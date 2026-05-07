import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNS_DIR = Path("reports") / "runs"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _run_id() -> str:
    return _utc_now().strftime("%Y%m%d_%H%M%S")


def start_run_dashboard() -> dict[str, Any]:
    started_at = _utc_now()
    run_id = _run_id()
    return {
        "run_id": run_id,
        "status": "running",
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": "",
        "duration_seconds": 0,
        "github": {},
        "testcases": {
            "generated_count": 0,
            "uploaded_to_testlink": 0,
            "obsolete_marked": 0,
            "regeneration_skipped": False,
        },
        "pytest": {
            "exit_code": None,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "report_path": "reports/report.html",
        },
        "mantisbt": {
            "created": 0,
            "updated": 0,
            "reopened": 0,
            "closed": 0,
            "failed": 0,
        },
    }


def mantis_events_path(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}_mantis_events.jsonl"


def record_mantis_event(action: str, testcase_name: str = "", issue_id: str | int = "") -> None:
    import os

    run_id = os.getenv("PIPELINE_RUN_ID", "").strip()
    if not run_id:
        return

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "action": action,
        "testcase_name": testcase_name,
        "issue_id": str(issue_id or ""),
        "created_at_utc": _utc_now().isoformat(),
    }
    with mantis_events_path(run_id).open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, separators=(",", ":")) + "\n")


def apply_mantis_events(dashboard: dict[str, Any]) -> None:
    path = mantis_events_path(str(dashboard.get("run_id", "")))
    if not path.exists():
        return

    counts = dashboard.setdefault("mantisbt", {})
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        action = str(event.get("action", "")).strip()
        if action:
            counts[action] = int(counts.get(action, 0) or 0) + 1


def parse_pytest_summary(output: str, exit_code: int) -> dict[str, int | None]:
    result: dict[str, int | None] = {
        "exit_code": exit_code,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
    }
    for line in reversed(output.splitlines()):
        clean = line.strip("= ").lower()
        if " in " not in clean:
            continue
        for key in ("passed", "failed", "skipped", "error", "errors"):
            marker = f" {key}"
            if marker not in f" {clean}":
                continue
            words = clean.replace(",", " ").split()
            for index, word in enumerate(words):
                if word in {key, key.rstrip("s")} and index > 0 and words[index - 1].isdigit():
                    normalized_key = "errors" if key in {"error", "errors"} else key
                    result[normalized_key] = int(words[index - 1])
        if any(int(result.get(key, 0) or 0) for key in ("passed", "failed", "skipped", "errors")):
            break
    return result


def finish_run_dashboard(dashboard: dict[str, Any], status: str) -> dict[str, Any]:
    finished_at = _utc_now()
    started_at = datetime.fromisoformat(str(dashboard["started_at_utc"]))
    dashboard["status"] = status
    dashboard["finished_at_utc"] = finished_at.isoformat()
    dashboard["duration_seconds"] = round((finished_at - started_at).total_seconds(), 2)
    apply_mantis_events(dashboard)
    return dashboard


def save_run_dashboard(dashboard: dict[str, Any]) -> tuple[Path, Path]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = str(dashboard["run_id"])
    json_path = RUNS_DIR / f"{run_id}.json"
    html_path = RUNS_DIR / f"{run_id}.html"
    latest_path = RUNS_DIR / "latest.html"

    json_path.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")
    html_path.write_text(_render_html(dashboard), encoding="utf-8")
    shutil.copyfile(html_path, latest_path)
    return json_path, html_path


def _status_class(status: str) -> str:
    return "success" if status == "success" else "failed" if status == "failed" else "running"


def _metric(label: str, value: Any) -> str:
    return f"<section><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></section>"


def _render_html(dashboard: dict[str, Any]) -> str:
    github = dashboard.get("github", {})
    testcases = dashboard.get("testcases", {})
    pytest = dashboard.get("pytest", {})
    mantisbt = dashboard.get("mantisbt", {})
    status = str(dashboard.get("status", "unknown"))
    status_class = _status_class(status)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Automation Pipeline Run {html.escape(str(dashboard.get("run_id", "")))}</title>
  <style>
    body {{ margin: 0; font-family: "Segoe UI", sans-serif; color: #18212f; background: #f5f7fb; }}
    header {{ padding: 28px 36px; background: #172033; color: white; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; font-weight: 700; }}
    header p {{ margin: 0; color: #cdd6e4; }}
    main {{ padding: 28px 36px; max-width: 1180px; }}
    .status {{ display: inline-block; margin-top: 16px; padding: 8px 12px; border-radius: 6px; font-weight: 700; text-transform: uppercase; }}
    .success {{ background: #dff6e7; color: #176535; }}
    .failed {{ background: #fde5e5; color: #a12525; }}
    .running {{ background: #fff2c8; color: #7a5600; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin: 22px 0 30px; }}
    section {{ background: white; border: 1px solid #dfe5ef; border-radius: 8px; padding: 16px; }}
    section span {{ display: block; color: #667085; font-size: 13px; margin-bottom: 8px; }}
    section strong {{ display: block; font-size: 22px; overflow-wrap: anywhere; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #dfe5ef; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid #edf1f7; vertical-align: top; }}
    th {{ background: #eef3fa; color: #344054; }}
    tr:last-child td {{ border-bottom: 0; }}
    a {{ color: #1457a8; }}
  </style>
</head>
<body>
  <header>
    <h1>Automation Pipeline Run</h1>
    <p>Run ID: {html.escape(str(dashboard.get("run_id", "")))}</p>
    <div class="status {status_class}">{html.escape(status)}</div>
  </header>
  <main>
    <div class="grid">
      {_metric("Duration", f"{dashboard.get('duration_seconds', 0)} seconds")}
      {_metric("Generated Testcases", testcases.get("generated_count", 0))}
      {_metric("Uploaded To TestLink", testcases.get("uploaded_to_testlink", 0))}
      {_metric("Pytest Result", f"{pytest.get('passed', 0)} passed / {pytest.get('failed', 0)} failed")}
      {_metric("Mantis Issues", f"{mantisbt.get('created', 0)} created, {mantisbt.get('reopened', 0)} reopened, {mantisbt.get('closed', 0)} closed")}
      {_metric("Final Status", status)}
    </div>

    <h2>GitHub</h2>
    <table>
      <tr><th>Field</th><th>Value</th></tr>
      <tr><td>Repository</td><td>{html.escape(str(github.get("repo", "")))}</td></tr>
      <tr><td>Branch</td><td>{html.escape(str(github.get("branch", "")))}</td></tr>
      <tr><td>Requirement Commit</td><td>{html.escape(str(github.get("requirement_commit_id", "")))}</td></tr>
      <tr><td>Design Commit</td><td>{html.escape(str(github.get("design_commit_id", "")))}</td></tr>
    </table>

    <h2>Pipeline Metrics</h2>
    <table>
      <tr><th>Area</th><th>Metric</th><th>Value</th></tr>
      <tr><td>Testcases</td><td>Regeneration Skipped</td><td>{html.escape(str(testcases.get("regeneration_skipped", False)))}</td></tr>
      <tr><td>Testcases</td><td>Obsolete Marked</td><td>{html.escape(str(testcases.get("obsolete_marked", 0)))}</td></tr>
      <tr><td>Pytest</td><td>Exit Code</td><td>{html.escape(str(pytest.get("exit_code", "")))}</td></tr>
      <tr><td>Pytest</td><td>Skipped / Errors</td><td>{html.escape(str(pytest.get("skipped", 0)))} skipped / {html.escape(str(pytest.get("errors", 0)))} errors</td></tr>
      <tr><td>MantisBT</td><td>Updated / Failed</td><td>{html.escape(str(mantisbt.get("updated", 0)))} updated / {html.escape(str(mantisbt.get("failed", 0)))} failed</td></tr>
    </table>

    <h2>Reports</h2>
    <table>
      <tr><th>Report</th><th>Path</th></tr>
      <tr><td>Pytest HTML</td><td><a href="../report.html">reports/report.html</a></td></tr>
      <tr><td>Run JSON</td><td>{html.escape(str(dashboard.get("run_id", "")))}.json</td></tr>
    </table>
  </main>
</body>
</html>
"""

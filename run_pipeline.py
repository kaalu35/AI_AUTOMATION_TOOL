import subprocess
import sys
import json
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def run_pytest() -> tuple[int, dict[str, Any]]:
    log_info("Executing generated Playwright pytest tests.")
    report_dir = ROOT_DIR / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "generated_tests",
        "--html=reports/report.html",
        "--self-contained-html",
    ]
    completed = subprocess.run(command, cwd=ROOT_DIR, capture_output=True, text=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)

    from run_dashboard import parse_pytest_summary

    combined_output = "\n".join([completed.stdout or "", completed.stderr or ""])
    return completed.returncode, parse_pytest_summary(combined_output, completed.returncode)


def _generated_test_exists() -> bool:
    return (ROOT_DIR / "generated_tests" / "test_calculator_generated.py").exists()


def main() -> int:
    original_cwd = Path.cwd()
    dashboard = None
    try:
        import os

        os.chdir(ROOT_DIR)
        if "--health-check" in sys.argv:
            from health_check import run_health_check

            return run_health_check()

        log_info("Starting AI automation pipeline.")

        from setup_installer import setup_environment

        setup_environment()

        from ai_generator import generate_testcases
        from data_loader import load_testcases, load_testcases_from_testlink
        from github_fetcher import fetch_or_create_requirements_and_design_with_metadata
        from impact_analyzer import run_requirement_impact_analysis
        from playwright_generator import generate_playwright_tests
        from run_dashboard import finish_run_dashboard, save_run_dashboard, start_run_dashboard
        from run_metadata import (
            load_run_metadata,
            load_source_snapshot,
            save_run_metadata,
            save_source_snapshot,
            source_changed,
        )
        from testcase_reviewer import review_generated_testcases
        from testlink_uploader import upload_testcases

        dashboard = start_run_dashboard()
        os.environ["PIPELINE_RUN_ID"] = str(dashboard["run_id"])

        log_info("Fetching requirement.txt and design.txt from GitHub.")
        requirement, design, current_metadata = fetch_or_create_requirements_and_design_with_metadata()
        dashboard["github"] = current_metadata
        previous_metadata = load_run_metadata()

        if source_changed(previous_metadata, current_metadata):
            log_info("Requirement/design change detected. Starting selective regeneration workflow.")

            testcases = None
            source_snapshot = load_source_snapshot()
            if source_snapshot.get("requirement") and source_snapshot.get("design"):
                try:
                    log_info("Analyzing requirement/design impact before regenerating testcases.")
                    existing_testcases = load_testcases_from_testlink()
                    testcases, impact_report = run_requirement_impact_analysis(
                        previous_requirement=str(source_snapshot.get("requirement", "")),
                        previous_design=str(source_snapshot.get("design", "")),
                        current_requirement=requirement,
                        current_design=design,
                        existing_testcases=existing_testcases,
                    )
                    dashboard["testcases"]["impact_analysis_enabled"] = True
                    dashboard["testcases"]["impact_keep"] = impact_report.get("kept", 0)
                    dashboard["testcases"]["impact_update"] = impact_report.get("updated", 0)
                    dashboard["testcases"]["impact_create"] = impact_report.get("created", 0)
                    dashboard["testcases"]["impact_obsolete"] = impact_report.get("obsolete", 0)
                    Path("generated_data").mkdir(parents=True, exist_ok=True)
                    Path("generated_data/testcases.json").write_text(
                        json.dumps({"testcases": testcases}, indent=2),
                        encoding="utf-8",
                    )
                except Exception as exc:
                    log_error(f"Requirement impact analysis failed. Falling back to full regeneration: {exc}")

            if testcases is None:
                log_info("Merging requirement and design, then generating strict JSON testcases.")
                generate_testcases(requirement, design)

                log_info("Loading validated testcase JSON.")
                testcases = load_testcases()
                dashboard["testcases"]["impact_analysis_enabled"] = False

            dashboard["testcases"]["generated_count"] = len(testcases)
            log_success(f"Loaded {len(testcases)} generated testcase(s).")

            log_info("Reviewing generated testcases before TestLink upload.")
            review_generated_testcases(testcases)

            log_info("Uploading testcases into TestLink.")
            upload_metrics = upload_testcases(testcases)
            dashboard["testcases"]["uploaded_to_testlink"] = upload_metrics.get("uploaded", 0)
            dashboard["testcases"]["obsolete_marked"] = upload_metrics.get("obsolete_marked", 0)

            log_info("Generating Playwright pytest scripts.")
            generate_playwright_tests()
            save_run_metadata(current_metadata)
            save_source_snapshot(requirement, design, current_metadata)
        else:
            log_info("No requirement/design change detected. Skipping regeneration and TestLink upload.")
            dashboard["testcases"]["regeneration_skipped"] = True
            if not load_source_snapshot():
                save_source_snapshot(requirement, design, current_metadata)
            if not _generated_test_exists():
                log_info("Generated Playwright script is missing. Rebuilding it from current TestLink data.")
                generate_playwright_tests()

        exit_code, pytest_metrics = run_pytest()
        dashboard["pytest"].update(pytest_metrics)
        if exit_code == 0:
            log_success("Pipeline completed successfully.")
            finish_run_dashboard(dashboard, "success")
        else:
            log_error(f"Pipeline completed with failing tests. Pytest exit code: {exit_code}")
            finish_run_dashboard(dashboard, "failed")
        json_path, html_path = save_run_dashboard(dashboard)
        log_success(f"Run dashboard saved: {html_path}")
        log_info(f"Run dashboard JSON saved: {json_path}")
        return exit_code
    except Exception as exc:
        log_error(str(exc))
        if dashboard is not None:
            try:
                from run_dashboard import finish_run_dashboard, save_run_dashboard

                finish_run_dashboard(dashboard, "failed")
                _, html_path = save_run_dashboard(dashboard)
                log_info(f"Run dashboard saved after failure: {html_path}")
            except Exception as dashboard_exc:
                log_error(f"Could not save run dashboard: {dashboard_exc}")
        return 1
    finally:
        import os

        os.chdir(original_cwd)


if __name__ == "__main__":
    raise SystemExit(main())

import base64
import hashlib
import json
import platform
import re
import socket
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import config
from run_metadata import load_run_metadata


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def _record_event(action: str, testcase_name: str = "", issue_id: str | int = "") -> None:
    try:
        from run_dashboard import record_mantis_event

        record_mantis_event(action, testcase_name=testcase_name, issue_id=issue_id)
    except Exception:
        pass


def _mantis_enabled() -> bool:
    if not config.ENABLE_MANTISBT_BUG_CREATION:
        return False
    if not config.MANTISBT_URL:
        log_error("Skipping MantisBT sync. MANTISBT_URL is missing.")
        return False
    if not (config.MANTISBT_API_TOKEN or (config.MANTISBT_USERNAME and config.MANTISBT_PASSWORD)):
        log_error(
            "Skipping MantisBT sync. Provide MANTISBT_API_TOKEN or "
            "MANTISBT_USERNAME and MANTISBT_PASSWORD."
        )
        return False
    if not (config.MANTISBT_PROJECT_ID or config.MANTISBT_PROJECT_NAME):
        log_error(
            "Skipping MantisBT sync. Provide MANTISBT_PROJECT_ID or "
            "MANTISBT_PROJECT_NAME."
        )
        return False
    return True


def _api_url(path: str, query: dict[str, Any] | None = None) -> str:
    base = f"{config.MANTISBT_URL.rstrip('/')}/{path.lstrip('/')}"
    if not query:
        return base
    encoded = parse.urlencode({key: value for key, value in query.items() if value not in (None, "")})
    return f"{base}?{encoded}" if encoded else base


def _headers(content_type: str = "application/json") -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    if config.MANTISBT_API_TOKEN:
        headers["Authorization"] = config.MANTISBT_API_TOKEN
    else:
        token = base64.b64encode(
            f"{config.MANTISBT_USERNAME}:{config.MANTISBT_PASSWORD}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return headers


def _request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        _api_url(path, query=query),
        data=data,
        headers=_headers(),
        method=method,
    )
    with request.urlopen(http_request, timeout=60) as response:
        response_text = response.read().decode("utf-8").strip()
    if not response_text:
        return {}
    return json.loads(response_text)


def _severity_for_failure(error_message: str) -> str:
    text = str(error_message).lower()
    if any(token in text for token in ("timeout", "locator", "selector", "unsupported playwright action")):
        return "minor"
    if any(token in text for token in ("crash", "500", "exception", "fatal")):
        return "crash"
    return config.MANTISBT_SEVERITY


def _priority_for_failure(error_message: str) -> str:
    text = str(error_message).lower()
    if any(token in text for token in ("checkout", "login", "payment", "critical", "blocker")):
        return "high"
    if any(token in text for token in ("selector", "locator", "timeout")):
        return "normal"
    return config.MANTISBT_PRIORITY


def _expected_result_from_testcase(testcase: dict[str, Any]) -> str:
    testdata = testcase.get("testdata", {})
    if testdata.get("expected"):
        return str(testdata.get("expected"))
    assertions = testdata.get("assertions", [])
    if assertions:
        parts = []
        for assertion in assertions:
            if isinstance(assertion, dict):
                selector = assertion.get("selector", "")
                expected = assertion.get("expected") or assertion.get("expected_text") or ""
                parts.append(f"{selector}: {expected}".strip(": "))
        if parts:
            return "; ".join(parts)
    steps = testcase.get("steps", [])
    if steps:
        final_step = steps[-1]
        if isinstance(final_step, dict):
            return str(final_step.get("expected_results") or "")
    return "Expected result not available in testcase payload."


def _testcase_key(testcase: dict[str, Any]) -> str:
    testlink = testcase.get("testlink", {})
    if isinstance(testlink, dict):
        external_id = str(testlink.get("external_id", "")).strip()
        if external_id:
            return external_id
    return str(testcase.get("name", "")).strip().lower()


def _normalized_error(error_message: str) -> str:
    text = str(error_message or "").strip().lower()
    text = re.sub(r"\b\d{8}_\d{6}\b", "<timestamp>", text)
    text = re.sub(r"[a-z]:\\[^\s)]+", "<path>", text, flags=re.IGNORECASE)
    text = re.sub(r"line \d+", "line <n>", text)
    text = re.sub(r"timeout \d+ms", "timeout <n>ms", text)
    text = re.sub(r"\s+", " ", text)
    return text[:600]


def _failure_fingerprint(testcase: dict[str, Any], error_message: str) -> str:
    raw = f"{_testcase_key(testcase)}|{_normalized_error(error_message)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _steps_to_reproduce(testcase: dict[str, Any]) -> str:
    steps = testcase.get("steps", [])
    if not steps:
        return "Generated testcase does not include step-by-step actions."
    lines = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        action = str(step.get("actions") or "").strip()
        expected = str(step.get("expected_results") or "").strip()
        if expected:
            lines.append(f"{index}. {action} | Expected: {expected}")
        else:
            lines.append(f"{index}. {action}")
    return "\n".join(lines) or "Generated testcase does not include step-by-step actions."


def _additional_information(
    testcase: dict[str, Any],
    current_url: str,
    error_message: str,
    screenshot_path: str,
    log_path: str,
    video_path: str,
    stack_trace: str,
) -> str:
    metadata = load_run_metadata()
    fingerprint = _failure_fingerprint(testcase, error_message)
    lines = [
        f"Automation Failure Fingerprint: {fingerprint}",
        f"Current URL: {current_url}",
        f"Error Message: {error_message}",
        f"TestLink External ID: {testcase.get('testlink', {}).get('external_id', '')}",
        f"TestLink Internal ID: {testcase.get('testlink', {}).get('internal_id', '')}",
        f"Build: {config.TESTLINK_BUILD_NAME}",
        f"Project: {config.REPO_NAME}",
        f"Requirement Commit ID: {metadata.get('requirement_commit_id', '')}",
        f"Design Commit ID: {metadata.get('design_commit_id', '')}",
        f"Browser: Chromium",
        f"Host: {socket.gethostname()}",
        f"OS: {platform.platform()}",
        f"Generated Script: generated_tests/test_calculator_generated.py",
        f"Screenshot: {screenshot_path}",
        f"Execution Log: {log_path}",
        f"Video: {video_path}",
    ]
    if testcase.get("testdata"):
        lines.append("Test Data:")
        lines.append(json.dumps(testcase.get("testdata", {}), indent=2))
    if stack_trace:
        lines.append("Stack Trace:")
        lines.append(stack_trace)
    return "\n".join(line for line in lines if line is not None)


def _description(testcase: dict[str, Any], error_message: str, current_url: str) -> str:
    metadata = load_run_metadata()
    expected_result = _expected_result_from_testcase(testcase)
    testcase_summary = testcase.get("summary", "")
    fingerprint = _failure_fingerprint(testcase, error_message)
    return "\n".join(
        [
            f"Automation Failure Fingerprint: {fingerprint}",
            f"Test Case Name: {testcase.get('name', '')}",
            f"Test Case Summary: {testcase_summary}",
            f"Expected Result: {expected_result}",
            f"Actual Result: {error_message}",
            f"Failed URL: {current_url}",
            f"Requirement Commit ID: {metadata.get('requirement_commit_id', '')}",
            f"Design Commit ID: {metadata.get('design_commit_id', '')}",
        ]
    )


def _issue_summary(testcase: dict[str, Any]) -> str:
    return f"[Automation Failure] {testcase.get('name', 'Generated Test Case')} | Chromium"


def _project_payload() -> dict[str, Any]:
    if config.MANTISBT_PROJECT_ID:
        return {"id": config.MANTISBT_PROJECT_ID}
    return {"name": config.MANTISBT_PROJECT_NAME}


def _attachment_entry(path: str) -> dict[str, str] | None:
    if not path:
        return None
    attachment_path = Path(path)
    if not attachment_path.exists() or not attachment_path.is_file():
        return None
    size_mb = attachment_path.stat().st_size / (1024 * 1024)
    if size_mb > config.MANTISBT_MAX_INLINE_ATTACHMENT_MB:
        log_info(
            f"Skipping MantisBT attachment '{attachment_path.name}' because it exceeds "
            f"{config.MANTISBT_MAX_INLINE_ATTACHMENT_MB} MB."
        )
        return None
    return {
        "name": attachment_path.name,
        "content": base64.b64encode(attachment_path.read_bytes()).decode("ascii"),
    }


def _build_issue_payload(
    testcase: dict[str, Any],
    error_message: str,
    screenshot_path: str,
    log_path: str,
    video_path: str,
    stack_trace: str,
    current_url: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": _issue_summary(testcase),
        "description": _description(testcase, error_message, current_url),
        "steps_to_reproduce": _steps_to_reproduce(testcase),
        "additional_information": _additional_information(
            testcase=testcase,
            current_url=current_url,
            error_message=error_message,
            screenshot_path=screenshot_path,
            log_path=log_path,
            video_path=video_path,
            stack_trace=stack_trace,
        ),
        "project": _project_payload(),
        "category": {"name": config.MANTISBT_CATEGORY},
        "priority": {"name": _priority_for_failure(error_message)},
        "severity": {"name": _severity_for_failure(error_message)},
        "reproducibility": {"name": config.MANTISBT_REPRODUCIBILITY},
    }
    if config.MANTISBT_HANDLER_ID:
        payload["handler"] = {"id": config.MANTISBT_HANDLER_ID}
    return payload


def _issue_note_text(
    testcase: dict[str, Any],
    status: str,
    notes: str,
    current_url: str,
    stack_trace: str,
) -> str:
    metadata = load_run_metadata()
    lines = [
        f"Automation result: {'PASSED' if status == 'p' else 'FAILED'}",
        f"Test Case: {testcase.get('name', '')}",
        f"TestLink External ID: {testcase.get('testlink', {}).get('external_id', '')}",
        f"Current URL: {current_url}",
        f"Notes: {notes}",
        f"Requirement Commit ID: {metadata.get('requirement_commit_id', '')}",
        f"Design Commit ID: {metadata.get('design_commit_id', '')}",
    ]
    if status == "f":
        lines.insert(1, f"Automation Failure Fingerprint: {_failure_fingerprint(testcase, notes)}")
    if stack_trace and status == "f":
        lines.extend(["Stack Trace:", stack_trace])
    return "\n".join(lines)


def _note_attachments(screenshot_path: str, log_path: str, video_path: str) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for path in (screenshot_path, log_path):
        entry = _attachment_entry(path)
        if entry:
            files.append(entry)
    if config.MANTISBT_ATTACH_VIDEO:
        entry = _attachment_entry(video_path)
        if entry:
            files.append(entry)
    return files


def _list_project_issues() -> list[dict[str, Any]]:
    project_id = config.MANTISBT_PROJECT_ID
    page = 1
    issues: list[dict[str, Any]] = []
    while True:
        response = _request_json(
            "GET",
            "issues",
            query={"project_id": project_id, "page": page, "page_size": 100},
        )
        page_issues = response.get("issues", []) if isinstance(response, dict) else []
        if not isinstance(page_issues, list) or not page_issues:
            break
        issues.extend(issue for issue in page_issues if isinstance(issue, dict))
        if len(page_issues) < 100:
            break
        page += 1
    return issues


def _issue_text(issue: dict[str, Any]) -> str:
    parts = [
        str(issue.get("summary", "")),
        str(issue.get("description", "")),
        str(issue.get("additional_information", "")),
        str(issue.get("steps_to_reproduce", "")),
    ]
    notes = issue.get("notes", [])
    if isinstance(notes, list):
        for note in notes:
            if isinstance(note, dict):
                parts.append(str(note.get("text", "")))
    return "\n".join(parts)


def _get_issue(issue_id: int) -> dict[str, Any]:
    response = _request_json("GET", f"issues/{issue_id}")
    issue = response.get("issues", response.get("issue", {})) if isinstance(response, dict) else {}
    if isinstance(issue, list):
        return issue[0] if issue and isinstance(issue[0], dict) else {}
    return issue if isinstance(issue, dict) else {}


def _find_existing_issue(testcase: dict[str, Any], error_message: str = "") -> dict[str, Any] | None:
    target_summary = _issue_summary(testcase)
    matches = []
    for issue in _list_project_issues():
        if issue.get("summary") != target_summary:
            continue
        project = issue.get("project", {})
        project_id = int(project.get("id", 0) or 0) if isinstance(project, dict) else 0
        project_name = str(project.get("name", "")).strip() if isinstance(project, dict) else ""
        if config.MANTISBT_PROJECT_ID and project_id != config.MANTISBT_PROJECT_ID:
            continue
        if config.MANTISBT_PROJECT_NAME and project_name and project_name != config.MANTISBT_PROJECT_NAME:
            continue
        matches.append(issue)
    if not matches:
        return None
    matches = sorted(matches, key=lambda issue: int(issue.get("id", 0) or 0), reverse=True)
    if not error_message:
        return matches[0]

    fingerprint = _failure_fingerprint(testcase, error_message)
    saw_fingerprinted_issue = False
    for issue in matches:
        issue_id = int(issue.get("id", 0) or 0)
        detailed_issue = _get_issue(issue_id) if issue_id else issue
        text = _issue_text(detailed_issue or issue)
        if "Automation Failure Fingerprint:" in text:
            saw_fingerprinted_issue = True
        if fingerprint in text:
            return issue

    if saw_fingerprinted_issue:
        return None
    return matches[0]


def _status_name(issue: dict[str, Any]) -> str:
    status = issue.get("status", {})
    if isinstance(status, dict):
        return str(status.get("name", "")).strip().lower()
    return str(status or "").strip().lower()


def _is_closed_status(issue: dict[str, Any]) -> bool:
    return _status_name(issue) == str(config.MANTISBT_CLOSED_STATUS).strip().lower()


def _patch_issue(issue_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    return _request_json("PATCH", f"issues/{issue_id}", payload)


def _add_note(issue_id: int, text: str, files: list[dict[str, str]] | None = None) -> None:
    payload: dict[str, Any] = {"text": text}
    if files:
        payload["files"] = files
    _request_json("POST", f"issues/{issue_id}/notes", payload)


def _create_new_issue(
    testcase: dict[str, Any],
    error_message: str,
    screenshot_path: str,
    log_path: str,
    video_path: str,
    stack_trace: str,
    current_url: str,
) -> None:
    payload = _build_issue_payload(
        testcase=testcase,
        error_message=error_message,
        screenshot_path=screenshot_path,
        log_path=log_path,
        video_path=video_path,
        stack_trace=stack_trace,
        current_url=current_url,
    )
    files = _note_attachments(screenshot_path, log_path, video_path)
    if files:
        payload["files"] = files
    response = _request_json("POST", "issues", payload)
    issue = response.get("issue", {}) if isinstance(response, dict) else {}
    issue_id = issue.get("id", "")
    log_success(
        f"Created MantisBT issue {issue_id or '[unknown id]'} for failed testcase "
        f"'{testcase.get('name', '')}'."
    )
    _record_event("created", str(testcase.get("name", "")), issue_id)


def _reopen_issue(issue: dict[str, Any], testcase: dict[str, Any], note_text: str, files: list[dict[str, str]]) -> None:
    issue_id = int(issue.get("id", 0) or 0)
    if not issue_id:
        return
    _patch_issue(
        issue_id,
        {
            "status": {"name": config.MANTISBT_REOPEN_STATUS},
            "resolution": {"name": "reopened"},
        },
    )
    _add_note(issue_id, note_text, files)
    log_success(f"Reopened MantisBT issue {issue_id} for testcase '{testcase.get('name', '')}'.")
    _record_event("reopened", str(testcase.get("name", "")), issue_id)


def _update_open_issue(issue: dict[str, Any], testcase: dict[str, Any], note_text: str, files: list[dict[str, str]]) -> None:
    issue_id = int(issue.get("id", 0) or 0)
    if not issue_id:
        return
    _add_note(issue_id, note_text, files)
    log_info(f"Updated existing open MantisBT issue {issue_id} for testcase '{testcase.get('name', '')}'.")
    _record_event("updated", str(testcase.get("name", "")), issue_id)


def _close_issue(issue: dict[str, Any], testcase: dict[str, Any], note_text: str) -> None:
    issue_id = int(issue.get("id", 0) or 0)
    if not issue_id:
        return
    _patch_issue(
        issue_id,
        {
            "status": {"name": config.MANTISBT_CLOSED_STATUS},
            "resolution": {"name": "fixed"},
        },
    )
    _add_note(issue_id, note_text, [])
    log_success(f"Closed MantisBT issue {issue_id} because testcase passed: '{testcase.get('name', '')}'.")
    _record_event("closed", str(testcase.get("name", "")), issue_id)


def sync_issue_for_test_result(
    testcase: dict[str, Any],
    status: str,
    notes: str,
    screenshot_path: str = "",
    log_path: str = "",
    video_path: str = "",
    stack_trace: str = "",
    current_url: str = "",
) -> None:
    if not _mantis_enabled():
        return

    try:
        issue = _find_existing_issue(testcase, notes if status == "f" else "")
        note_text = _issue_note_text(
            testcase=testcase,
            status=status,
            notes=notes,
            current_url=current_url,
            stack_trace=stack_trace,
        )
        files = _note_attachments(screenshot_path, log_path, video_path)

        if status == "p":
            if issue and not _is_closed_status(issue) and config.MANTISBT_CLOSE_ON_PASS:
                _close_issue(issue, testcase, note_text)
            return

        if issue:
            if _is_closed_status(issue) and config.MANTISBT_REOPEN_ON_FAILURE:
                _reopen_issue(issue, testcase, note_text, files)
            else:
                _update_open_issue(issue, testcase, note_text, files)
            return

        _create_new_issue(
            testcase=testcase,
            error_message=notes,
            screenshot_path=screenshot_path,
            log_path=log_path,
            video_path=video_path,
            stack_trace=stack_trace,
            current_url=current_url,
        )
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        log_error(f"MantisBT issue sync failed with HTTP {exc.code}: {body or exc.reason}")
        _record_event("failed", str(testcase.get("name", "")))
    except Exception as exc:
        log_error(f"MantisBT issue sync failed: {exc}")
        _record_event("failed", str(testcase.get("name", "")))


def create_issue_for_failure(
    testcase: dict[str, Any],
    error_message: str,
    screenshot_path: str = "",
    log_path: str = "",
    video_path: str = "",
    stack_trace: str = "",
    current_url: str = "",
) -> None:
    sync_issue_for_test_result(
        testcase=testcase,
        status="f",
        notes=error_message,
        screenshot_path=screenshot_path,
        log_path=log_path,
        video_path=video_path,
        stack_trace=stack_trace,
        current_url=current_url,
    )

from pathlib import Path
from typing import Any

import config


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def _results_enabled() -> bool:
    if not config.UPLOAD_RESULTS_TO_TESTLINK:
        log_info("TestLink execution result upload is disabled.")
        return False
    if not config.TESTLINK_TESTPLAN_ID:
        log_error("Skipping TestLink result upload. TESTLINK_TESTPLAN_ID is missing.")
        return False
    if not config.DEV_KEY:
        log_error("Skipping TestLink result upload. TESTLINK_DEV_KEY is missing.")
        return False
    return True


def _get_client():
    import testlink

    return testlink.TestlinkAPIClient(config.TESTLINK_URL, config.DEV_KEY)


def ensure_build(client) -> None:
    try:
        response = client.createBuild(
            testplanid=config.TESTLINK_TESTPLAN_ID,
            buildname=config.TESTLINK_BUILD_NAME,
            buildnotes="Created automatically by automation AI pipeline.",
            active=1,
            open=1,
        )
        if isinstance(response, list) and response and response[0].get("status") is False:
            log_info(f"Using existing or unavailable TestLink build: {config.TESTLINK_BUILD_NAME}")
        else:
            log_success(f"TestLink build ready: {config.TESTLINK_BUILD_NAME}")
    except Exception as exc:
        log_info(f"Continuing with configured TestLink build name. Build create/check failed: {exc}")


def _extract_execution_id(response: Any) -> str:
    if isinstance(response, list):
        for item in response:
            if isinstance(item, dict):
                for key in ("executionid", "execution_id", "id"):
                    if item.get(key):
                        return str(item[key])
    if isinstance(response, dict):
        for key in ("executionid", "execution_id", "id"):
            if response.get(key):
                return str(response[key])
    return ""


def _upload_attachment(client, execution_id: str, path: str | Path, title: str) -> None:
    if not execution_id:
        return
    attachment_path = Path(path)
    if not attachment_path.exists():
        return
    try:
        client.uploadExecutionAttachment(
            executionid=execution_id,
            attachmentfile=str(attachment_path),
            title=title,
            description=f"Automation artifact: {attachment_path.name}",
        )
        log_success(f"Uploaded TestLink attachment: {attachment_path.name}")
    except Exception as exc:
        log_error(f"Could not upload TestLink attachment '{attachment_path}': {exc}")


def upload_execution_result(
    testcase: dict[str, Any],
    status: str,
    notes: str,
    screenshot_path: str = "",
    log_path: str = "",
    video_path: str = "",
) -> None:
    if not _results_enabled():
        return

    external_id = str(testcase.get("testlink", {}).get("external_id") or "").strip()
    if not external_id:
        log_error(f"Skipping result upload because testcase has no TestLink external_id: {testcase.get('name')}")
        return

    try:
        client = _get_client()
        ensure_build(client)
        response = client.reportTCResult(
            testcaseexternalid=external_id,
            testplanid=config.TESTLINK_TESTPLAN_ID,
            buildname=config.TESTLINK_BUILD_NAME,
            status=status,
            notes=notes,
            overwrite=True,
            user=config.TESTLINK_AUTHOR_LOGIN,
        )
        if isinstance(response, list) and response and response[0].get("status") is False:
            log_error(f"TestLink rejected execution result for {external_id}: {response}")
            return

        execution_id = _extract_execution_id(response)
        for artifact_path, title in (
            (screenshot_path, "Failure Screenshot"),
            (log_path, "Execution Log"),
            (video_path, "Execution Video"),
        ):
            if artifact_path:
                _upload_attachment(client, execution_id, artifact_path, title)

        log_success(f"Uploaded TestLink execution result {status.upper()} for {external_id}.")
    except Exception as exc:
        log_error(f"Failed to upload TestLink execution result for {external_id}: {exc}")

import json
import re
from pathlib import Path
from typing import Any

import config
from testdata_schema_validator import (
    ValidationReport,
    save_validation_report,
    validate_raw_testlink_case,
)


URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
SUPPORTED_ACTIONS = {
    "fill",
    "type",
    "click",
    "select",
    "check",
    "uncheck",
    "assert_text",
    "assert_visible",
    "assert_value",
    "assert_url",
}


def _is_obsolete_testcase(raw_testcase: dict[str, Any]) -> bool:
    tag = str(config.TESTLINK_OBSOLETE_TAG or "").strip()
    if not tag:
        return False
    haystack = " ".join(
        [
            str(raw_testcase.get("preconditions", "")),
            str(raw_testcase.get("summary", "")),
        ]
    ).lower()
    return tag.lower() in haystack


def load_testcases(json_path: str | Path = "generated_data/testcases.json") -> list[dict[str, Any]]:
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Testcase file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    testcases = data.get("testcases")
    if not isinstance(testcases, list) or not testcases:
        raise ValueError("Testcase JSON must contain a non-empty testcases list.")

    return testcases


def _normalize_testdata(testdata: Any) -> dict[str, Any]:
    if not isinstance(testdata, dict):
        raise ValueError("TestLink testcase has invalid automation test data.")
    normalized = dict(testdata)
    normalized.setdefault("input1", "")
    normalized.setdefault("input2", "")
    normalized.setdefault("operator", "")
    normalized.setdefault("expected", "")
    normalized.setdefault("target_url", "")
    normalized.setdefault("selectors", {})
    normalized.setdefault("actions", [])
    normalized.setdefault("assertions", [])
    for key in ("input1", "input2", "operator", "expected", "target_url"):
        normalized[key] = str(normalized.get(key, ""))
    if not isinstance(normalized["selectors"], dict):
        normalized["selectors"] = {}
    if not isinstance(normalized["actions"], list):
        normalized["actions"] = []
    if not isinstance(normalized["assertions"], list):
        normalized["assertions"] = []
    if not normalized["expected"]:
        raise ValueError("TestLink testcase has no expected value in automation test data.")
    return normalized


def _normalize_selector(selector: str) -> str:
    selector = str(selector or "").strip()
    lowered = selector.lower()
    if lowered.startswith("xpath:"):
        return "xpath=" + selector.split(":", 1)[1].strip()
    return selector


def _pick_action_name(action_name: str, selector: str, value: str) -> str:
    lowered = str(action_name or "").strip().lower()
    if lowered in SUPPORTED_ACTIONS:
        return lowered

    parts = [part.strip() for part in lowered.replace(",", "|").split("|") if part.strip()]
    for part in parts:
        if part in SUPPORTED_ACTIONS:
            return part

    joined = " ".join([lowered, str(selector).lower(), str(value).lower()])
    if any(token in joined for token in ("username", "password", "first name", "last name", "postal", "zip")):
        return "fill"
    if "url" in joined:
        return "assert_url"
    if any(token in joined for token in ("visible", "displayed", "shown")):
        return "assert_visible"
    if any(token in joined for token in ("text", "message", "error")):
        return "assert_text"
    return "click"


def _repair_action(action: dict[str, Any]) -> dict[str, Any]:
    selector = str(action.get("selector") or action.get("locator") or "").strip()
    value = str(
        action.get("value")
        or action.get("text")
        or action.get("expected")
        or action.get("expected_from_testdata")
        or ""
    ).strip()
    raw_action = str(action.get("action", "")).strip()

    if "|" in raw_action and not selector:
        parts = [part.strip() for part in raw_action.split("|") if part.strip()]
        for part in parts[1:]:
            if part.lower().startswith("xpath:") or part.startswith("//") or any(
                token in part.lower() for token in ("#", "[", "text=", "button", "input")
            ):
                selector = part
                break

    if not selector and any(token in value.lower() for token in ("username", "password", "first name", "last name", "postal", "zip")):
        selector = value

    return {
        "selector": _normalize_selector(selector),
        "action": _pick_action_name(raw_action, selector, value),
        "value": value,
    }


def _repair_assertion(assertion: dict[str, Any]) -> dict[str, Any]:
    selector = _normalize_selector(str(assertion.get("selector", "")).strip())
    assertion_type = str(assertion.get("assertion_type", "text")).strip().lower()
    expected = str(
        assertion.get("expected")
        or assertion.get("expected_text")
        or assertion.get("expected_from_testdata")
        or ""
    ).strip()
    if assertion_type not in {"text", "visible", "url", "value"}:
        joined = " ".join([selector.lower(), expected.lower()])
        if "url" in joined or expected.startswith("http"):
            assertion_type = "url"
        elif any(token in joined for token in ("visible", "displayed", "shown")):
            assertion_type = "visible"
        else:
            assertion_type = "text"
    return {
        "selector": selector,
        "assertion_type": assertion_type,
        "expected": expected,
    }


def _repair_testcase_payload(testcase: dict[str, Any]) -> dict[str, Any]:
    testdata = dict(testcase.get("testdata", {}))
    raw_actions = testdata.get("actions") or testcase.get("actions") or []
    raw_assertions = testdata.get("assertions") or testcase.get("assertions") or []
    testdata["actions"] = [
        repaired
        for repaired in (_repair_action(action) for action in raw_actions if isinstance(action, dict))
        if repaired.get("action")
    ]
    testdata["assertions"] = [
        _repair_assertion(assertion)
        for assertion in raw_assertions
        if isinstance(assertion, dict)
    ]
    testcase = dict(testcase)
    testcase["testdata"] = testdata
    if not str(testdata.get("target_url", "")).strip():
        testdata["target_url"] = _infer_target_url(testcase)
    if not str(testdata.get("target_url", "")).strip():
        raise ValueError(
            f"Testcase '{testcase.get('name', '')}' has no target_url. "
            "Execution must come from GitHub requirement/design data, not an inferred fallback."
        )
    if not testdata["actions"]:
        raise ValueError(
            f"Testcase '{testcase.get('name', '')}' has no executable actions. "
            "Regenerate the testcase with Playwright-ready actions/selectors."
        )
    if not testdata["assertions"] and not testdata.get("selectors", {}).get("result"):
        raise ValueError(
            f"Testcase '{testcase.get('name', '')}' has no assertions. "
            "Regenerate the testcase with deterministic assertions."
        )
    return testcase


def _infer_target_url(testcase: dict[str, Any]) -> str:
    searchable_values = [
        testcase.get("summary", ""),
        testcase.get("expected", ""),
    ]
    searchable_values.extend(str(step) for step in testcase.get("steps", []))
    testdata = testcase.get("testdata", {})
    if isinstance(testdata, dict):
        searchable_values.extend(str(value) for value in testdata.values())

    for value in searchable_values:
        match = URL_PATTERN.search(str(value))
        if match:
            return match.group(0).rstrip(".,)")
    return ""


def _normalize_custom_field_payload(payload: Any, raw_testcase: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("TestLink custom field must contain a JSON object.")
    if "testdata" in payload:
        testdata = _normalize_testdata(payload["testdata"])
        if not testdata.get("target_url"):
            testdata["target_url"] = _infer_target_url(payload)
        testcase = {
            "name": str(payload.get("name") or raw_testcase.get("name") or "TestLink testcase"),
            "summary": str(payload.get("summary") or raw_testcase.get("summary") or ""),
            "steps": payload.get("steps", []),
            "testdata": testdata,
            "testlink": _testlink_metadata(raw_testcase),
        }
        return _repair_testcase_payload(testcase)
    legacy_payload = {
        "summary": raw_testcase.get("summary", ""),
        "steps": raw_testcase.get("steps", []),
        "testdata": payload,
    }
    testdata = _normalize_testdata(payload)
    if not testdata.get("target_url"):
        testdata["target_url"] = _infer_target_url(legacy_payload)
    testcase = {
        "name": str(raw_testcase.get("name") or raw_testcase.get("testcase_name") or "TestLink testcase"),
        "summary": str(raw_testcase.get("summary", "")),
        "steps": raw_testcase.get("steps", []),
        "testdata": testdata,
        "testlink": _testlink_metadata(raw_testcase),
    }
    return _repair_testcase_payload(testcase)


def _testlink_metadata(raw_testcase: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw_testcase.get("id"),
        "external_id": raw_testcase.get("external_id"),
        "version": raw_testcase.get("version", 1),
        "tcversion_id": raw_testcase.get("tcversion_id"),
    }


def _get_testlink_client():
    if not config.DEV_KEY:
        raise ValueError("TESTLINK_DEV_KEY or DEV_KEY is required to load test data from TestLink.")
    if not config.SUITE_ID:
        raise ValueError("TESTLINK_SUITE_ID or SUITE_ID is required to load test data from TestLink.")

    import testlink

    return testlink.TestlinkAPIClient(config.TESTLINK_URL, config.DEV_KEY)


def load_testcases_from_testlink() -> list[dict[str, Any]]:
    client = _get_testlink_client()
    raw_testcases = client.getTestCasesForTestSuite(
        testsuiteid=config.SUITE_ID,
        deep=True,
        details="full",
    )

    if not raw_testcases:
        raise ValueError(f"No testcases found in TestLink suite id {config.SUITE_ID}.")

    latest_testcase_by_name: dict[str, dict[str, Any]] = {}
    for raw_testcase in raw_testcases:
        if not isinstance(raw_testcase, dict):
            continue
        testcase_name = str(
            raw_testcase.get("name")
            or raw_testcase.get("testcase_name")
            or f"TestLink testcase {raw_testcase.get('id', '')}"
        )
        existing = latest_testcase_by_name.get(testcase_name)
        if existing is None or int(raw_testcase.get("id", 0)) > int(existing.get("id", 0)):
            latest_testcase_by_name[testcase_name] = raw_testcase

    loaded_testcases = []
    validation_report = ValidationReport()
    for raw_testcase in latest_testcase_by_name.values():
        if not isinstance(raw_testcase, dict):
            continue
        if _is_obsolete_testcase(raw_testcase):
            continue

        external_id = raw_testcase.get("external_id")
        version = raw_testcase.get("version", 1)
        if not external_id:
            continue

        custom_field_value = client.getTestCaseCustomFieldDesignValue(
            testcaseexternalid=str(external_id),
            version=int(version),
            testprojectid=config.PROJECT_ID,
            customfieldname=config.TESTLINK_CUSTOM_FIELD_NAME,
            details="value",
        )
        if not custom_field_value:
            validation_report.skipped += 1
            continue

        if not validate_raw_testlink_case(raw_testcase, custom_field_value, validation_report):
            continue

        try:
            payload = json.loads(str(custom_field_value))
            loaded_testcases.append(_normalize_custom_field_payload(payload, raw_testcase))
        except (json.JSONDecodeError, ValueError) as exc:
            validation_report.add_error(
                str(raw_testcase.get("name") or raw_testcase.get("testcase_name") or raw_testcase.get("external_id") or "Unknown testcase"),
                str(raw_testcase.get("external_id") or raw_testcase.get("id") or ""),
                str(exc),
            )
            continue

    report_path = save_validation_report(validation_report)
    if validation_report.errors:
        for error in validation_report.errors:
            print(
                "[ERROR] Invalid TestLink automation test data "
                f"for {error['testcase']} ({error['external_id']}): {error['reason']}"
            )
        print(f"[INFO] Test data validation report saved: {report_path}")

    if not loaded_testcases:
        raise ValueError(
            f"No TestLink testcases contained custom field '{config.TESTLINK_CUSTOM_FIELD_NAME}'. "
            "Run the pipeline upload step before executing Playwright tests."
        )

    return loaded_testcases

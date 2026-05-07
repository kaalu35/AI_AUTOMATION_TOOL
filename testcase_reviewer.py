import json
from pathlib import Path
from typing import Any

import config


REVIEW_PATH = Path("generated_data") / "review_summary.txt"
SELECTOR_REPORT_PATH = Path("generated_data") / "selector_validation_report.txt"
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
SUPPORTED_ASSERTIONS = {"text", "visible", "url", "value"}


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def _selector_warnings(testcase: dict[str, Any]) -> list[str]:
    warnings = []
    testdata = testcase.get("testdata", {})
    if not isinstance(testdata, dict):
        return ["testdata is not a JSON object."]

    actions = testdata.get("actions", [])
    assertions = testdata.get("assertions", [])
    selectors = testdata.get("selectors", {})

    if actions and not isinstance(actions, list):
        warnings.append("actions must be a list.")
        actions = []
    if assertions and not isinstance(assertions, list):
        warnings.append("assertions must be a list.")
        assertions = []
    if selectors and not isinstance(selectors, dict):
        warnings.append("selectors must be an object.")

    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            warnings.append(f"action {index} is not an object.")
            continue
        action_name = str(action.get("action", "")).strip().lower()
        selector = str(action.get("selector") or action.get("locator") or "").strip()
        if action_name not in SUPPORTED_ACTIONS:
            warnings.append(f"action {index} uses unsupported action '{action_name}'.")
        if action_name not in {"assert_url"} and not selector:
            warnings.append(f"action {index} is missing a selector.")

    for index, assertion in enumerate(assertions, start=1):
        if not isinstance(assertion, dict):
            warnings.append(f"assertion {index} is not an object.")
            continue
        assertion_type = str(assertion.get("assertion_type", "text")).strip().lower()
        selector = str(assertion.get("selector", "")).strip()
        if assertion_type not in SUPPORTED_ASSERTIONS:
            warnings.append(
                f"assertion {index} uses unsupported assertion_type '{assertion_type}'."
            )
        if assertion_type != "url" and not selector:
            warnings.append(f"assertion {index} is missing a selector.")

    if actions and not assertions:
        warnings.append("generic actions exist but assertions list is empty.")
    if not actions and not all(str(testdata.get(key, "")).strip() for key in ("input1", "operator", "expected")):
        warnings.append("no generic actions and calculator fallback data looks incomplete.")

    return warnings


def review_generated_testcases(testcases: list[dict[str, Any]]) -> None:
    if not config.REVIEW_GENERATED_TESTS:
        log_info("Generated testcase review is disabled.")
        return

    REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Generated Test Review",
        f"Total testcases: {len(testcases)}",
        "",
    ]
    total_warnings = 0
    seen_names: set[str] = set()

    for index, testcase in enumerate(testcases, start=1):
        name = str(testcase.get("name") or f"Testcase {index}")
        warnings = _selector_warnings(testcase)
        if name in seen_names:
            warnings.append("duplicate testcase name in generated JSON.")
        seen_names.add(name)
        total_warnings += len(warnings)
        lines.append(f"{index}. {name}")
        lines.append(f"   Expected: {testcase.get('testdata', {}).get('expected', '')}")
        if warnings:
            for warning in warnings:
                lines.append(f"   WARNING: {warning}")
        else:
            lines.append("   OK")

    REVIEW_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if total_warnings:
        log_error(f"Generated testcase review completed with {total_warnings} warning(s). See {REVIEW_PATH}.")
    else:
        log_success(f"Generated testcase review passed. See {REVIEW_PATH}.")


def write_selector_validation_report(testcases: list[dict[str, Any]]) -> None:
    SELECTOR_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "total_testcases": len(testcases),
        "testcases": [
            {
                "name": testcase.get("name", ""),
                "warnings": _selector_warnings(testcase),
            }
            for testcase in testcases
        ],
    }
    SELECTOR_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    warning_count = sum(len(item["warnings"]) for item in report["testcases"])
    if warning_count:
        log_error(f"Selector validation completed with {warning_count} warning(s). See {SELECTOR_REPORT_PATH}.")
    else:
        log_success(f"Selector validation passed. See {SELECTOR_REPORT_PATH}.")

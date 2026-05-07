import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
REPORT_PATH = Path("reports") / "testdata_validation_report.json"


@dataclass
class ValidationReport:
    valid: int = 0
    invalid: int = 0
    skipped: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)

    def add_error(self, testcase: str, external_id: str, reason: str) -> None:
        self.invalid += 1
        self.errors.append(
            {
                "testcase": testcase,
                "external_id": external_id,
                "reason": reason,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "valid": self.valid,
            "invalid": self.invalid,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def _display_name(raw_testcase: dict[str, Any]) -> str:
    return str(
        raw_testcase.get("name")
        or raw_testcase.get("testcase_name")
        or raw_testcase.get("external_id")
        or "Unknown testcase"
    )


def _external_id(raw_testcase: dict[str, Any]) -> str:
    return str(raw_testcase.get("external_id") or raw_testcase.get("id") or "")


def _path(base: str, index: int | None = None, field_name: str | None = None) -> str:
    value = base
    if index is not None:
        value += f"[{index}]"
    if field_name:
        value += f".{field_name}"
    return value


def _require_object(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path} must be a JSON object.")
        return False
    return True


def _require_list(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, list):
        errors.append(f"{path} must be a list.")
        return False
    return True


def _require_non_empty_string(value: Any, path: str, errors: list[str]) -> None:
    if not str(value or "").strip():
        errors.append(f"{path} is required and cannot be empty.")


def _normalize_action_name(action_name: Any) -> str:
    lowered = str(action_name or "").strip().lower()
    if lowered in SUPPORTED_ACTIONS:
        return lowered
    parts = [part.strip() for part in lowered.replace(",", "|").split("|") if part.strip()]
    for part in parts:
        if part in SUPPORTED_ACTIONS:
            return part
    return lowered


def _validate_actions(testdata: dict[str, Any], errors: list[str]) -> None:
    actions = testdata.get("actions", [])
    if not _require_list(actions, "actions", errors):
        return
    for index, action in enumerate(actions):
        path = _path("actions", index)
        if not _require_object(action, path, errors):
            continue
        selector = str(action.get("selector") or action.get("locator") or "").strip()
        value = str(
            action.get("value")
            or action.get("text")
            or action.get("expected")
            or action.get("expected_from_testdata")
            or ""
        ).strip()
        action_name = _normalize_action_name(action.get("action", ""))
        if not selector and not value:
            errors.append(f"{path}.selector is empty and no usable value fallback is present.")
        if action_name not in SUPPORTED_ACTIONS:
            errors.append(
                f"{path}.action must be one of {sorted(SUPPORTED_ACTIONS)}. Found: {action.get('action', '')}"
            )


def _validate_assertions(testdata: dict[str, Any], errors: list[str]) -> None:
    assertions = testdata.get("assertions", [])
    if not _require_list(assertions, "assertions", errors):
        return
    for index, assertion in enumerate(assertions):
        path = _path("assertions", index)
        if not _require_object(assertion, path, errors):
            continue
        selector = str(assertion.get("selector") or "").strip()
        assertion_type = str(assertion.get("assertion_type", "text")).strip().lower()
        expected = str(
            assertion.get("expected")
            or assertion.get("expected_text")
            or assertion.get("expected_from_testdata")
            or ""
        ).strip()
        _require_non_empty_string(selector, _path("assertions", index, "selector"), errors)
        _require_non_empty_string(expected, _path("assertions", index, "expected"), errors)
        if assertion_type not in SUPPORTED_ASSERTIONS:
            errors.append(
                f"{path}.assertion_type must be one of {sorted(SUPPORTED_ASSERTIONS)}. Found: {assertion_type}"
            )


def validate_testdata_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not _require_object(payload, "custom_field", errors):
        return errors

    testdata = payload.get("testdata") if "testdata" in payload else payload
    if not _require_object(testdata, "testdata", errors):
        return errors

    _require_non_empty_string(testdata.get("expected"), "expected", errors)

    selectors = testdata.get("selectors", {})
    if selectors is not None and not isinstance(selectors, dict):
        errors.append("selectors must be a JSON object when provided.")

    _validate_actions(testdata, errors)
    _validate_assertions(testdata, errors)
    return errors


def parse_custom_field_json(raw_value: Any) -> tuple[Any | None, str | None]:
    try:
        return json.loads(str(raw_value)), None
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON at character {exc.pos}: {exc.msg}"


def validate_raw_testlink_case(
    raw_testcase: dict[str, Any],
    custom_field_value: Any,
    report: ValidationReport,
) -> bool:
    testcase_name = _display_name(raw_testcase)
    external_id = _external_id(raw_testcase)
    if not custom_field_value:
        report.skipped += 1
        return False

    payload, parse_error = parse_custom_field_json(custom_field_value)
    if parse_error:
        report.add_error(testcase_name, external_id, parse_error)
        return False

    errors = validate_testdata_payload(payload)
    if errors:
        report.add_error(testcase_name, external_id, "; ".join(errors))
        return False

    report.valid += 1
    return True


def save_validation_report(report: ValidationReport, path: str | Path = REPORT_PATH) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report_path


def validate_file(path: str | Path) -> int:
    payload, parse_error = parse_custom_field_json(Path(path).read_text(encoding="utf-8"))
    if parse_error:
        print(f"[ERROR] {parse_error}")
        return 1
    errors = validate_testdata_payload(payload)
    if errors:
        for reason in errors:
            print(f"[ERROR] {reason}")
        return 1
    print("[SUCCESS] Test data JSON is valid.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate automation test data JSON.")
    parser.add_argument("--file", help="Path to a JSON file containing TestLink custom field data.")
    args = parser.parse_args()

    if args.file:
        return validate_file(args.file)

    parser.error("Provide --file for standalone validation.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

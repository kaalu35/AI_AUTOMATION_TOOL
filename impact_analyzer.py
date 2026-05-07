import json
from pathlib import Path
from typing import Any

import config
from ai_generator import (
    _build_generation_prompt,
    _generate_with_configured_provider,
    validate_testcase_json,
)


IMPACT_REPORT_PATH = Path("reports") / "requirement_impact_analysis.json"
IMPACT_GENERATED_PATH = Path("generated_data") / "impacted_testcases.json"


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def _testcase_summary(testcase: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": testcase.get("name", ""),
        "summary": testcase.get("summary", ""),
        "steps": testcase.get("steps", []),
        "expected": testcase.get("testdata", {}).get("expected", ""),
    }


def _normalize_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _build_impact_prompt(
    previous_requirement: str,
    previous_design: str,
    current_requirement: str,
    current_design: str,
    existing_testcases: list[dict[str, Any]],
) -> str:
    testcase_summaries = [_testcase_summary(testcase) for testcase in existing_testcases]
    return f"""
You are a senior QA test architect.

Compare the previous requirement/design with the current requirement/design.
Classify the existing testcases by impact.

Return ONLY strict JSON in this structure:
{{
  "impact": [
    {{
      "testcase_name": "",
      "action": "keep | update | obsolete",
      "reason": ""
    }}
  ],
  "new_testcases": [
    {{
      "name": "",
      "reason": ""
    }}
  ]
}}

Rules:
- action=keep means the existing testcase still fully matches the current requirement/design.
- action=update means the existing testcase is still relevant but its steps/test data/expected result should change.
- action=obsolete means the existing testcase no longer applies to the current requirement/design.
- new_testcases must include scenarios required by the current requirement/design that are not covered by existing testcases.
- Do not invent unsupported features.
- Use exact existing testcase names in impact.testcase_name.
- Return parseable JSON only.

Previous Requirement:
{previous_requirement}

Previous Design:
{previous_design}

Current Requirement:
{current_requirement}

Current Design:
{current_design}

Existing Testcases:
{json.dumps(testcase_summaries, indent=2)}
"""


def _validate_impact_plan(data: Any, existing_testcases: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Impact analysis response must be a JSON object.")
    impact = data.get("impact")
    new_testcases = data.get("new_testcases", [])
    if not isinstance(impact, list):
        raise ValueError("Impact analysis JSON must contain an impact list.")
    if not isinstance(new_testcases, list):
        raise ValueError("Impact analysis new_testcases must be a list.")

    existing_names = {_normalize_name(testcase.get("name", "")) for testcase in existing_testcases}
    normalized_impact = []
    for item in impact:
        if not isinstance(item, dict):
            continue
        testcase_name = str(item.get("testcase_name", "")).strip()
        action = str(item.get("action", "")).strip().lower()
        reason = str(item.get("reason", "")).strip()
        if action not in {"keep", "update", "obsolete"}:
            continue
        if _normalize_name(testcase_name) not in existing_names:
            continue
        normalized_impact.append(
            {
                "testcase_name": testcase_name,
                "action": action,
                "reason": reason,
            }
        )

    covered = {_normalize_name(item["testcase_name"]) for item in normalized_impact}
    for testcase in existing_testcases:
        name = str(testcase.get("name", "")).strip()
        if name and _normalize_name(name) not in covered:
            normalized_impact.append(
                {
                    "testcase_name": name,
                    "action": "update",
                    "reason": "Not classified by impact analysis, so updating conservatively.",
                }
            )

    normalized_new = [
        {
            "name": str(item.get("name", "")).strip(),
            "reason": str(item.get("reason", "")).strip(),
        }
        for item in new_testcases
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    return {"impact": normalized_impact, "new_testcases": normalized_new}


def _build_impacted_generation_prompt(
    current_requirement: str,
    current_design: str,
    impact_plan: dict[str, Any],
) -> str:
    update_names = [
        item["testcase_name"]
        for item in impact_plan.get("impact", [])
        if item.get("action") == "update"
    ]
    new_names = [item["name"] for item in impact_plan.get("new_testcases", [])]
    names_to_generate = update_names + new_names
    base_prompt = _build_generation_prompt(current_requirement, current_design)
    return f"""
{base_prompt}

Additional selective regeneration instruction:
- Generate ONLY the following impacted or new testcase names.
- Do not include unchanged keep testcases.
- Do not include obsolete testcases.
- If a listed name needs clearer wording, keep the same business meaning.

Testcases to generate:
{json.dumps(names_to_generate, indent=2)}
"""


def _merge_testcases(
    existing_testcases: list[dict[str, Any]],
    generated_impacted: list[dict[str, Any]],
    impact_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    existing_by_name = {
        _normalize_name(testcase.get("name", "")): testcase
        for testcase in existing_testcases
        if testcase.get("name")
    }
    generated_by_name = {
        _normalize_name(testcase.get("name", "")): testcase
        for testcase in generated_impacted
        if testcase.get("name")
    }

    merged: list[dict[str, Any]] = []
    for item in impact_plan.get("impact", []):
        name_key = _normalize_name(item.get("testcase_name", ""))
        action = item.get("action")
        if action == "obsolete":
            continue
        if action == "keep" and name_key in existing_by_name:
            merged.append(existing_by_name[name_key])
        elif action == "update" and name_key in generated_by_name:
            merged.append(generated_by_name[name_key])
        elif action == "update" and name_key in existing_by_name:
            log_error(
                f"Impact analysis requested update but no regenerated testcase matched: "
                f"{item.get('testcase_name')}. Keeping existing testcase."
            )
            merged.append(existing_by_name[name_key])

    used_keys = {_normalize_name(testcase.get("name", "")) for testcase in merged}
    for testcase in generated_impacted:
        key = _normalize_name(testcase.get("name", ""))
        if key and key not in used_keys:
            merged.append(testcase)
            used_keys.add(key)
    return merged


def run_requirement_impact_analysis(
    previous_requirement: str,
    previous_design: str,
    current_requirement: str,
    current_design: str,
    existing_testcases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not config.ENABLE_REQUIREMENT_IMPACT_ANALYSIS:
        raise RuntimeError("Requirement impact analysis is disabled.")
    if not existing_testcases:
        raise RuntimeError("No existing TestLink testcases are available for impact analysis.")

    log_info("Running requirement impact analysis.")
    impact_prompt = _build_impact_prompt(
        previous_requirement=previous_requirement,
        previous_design=previous_design,
        current_requirement=current_requirement,
        current_design=current_design,
        existing_testcases=existing_testcases,
    )
    raw_plan = _generate_with_configured_provider(impact_prompt)
    impact_plan = _validate_impact_plan(raw_plan, existing_testcases)

    update_count = sum(1 for item in impact_plan["impact"] if item["action"] == "update")
    create_count = len(impact_plan["new_testcases"])
    if update_count or create_count:
        generation_prompt = _build_impacted_generation_prompt(
            current_requirement=current_requirement,
            current_design=current_design,
            impact_plan=impact_plan,
        )
        raw_generated = _generate_with_configured_provider(generation_prompt)
        validated = validate_testcase_json(raw_generated)
        generated_impacted = validated["testcases"]
    else:
        generated_impacted = []

    merged_testcases = _merge_testcases(existing_testcases, generated_impacted, impact_plan)
    if not merged_testcases:
        raise RuntimeError("Impact analysis produced no current testcases.")

    report = {
        "enabled": True,
        "impact": impact_plan["impact"],
        "new_testcases": impact_plan["new_testcases"],
        "kept": sum(1 for item in impact_plan["impact"] if item["action"] == "keep"),
        "updated": update_count,
        "created": create_count,
        "obsolete": sum(1 for item in impact_plan["impact"] if item["action"] == "obsolete"),
        "final_current_testcase_count": len(merged_testcases),
    }
    IMPACT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    IMPACT_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    IMPACT_GENERATED_PATH.parent.mkdir(parents=True, exist_ok=True)
    IMPACT_GENERATED_PATH.write_text(
        json.dumps({"testcases": merged_testcases}, indent=2),
        encoding="utf-8",
    )
    log_success(
        "Requirement impact analysis completed. "
        f"Kept {report['kept']}, updated {report['updated']}, "
        f"created {report['created']}, obsolete {report['obsolete']}."
    )
    return merged_testcases, report

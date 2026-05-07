import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import config


OUTPUT_PATH = Path("generated_data") / "testcases.json"
CHUNK_REPORT_PATH = Path("reports") / "large_document_chunks.json"
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def _fallback_testcases() -> dict[str, Any]:
    return {
        "testcases": [
            {
                "name": "Add two whole numbers",
                "summary": "Verify that the calculator adds two whole numbers.",
                "steps": [
                    {
                        "actions": "Enter 8, select +, enter 2, then press equals.",
                        "expected_results": "The calculator displays 10.",
                    }
                ],
                "testdata": {
                    "input1": "8",
                    "input2": "2",
                    "operator": "+",
                    "expected": "10",
                    "target_url": config.TARGET_CALCULATOR_URL,
                },
            },
            {
                "name": "Subtract decimal values",
                "summary": "Verify that the calculator subtracts decimal numbers.",
                "steps": [
                    {
                        "actions": "Enter 7.5, select -, enter 2.25, then press equals.",
                        "expected_results": "The calculator displays 5.25.",
                    }
                ],
                "testdata": {
                    "input1": "7.5",
                    "input2": "2.25",
                    "operator": "-",
                    "expected": "5.25",
                    "target_url": config.TARGET_CALCULATOR_URL,
                },
            },
            {
                "name": "Multiply two values",
                "summary": "Verify that the calculator multiplies two values.",
                "steps": [
                    {
                        "actions": "Enter 6, select *, enter 4, then press equals.",
                        "expected_results": "The calculator displays 24.",
                    }
                ],
                "testdata": {
                    "input1": "6",
                    "input2": "4",
                    "operator": "*",
                    "expected": "24",
                    "target_url": config.TARGET_CALCULATOR_URL,
                },
            },
            {
                "name": "Divide by zero",
                "summary": "Verify that division by zero is handled gracefully.",
                "steps": [
                    {
                        "actions": "Enter 9, select /, enter 0, then press equals.",
                        "expected_results": "The calculator displays an error or infinity message.",
                    }
                ],
                "testdata": {
                    "input1": "9",
                    "input2": "0",
                    "operator": "/",
                    "expected": "Infinity",
                    "target_url": config.TARGET_CALCULATOR_URL,
                },
            },
        ]
    }


def _extract_json(raw_text: str) -> dict[str, Any]:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def validate_testcase_json(data: Any, default_target_url: str = "") -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("OpenAI response must be a JSON object.")

    testcases = data.get("testcases")
    if not isinstance(testcases, list) or not testcases:
        raise ValueError("JSON must contain a non-empty testcases list.")

    valid_testcases: list[dict[str, Any]] = []
    for index, testcase in enumerate(testcases, start=1):
        try:
            if not isinstance(testcase, dict):
                raise ValueError(f"Testcase {index} must be an object.")
            for key in ("name", "summary", "steps", "testdata"):
                if key not in testcase:
                    raise ValueError(f"Testcase {index} is missing '{key}'.")
            if not str(testcase["name"]).strip():
                raise ValueError(f"Testcase {index} has an empty name.")
            if not isinstance(testcase["steps"], list) or not testcase["steps"]:
                raise ValueError(f"Testcase {index} must include at least one step.")
            for step_number, step in enumerate(testcase["steps"], start=1):
                if not isinstance(step, dict):
                    raise ValueError(f"Testcase {index}, step {step_number} must be an object.")
                if "actions" not in step or "expected_results" not in step:
                    raise ValueError(
                        f"Testcase {index}, step {step_number} needs actions and expected_results."
                    )
            testdata = testcase["testdata"]
            if not isinstance(testdata, dict):
                raise ValueError(f"Testcase {index} testdata must be an object.")
            if not testdata.get("actions") and isinstance(testcase.get("actions"), list):
                testdata["actions"] = testcase.get("actions", [])
            if not testdata.get("assertions") and isinstance(testcase.get("assertions"), list):
                testdata["assertions"] = testcase.get("assertions", [])
            testcase["testdata"] = _normalize_testdata(
                testdata,
                testcase.get("steps", []),
                default_target_url=default_target_url,
            )
            valid_testcases.append(testcase)
        except ValueError as exc:
            log_error(f"Skipping invalid generated testcase #{index}: {exc}")
            continue

    if len(valid_testcases) < 3:
        raise ValueError(
            f"Only {len(valid_testcases)} executable testcase(s) were valid. "
            "At least 3 are required before uploading or executing."
        )
    data["testcases"] = valid_testcases
    return data


def _dedupe_testcases(testcases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen = set()
    for testcase in testcases:
        name = " ".join(str(testcase.get("name", "")).strip().lower().split())
        summary = " ".join(str(testcase.get("summary", "")).strip().lower().split())
        key = name or summary
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(testcase)
    return deduped


def _split_large_text(text: str, chunk_size: int) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for paragraph in paragraphs:
        paragraph_size = len(paragraph)
        if paragraph_size > chunk_size:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_size = 0
            for start in range(0, paragraph_size, chunk_size):
                chunks.append(paragraph[start : start + chunk_size])
            continue

        if current and current_size + paragraph_size + 2 > chunk_size:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_size = paragraph_size
        else:
            current.append(paragraph)
            current_size += paragraph_size + 2

    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text]


def _compress_requirement_for_generation(requirement: str, max_chars: int = 7000) -> str:
    lines = [line.strip() for line in requirement.splitlines() if line.strip()]
    kept: list[str] = []
    seen = set()
    for line in lines:
        normalized = re.sub(r"\bsection\s+\d+\b", "section #", line.lower())
        normalized = re.sub(r"\d+", "#", normalized)
        if normalized in seen and not re.match(r"(?i)^(module|feature|requirement|flow|section)\b", line):
            continue
        seen.add(normalized)
        kept.append(line)
        if sum(len(item) + 1 for item in kept) >= max_chars:
            break
    compressed = "\n".join(kept)
    return compressed or requirement[:max_chars]


def _build_chunk_prompt(requirement_chunk: str, design: str, chunk_number: int, total_chunks: int) -> str:
    base_prompt = _build_generation_prompt(requirement_chunk, design)
    return f"""
{base_prompt}

Large document instruction:
- This is requirement chunk {chunk_number} of {total_chunks}.
- Generate only the strongest 3 to 6 automation-ready testcases for this chunk.
- Focus only on behavior described in this chunk.
- Add the module/feature name at the start of each testcase name when it is clear.
- Avoid duplicating generic login/precondition cases unless this chunk is specifically about login.
"""


def _generate_chunked_testcases(requirement: str, design: str) -> dict[str, Any]:
    compressed_requirement = _compress_requirement_for_generation(requirement)
    if len(compressed_requirement) + len(design) < len(requirement) + len(design):
        log_info(
            "Compressed repetitive large requirement from "
            f"{len(requirement)} to {len(compressed_requirement)} chars before generation."
        )

    if len(compressed_requirement) + len(design) <= config.LARGE_DOCUMENT_CHARS:
        log_info("Compressed requirement is small enough for a single generation request.")
        return _generate_with_configured_provider(_build_generation_prompt(compressed_requirement, design))

    chunks = _split_large_text(compressed_requirement, config.DOCUMENT_CHUNK_CHARS)
    all_testcases: list[dict[str, Any]] = []
    chunk_report: list[dict[str, Any]] = []

    log_info(
        f"Large requirement detected ({len(requirement) + len(design)} chars). "
        f"Generating testcases in {len(chunks)} chunk(s)."
    )

    for index, chunk in enumerate(chunks, start=1):
        log_info(f"Generating testcases for requirement chunk {index}/{len(chunks)}.")
        prompt = _build_chunk_prompt(chunk, design, index, len(chunks))
        raw = _generate_with_configured_provider(prompt)
        try:
            validated = validate_testcase_json(raw)
            generated = validated["testcases"]
            all_testcases.extend(generated)
            chunk_report.append(
                {
                    "chunk": index,
                    "status": "success",
                    "chars": len(chunk),
                    "testcases": len(generated),
                }
            )
            log_success(f"Chunk {index}/{len(chunks)} generated {len(generated)} testcase(s).")
        except Exception as exc:
            chunk_report.append(
                {
                    "chunk": index,
                    "status": "failed",
                    "chars": len(chunk),
                    "error": str(exc),
                }
            )
            log_error(f"Chunk {index}/{len(chunks)} failed validation: {exc}")

    deduped = _dedupe_testcases(all_testcases)
    if config.MAX_CHUNKED_TESTCASES > 0:
        deduped = deduped[: config.MAX_CHUNKED_TESTCASES]

    report = {
        "requirement_chars": len(requirement),
        "compressed_requirement_chars": len(compressed_requirement),
        "design_chars": len(design),
        "chunks": len(chunks),
        "generated_before_dedupe": len(all_testcases),
        "generated_after_dedupe": len(deduped),
        "max_chunked_testcases": config.MAX_CHUNKED_TESTCASES,
        "chunk_results": chunk_report,
    }
    CHUNK_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHUNK_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not deduped:
        raise ValueError("Large-document chunking did not produce any valid testcases.")
    return {"testcases": deduped}


def _derive_expected_value(normalized: dict[str, Any], fallback_steps: list[dict[str, Any]] | None) -> str:
    if normalized.get("expected"):
        return str(normalized.get("expected", "")).strip()

    if normalized["assertions"]:
        first_assertion = normalized["assertions"][0]
        if isinstance(first_assertion, dict):
            derived = str(
                first_assertion.get("expected")
                or first_assertion.get("expected_text")
                or first_assertion.get("expected_from_testdata")
                or ""
            ).strip()
            if derived:
                return derived

    selectors = normalized.get("selectors", {})
    if isinstance(selectors, dict):
        derived = str(selectors.get("result", "")).strip()
        if derived:
            return derived

    for action in normalized["actions"]:
        if not isinstance(action, dict):
            continue
        action_name = str(action.get("action", "")).strip().lower()
        if action_name in {"assert_text", "assert_value", "assert_url"}:
            derived = str(
                action.get("value")
                or action.get("text")
                or action.get("expected")
                or action.get("expected_from_testdata")
                or ""
            ).strip()
            if derived:
                return derived

    for step in fallback_steps or []:
        if isinstance(step, dict):
            derived = str(step.get("expected_results", "")).strip()
            if derived:
                return derived

    return ""


def _normalize_testdata(
    testdata: dict[str, Any],
    fallback_steps: list[dict[str, Any]] | None = None,
    default_target_url: str = "",
) -> dict[str, Any]:
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
        normalized["expected"] = _derive_expected_value(normalized, fallback_steps)
    if not normalized["expected"]:
        raise ValueError("Each testcase must include an expected result in testdata.")
    if not normalized["target_url"]:
        searchable_values = []
        for step in fallback_steps or []:
            if isinstance(step, dict):
                searchable_values.extend([str(step.get("actions", "")), str(step.get("expected_results", ""))])
        for value in searchable_values:
            match = URL_PATTERN.search(value)
            if match:
                normalized["target_url"] = match.group(0).rstrip(".,)")
                break
    if not normalized["target_url"] and default_target_url:
        normalized["target_url"] = default_target_url
    if not normalized["target_url"]:
        raise ValueError("Each executable UI testcase must include target_url from the requirement/design.")
    if not normalized["actions"]:
        raise ValueError("Each executable UI testcase must include Playwright-ready actions.")
    if not normalized["assertions"] and not normalized["selectors"].get("result"):
        raise ValueError("Each executable UI testcase must include assertions or selectors.result.")
    return normalized


def _build_generation_prompt(requirement: str, design: str) -> str:
    merged_context = f"Requirement:\n{requirement}\n\nDesign:\n{design}"
    return f"""
You are a senior QA automation architect and Playwright automation engineer.

Analyze the provided requirement and design documents and generate automation-ready
test cases for the described web application. The output will be used by a
pipeline that uploads test cases and dynamic test data into TestLink, then
generates and executes Playwright pytest scripts from TestLink data.

Return ONLY strict JSON. Do not include markdown, comments, explanations, or extra text.

Required JSON structure:
{{
  "testcases": [
    {{
      "name": "",
      "summary": "",
      "steps": [
        {{
          "actions": "",
          "expected_results": ""
        }}
      ],
      "testdata": {{
        "input1": "",
        "input2": "",
        "operator": "",
        "expected": "",
        "target_url": "",
        "selectors": {{
          "field1": "",
          "field2": "",
          "operator": "",
          "submit": "",
          "result": "",
          "clear": ""
        }},
        "actions": [
          {{
            "selector": "",
            "action": "fill | click | select | check | assert_text | assert_visible",
            "value": ""
          }}
        ],
        "assertions": [
          {{
            "selector": "",
            "assertion_type": "text | visible | url | value",
            "expected": ""
          }}
        ]
      }}
    }}
  ]
}}

Rules:
- Generate exactly 5 practical, independent testcases.
- Generate strictly from the requirement and design. Do not invent unsupported features.
- Cover positive, negative, boundary, validation, error-handling, and business-critical scenarios.
- Every testcase must include meaningful dynamic testdata and deterministic expected results.
- Every testcase must include Playwright-ready selectors, actions, and assertions for the application in the requirement/design.
- Prefer selectors in this order: data-testid, id, name, aria-label, placeholder, label text, role/text.
- Avoid brittle XPath unless no stable selector can be inferred.
- target_url is mandatory for every web UI testcase when the requirement/design gives an application URL.
- Do not use calculator, SauceDemo, or any sample/demo site unless that exact application appears in the requirement/design.
- For non-calculator requirements, map the primary input values into input1/input2, the main event into operator,
  and the expected UI outcome into expected, while adding executable actions/assertions for the required application.
- Action value may be a literal or a reference like input1, input2, operator, or expected.
- JSON must be parseable with Python json.loads and must not contain trailing commas.

Context:
{merged_context}
"""


def _generate_with_openai(prompt: str) -> dict[str, Any]:
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You generate only valid JSON for test automation.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw_content = response.choices[0].message.content or ""
    return _extract_json(raw_content)


def _generate_with_gemini(prompt: str) -> dict[str, Any]:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing.")

    import google.generativeai as genai

    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel(config.GEMINI_MODEL)
    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )
    return _extract_json(response.text or "")


def _generate_with_deepseek(prompt: str) -> dict[str, Any]:
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is missing.")

    from openai import OpenAI

    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
    )
    response = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You generate only valid JSON for test automation.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw_content = response.choices[0].message.content or ""
    return _extract_json(raw_content)


def _generate_with_ollama(prompt: str) -> dict[str, Any]:
    request_body = json.dumps(
        {
            "model": config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.2,
                "num_predict": config.OLLAMA_NUM_PREDICT,
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.OLLAMA_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Unable to connect to Ollama. Install Ollama, start it, and run "
            f"'ollama pull {config.OLLAMA_MODEL}'."
        ) from exc
    return _extract_json(str(payload.get("response", "")))


def _call_provider(provider: str, prompt: str) -> dict[str, Any]:
    if provider == "ollama":
        log_info(f"Generating testcases using local Ollama model: {config.OLLAMA_MODEL}")
        return _generate_with_ollama(prompt)
    if provider == "gemini":
        log_info(f"Generating testcases using Gemini model: {config.GEMINI_MODEL}")
        return _generate_with_gemini(prompt)
    if provider == "deepseek":
        log_info(f"Generating testcases using DeepSeek model: {config.DEEPSEEK_MODEL}")
        return _generate_with_deepseek(prompt)
    if provider == "openai":
        log_info(f"Generating testcases using OpenAI model: {config.OPENAI_MODEL}")
        return _generate_with_openai(prompt)
    raise ValueError(f"Unsupported AI provider: {provider}")


def _trim_for_retry(value: Any, max_chars: int = 6000) -> str:
    try:
        text = json.dumps(value, indent=2)
    except TypeError:
        text = str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...truncated..."


def _build_correction_prompt(original_prompt: str, invalid_response: Any, validation_error: Exception) -> str:
    return f"""
{original_prompt}

Correction retry:
The previous AI output was rejected by strict validation and was NOT uploaded to TestLink.
Fix the output now. Return ONLY corrected strict JSON using the exact required schema.

Validation error:
{validation_error}

Invalid output:
{_trim_for_retry(invalid_response)}

Mandatory correction rules:
- Keep the testcases strictly based on the same requirement/design context above.
- Include at least 3 and ideally exactly 5 executable testcases.
- Every testcase must have name, summary, steps, and testdata.
- Every step must have actions and expected_results.
- Every testdata object must include target_url, actions, assertions, and expected.
- Every action must include selector, action, and value.
- Every assertion must include selector, assertion_type, and expected.
- Do not use calculator, SauceDemo, or unrelated demo data unless explicitly present in the requirement/design.
- Return parseable JSON only. No markdown, no comments, no explanation.
"""


def _generate_validated_with_provider(
    provider: str,
    prompt: str,
    default_target_url: str = "",
) -> dict[str, Any]:
    current_prompt = prompt
    attempts = max(0, config.AI_CORRECTION_RETRIES) + 1
    last_error: Exception | None = None
    last_candidate: Any = None

    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1:
                log_info(
                    f"Retrying {provider} generation with correction prompt "
                    f"({attempt - 1}/{config.AI_CORRECTION_RETRIES})."
                )
            last_candidate = _call_provider(provider, current_prompt)
            return validate_testcase_json(last_candidate, default_target_url=default_target_url)
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            log_error(f"{provider} output failed validation: {exc}")
            current_prompt = _build_correction_prompt(prompt, last_candidate, exc)

    raise RuntimeError(
        f"{provider} did not produce valid executable testcases after {attempts} attempt(s): {last_error}"
    )


def _generate_with_configured_provider(prompt: str, default_target_url: str = "") -> dict[str, Any]:
    if config.AI_PROVIDER == "auto":
        errors = []
        providers = ["ollama"]
        if config.DEEPSEEK_API_KEY:
            providers.append("deepseek")
        if config.GEMINI_API_KEY:
            providers.append("gemini")
        if config.OPENAI_API_KEY:
            providers.append("openai")

        for provider in providers:
            try:
                log_info(f"Auto provider: trying {provider}.")
                return _generate_validated_with_provider(
                    provider,
                    prompt,
                    default_target_url=default_target_url,
                )
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                log_error(f"Auto provider {provider} failed: {exc}")
        raise RuntimeError("All configured AI providers failed. " + " | ".join(errors))

    if config.AI_PROVIDER == "gemini":
        return _generate_validated_with_provider("gemini", prompt, default_target_url=default_target_url)
    if config.AI_PROVIDER == "ollama":
        return _generate_validated_with_provider("ollama", prompt, default_target_url=default_target_url)
    if config.AI_PROVIDER == "deepseek":
        return _generate_validated_with_provider("deepseek", prompt, default_target_url=default_target_url)
    if config.AI_PROVIDER in {"openai", "gpt41mini"}:
        return _generate_validated_with_provider("openai", prompt, default_target_url=default_target_url)
    raise ValueError("Unsupported AI_PROVIDER. Use 'auto', 'ollama', 'gemini', 'deepseek', 'openai', or 'gpt41mini'.")


def generate_testcases(requirement: str, design: str) -> dict[str, Any]:
    prompt = _build_generation_prompt(requirement, design)
    default_target_url = ""
    target_match = URL_PATTERN.search(f"{requirement}\n{design}")
    if target_match:
        default_target_url = target_match.group(0).rstrip(".,)")
    use_chunking = (
        config.ENABLE_LARGE_DOCUMENT_CHUNKING
        and len(requirement) + len(design) >= config.LARGE_DOCUMENT_CHARS
    )

    if use_chunking:
        try:
            testcases = _generate_chunked_testcases(requirement, design)
        except Exception as exc:
            if not config.ALLOW_DEMO_FALLBACK:
                raise RuntimeError(
                    "Large-document chunked generation failed, so the pipeline stopped before "
                    f"uploading/executing stale cases. Details: {exc}"
                ) from exc
            log_error(
                f"Large-document chunked generation failed: {exc}. "
                "ALLOW_DEMO_FALLBACK=true, using demo calculator testcases."
            )
            testcases = _fallback_testcases()
    elif config.AI_PROVIDER in {"openai", "gpt41mini"} and not config.OPENAI_API_KEY:
        if not config.ALLOW_DEMO_FALLBACK:
            raise RuntimeError(
                "OPENAI_API_KEY is missing. Cannot generate requirement-specific testcases. "
                "Set OPENAI_API_KEY or set ALLOW_DEMO_FALLBACK=true only for demo calculator runs."
            )
        log_error("OPENAI_API_KEY is missing. ALLOW_DEMO_FALLBACK=true, using demo calculator testcases.")
        testcases = _fallback_testcases()
    elif config.AI_PROVIDER == "gemini" and not config.GEMINI_API_KEY:
        if not config.ALLOW_DEMO_FALLBACK:
            raise RuntimeError(
                "GEMINI_API_KEY is missing. Cannot generate requirement-specific testcases. "
                "Set GEMINI_API_KEY or set ALLOW_DEMO_FALLBACK=true only for demo calculator runs."
            )
        log_error("GEMINI_API_KEY is missing. ALLOW_DEMO_FALLBACK=true, using demo calculator testcases.")
        testcases = _fallback_testcases()
    elif config.AI_PROVIDER == "deepseek" and not config.DEEPSEEK_API_KEY:
        if not config.ALLOW_DEMO_FALLBACK:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is missing. Cannot generate requirement-specific testcases. "
                "Set DEEPSEEK_API_KEY or set ALLOW_DEMO_FALLBACK=true only for demo calculator runs."
            )
        log_error("DEEPSEEK_API_KEY is missing. ALLOW_DEMO_FALLBACK=true, using demo calculator testcases.")
        testcases = _fallback_testcases()
    elif config.AI_PROVIDER == "ollama":
        try:
            testcases = _generate_with_configured_provider(prompt, default_target_url=default_target_url)
        except Exception as exc:
            if not config.ALLOW_DEMO_FALLBACK:
                raise RuntimeError(
                    "ollama generation failed, so the pipeline stopped before uploading/executing "
                    f"stale demo calculator cases. Fix ollama setup and rerun. Details: {exc}"
                ) from exc
            log_error(
                f"ollama generation failed: {exc}. "
                "ALLOW_DEMO_FALLBACK=true, using demo calculator testcases."
            )
            testcases = _fallback_testcases()
    else:
        try:
            testcases = _generate_with_configured_provider(prompt, default_target_url=default_target_url)
        except Exception as exc:
            if not config.ALLOW_DEMO_FALLBACK:
                raise RuntimeError(
                    f"{config.AI_PROVIDER} generation failed, so the pipeline stopped before uploading/executing "
                    f"stale demo calculator cases. Fix AI provider setup and rerun. Details: {exc}"
                ) from exc
            log_error(
                f"{config.AI_PROVIDER} generation failed: {exc}. "
                "ALLOW_DEMO_FALLBACK=true, using demo calculator testcases."
            )
            testcases = _fallback_testcases()

    validated = validate_testcase_json(testcases, default_target_url=default_target_url)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(validated, indent=2), encoding="utf-8")
    log_success(f"Validated testcases saved to {OUTPUT_PATH}.")
    return validated

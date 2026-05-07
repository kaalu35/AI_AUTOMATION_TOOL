import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

import config
from setup_installer import DEPENDENCIES


ROOT_DIR = Path(__file__).resolve().parent


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def _check(name: str, fn) -> bool:
    try:
        fn()
        log_success(name)
        return True
    except Exception as exc:
        log_error(f"{name}: {exc}")
        return False


def _require(value: Any, label: str) -> None:
    if value in ("", None, 0):
        raise ValueError(f"{label} is missing.")


def _check_python() -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError(f"Python 3.11+ required. Current: {sys.version.split()[0]}")


def _check_folders() -> None:
    for folder in ("generated_data", "generated_tests", "reports"):
        path = ROOT_DIR / folder
        path.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            raise RuntimeError(f"Required folder could not be created: {folder}")


def _check_dependencies() -> None:
    missing = [
        dependency.package_name
        for dependency in DEPENDENCIES
        if importlib.util.find_spec(dependency.import_name) is None
    ]
    if missing:
        raise RuntimeError("Missing Python package(s): " + ", ".join(missing))


def _check_config() -> None:
    required = {
        "GITHUB_TOKEN": config.GITHUB_TOKEN,
        "REPO_NAME": config.REPO_NAME,
        "TESTLINK_URL": config.TESTLINK_URL,
        "TESTLINK_DEV_KEY": config.DEV_KEY,
        "TESTLINK_PROJECT_ID": config.PROJECT_ID,
        "TESTLINK_SUITE_ID": config.SUITE_ID,
    }
    if config.AI_PROVIDER in {"auto", "ollama"}:
        required["OLLAMA_BASE_URL"] = config.OLLAMA_BASE_URL
        required["OLLAMA_MODEL"] = config.OLLAMA_MODEL
    if config.ENABLE_MANTISBT_BUG_CREATION:
        required["MANTISBT_URL"] = config.MANTISBT_URL
        required["MANTISBT_PROJECT_NAME or MANTISBT_PROJECT_ID"] = (
            config.MANTISBT_PROJECT_NAME or config.MANTISBT_PROJECT_ID
        )
        required["MANTISBT_API_TOKEN or username/password"] = (
            config.MANTISBT_API_TOKEN
            or (config.MANTISBT_USERNAME and config.MANTISBT_PASSWORD)
        )

    missing = [label for label, value in required.items() if value in ("", None, 0)]
    if missing:
        raise RuntimeError("Missing config value(s): " + ", ".join(missing))


def _repo_full_name() -> str:
    if "/" in config.REPO_NAME:
        return config.REPO_NAME
    _require(config.GITHUB_USERNAME, "GITHUB_USERNAME")
    return f"{config.GITHUB_USERNAME}/{config.REPO_NAME}"


def _check_github() -> None:
    from github import Github

    repo = Github(config.GITHUB_TOKEN).get_repo(_repo_full_name())
    repo.get_contents("requirement.txt", ref=config.GITHUB_BRANCH)
    repo.get_contents("design.txt", ref=config.GITHUB_BRANCH)


def _request_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> Any:
    http_request = request.Request(url, headers=headers or {}, method="GET")
    with request.urlopen(http_request, timeout=timeout) as response:
        text = response.read().decode("utf-8").strip()
    return json.loads(text) if text else {}


def _check_ollama() -> None:
    if config.AI_PROVIDER not in {"auto", "ollama"}:
        log_info(f"Ollama check skipped because AI_PROVIDER={config.AI_PROVIDER}.")
        return
    tags_url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    response = _request_json(tags_url, timeout=10)
    models = response.get("models", []) if isinstance(response, dict) else []
    names = {str(model.get("name", "")) for model in models if isinstance(model, dict)}
    if config.OLLAMA_MODEL not in names:
        raise RuntimeError(f"Ollama model not found: {config.OLLAMA_MODEL}")


def _check_cloud_llm_config() -> None:
    provider = config.AI_PROVIDER
    if provider in {"openai", "gpt41mini"}:
        _require(config.OPENAI_API_KEY, "OPENAI_API_KEY")
    elif provider == "gemini":
        _require(config.GEMINI_API_KEY, "GEMINI_API_KEY")
    elif provider == "deepseek":
        _require(config.DEEPSEEK_API_KEY, "DEEPSEEK_API_KEY")


def _check_testlink() -> None:
    import testlink

    client = testlink.TestlinkAPIClient(config.TESTLINK_URL, config.DEV_KEY)
    projects = client.getProjects()
    if not any(str(project.get("id")) == str(config.PROJECT_ID) for project in projects if isinstance(project, dict)):
        raise RuntimeError(f"TestLink project id not found: {config.PROJECT_ID}")

    client.getTestCasesForTestSuite(
        testsuiteid=config.SUITE_ID,
        deep=False,
        details="simple",
    )


def _mantis_headers() -> dict[str, str]:
    if config.MANTISBT_API_TOKEN:
        auth = config.MANTISBT_API_TOKEN
    else:
        import base64

        token = base64.b64encode(
            f"{config.MANTISBT_USERNAME}:{config.MANTISBT_PASSWORD}".encode("utf-8")
        ).decode("ascii")
        auth = f"Basic {token}"
    return {"Authorization": auth, "Accept": "application/json"}


def _check_mantisbt() -> None:
    if not config.ENABLE_MANTISBT_BUG_CREATION:
        log_info("MantisBT check skipped because ENABLE_MANTISBT_BUG_CREATION=false.")
        return
    url = f"{config.MANTISBT_URL.rstrip('/')}/users/me"
    response = _request_json(url, headers=_mantis_headers(), timeout=20)
    projects = response.get("projects", []) if isinstance(response, dict) else []
    if config.MANTISBT_PROJECT_ID:
        found = any(str(project.get("id")) == str(config.MANTISBT_PROJECT_ID) for project in projects if isinstance(project, dict))
    else:
        found = any(str(project.get("name")) == config.MANTISBT_PROJECT_NAME for project in projects if isinstance(project, dict))
    if not found:
        raise RuntimeError("Configured MantisBT project is not visible to the API user.")


def _check_playwright() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser.close()


def run_health_check() -> int:
    log_info("Running pipeline health check.")
    checks = [
        ("Python version is supported.", _check_python),
        ("Required folders are ready.", _check_folders),
        ("Python dependencies are installed.", _check_dependencies),
        ("Required configuration values are present.", _check_config),
        ("GitHub repository and requirement/design files are reachable.", _check_github),
        ("Ollama/local LLM is reachable when configured.", _check_ollama),
        ("Cloud LLM config is present when configured.", _check_cloud_llm_config),
        ("TestLink API, project, and suite are reachable.", _check_testlink),
        ("MantisBT API and project are reachable when enabled.", _check_mantisbt),
        ("Playwright Chromium browser launches successfully.", _check_playwright),
    ]

    passed = 0
    for name, fn in checks:
        if _check(name, fn):
            passed += 1

    failed = len(checks) - passed
    if failed:
        log_error(f"Health check failed. Passed {passed}/{len(checks)}, failed {failed}.")
        return 1

    log_success(f"Health check passed. Passed {passed}/{len(checks)} checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_health_check())

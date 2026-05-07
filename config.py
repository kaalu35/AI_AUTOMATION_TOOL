import os
from pathlib import Path




def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env_file()


GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
REPO_NAME = os.getenv("REPO_NAME", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AI_PROVIDER = os.getenv("AI_PROVIDER", "auto").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "600"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "2048"))
AI_CORRECTION_RETRIES = int(os.getenv("AI_CORRECTION_RETRIES", "2") or 2)

TESTLINK_URL = os.getenv(
    "TESTLINK_URL",
    "http://localhost/testlink/lib/api/xmlrpc/v1/xmlrpc.php",
)
DEV_KEY = os.getenv("TESTLINK_DEV_KEY", os.getenv("DEV_KEY", ""))
PROJECT_ID = int(os.getenv("TESTLINK_PROJECT_ID", os.getenv("PROJECT_ID", "0")) or 0)
SUITE_ID = int(os.getenv("TESTLINK_SUITE_ID", os.getenv("SUITE_ID", "0")) or 0)
TESTLINK_AUTHOR_LOGIN = os.getenv("TESTLINK_AUTHOR_LOGIN", "admin")
TESTLINK_TESTPLAN_ID = int(os.getenv("TESTLINK_TESTPLAN_ID", "0") or 0)
TESTLINK_BUILD_NAME = os.getenv("TESTLINK_BUILD_NAME", "Automation Pipeline Build")
UPLOAD_RESULTS_TO_TESTLINK = os.getenv("UPLOAD_RESULTS_TO_TESTLINK", "false").lower() in (
    "1",
    "true",
    "yes",
)
TESTLINK_CUSTOM_FIELD_NAME = os.getenv(
    "TESTLINK_CUSTOM_FIELD_NAME",
    "automation_testdata_json",
)
TESTLINK_CUSTOM_FIELD_LABEL = os.getenv(
    "TESTLINK_CUSTOM_FIELD_LABEL",
    "Automation Test Data JSON",
)
TESTLINK_DB_HOST = os.getenv("TESTLINK_DB_HOST", "localhost")
TESTLINK_DB_NAME = os.getenv("TESTLINK_DB_NAME", "testlink")
TESTLINK_DB_USER = os.getenv("TESTLINK_DB_USER", "testlink")
TESTLINK_DB_PASSWORD = os.getenv("TESTLINK_DB_PASSWORD", "testlink")
MYSQL_EXE = os.getenv("MYSQL_EXE", r"C:\xampp\mysql\bin\mysql.exe")

GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
ALLOW_DEMO_FALLBACK = os.getenv("ALLOW_DEMO_FALLBACK", "false").lower() in (
    "1",
    "true",
    "yes",
)
REVIEW_GENERATED_TESTS = os.getenv("REVIEW_GENERATED_TESTS", "true").lower() in (
    "1",
    "true",
    "yes",
)
REUSE_EXISTING_TESTLINK_CASES = os.getenv("REUSE_EXISTING_TESTLINK_CASES", "true").lower() in (
    "1",
    "true",
    "yes",
)
DEACTIVATE_OBSOLETE_TESTCASES = os.getenv(
    "DEACTIVATE_OBSOLETE_TESTCASES",
    "true",
).lower() in ("1", "true", "yes")
TESTLINK_OBSOLETE_TAG = os.getenv("TESTLINK_OBSOLETE_TAG", "[OBSOLETE]")
ENABLE_REQUIREMENT_IMPACT_ANALYSIS = os.getenv(
    "ENABLE_REQUIREMENT_IMPACT_ANALYSIS",
    "true",
).lower() in ("1", "true", "yes")
ENABLE_LARGE_DOCUMENT_CHUNKING = os.getenv(
    "ENABLE_LARGE_DOCUMENT_CHUNKING",
    "true",
).lower() in ("1", "true", "yes")
LARGE_DOCUMENT_CHARS = int(os.getenv("LARGE_DOCUMENT_CHARS", "12000") or 12000)
DOCUMENT_CHUNK_CHARS = int(os.getenv("DOCUMENT_CHUNK_CHARS", "3500") or 3500)
MAX_CHUNKED_TESTCASES = int(os.getenv("MAX_CHUNKED_TESTCASES", "40") or 40)

ENABLE_MANTISBT_BUG_CREATION = os.getenv(
    "ENABLE_MANTISBT_BUG_CREATION",
    "false",
).lower() in ("1", "true", "yes")
MANTISBT_URL = os.getenv("MANTISBT_URL", "http://localhost/mantisbt/api/rest")
MANTISBT_API_TOKEN = os.getenv("MANTISBT_API_TOKEN", "")
MANTISBT_USERNAME = os.getenv("MANTISBT_USERNAME", "")
MANTISBT_PASSWORD = os.getenv("MANTISBT_PASSWORD", "")
MANTISBT_PROJECT_ID = int(os.getenv("MANTISBT_PROJECT_ID", "0") or 0)
MANTISBT_PROJECT_NAME = os.getenv("MANTISBT_PROJECT_NAME", "")
MANTISBT_CATEGORY = os.getenv("MANTISBT_CATEGORY", "Automation")
MANTISBT_PRIORITY = os.getenv("MANTISBT_PRIORITY", "normal")
MANTISBT_SEVERITY = os.getenv("MANTISBT_SEVERITY", "major")
MANTISBT_REPRODUCIBILITY = os.getenv("MANTISBT_REPRODUCIBILITY", "always")
MANTISBT_HANDLER_ID = int(os.getenv("MANTISBT_HANDLER_ID", "0") or 0)
MANTISBT_ATTACH_VIDEO = os.getenv("MANTISBT_ATTACH_VIDEO", "false").lower() in (
    "1",
    "true",
    "yes",
)
MANTISBT_CLOSE_ON_PASS = os.getenv("MANTISBT_CLOSE_ON_PASS", "true").lower() in (
    "1",
    "true",
    "yes",
)
MANTISBT_REOPEN_ON_FAILURE = os.getenv("MANTISBT_REOPEN_ON_FAILURE", "true").lower() in (
    "1",
    "true",
    "yes",
)
MANTISBT_CLOSED_STATUS = os.getenv("MANTISBT_CLOSED_STATUS", "closed")
MANTISBT_REOPEN_STATUS = os.getenv("MANTISBT_REOPEN_STATUS", "feedback")
MANTISBT_MAX_INLINE_ATTACHMENT_MB = float(
    os.getenv("MANTISBT_MAX_INLINE_ATTACHMENT_MB", "8")
)

TARGET_CALCULATOR_URL = "https://www.calculator.net/basic-calculator.html"

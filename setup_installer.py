import importlib.util
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Dependency:
    package_name: str
    import_name: str


DEPENDENCIES = [
    Dependency("openai", "openai"),
    Dependency("google-generativeai", "google.generativeai"),
    Dependency("PyGithub", "github"),
    Dependency("pytest", "pytest"),
    Dependency("pytest-html", "pytest_html"),
    Dependency("playwright", "playwright"),
    Dependency("TestLink-API-Python-client", "testlink"),
]


def ensure_python_version() -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError(
            "Python 3.11 or newer is required. "
            f"Current version: {sys.version.split()[0]}"
        )


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def is_package_installed(import_name: str) -> bool:
    return importlib.util.find_spec(import_name) is not None


def run_command(command: list[str], description: str) -> None:
    log_info(description)
    try:
        subprocess.check_call(command)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Command failed: {' '.join(command)}") from exc


def install_missing_dependencies() -> None:
    missing_packages = [
        dependency.package_name
        for dependency in DEPENDENCIES
        if not is_package_installed(dependency.import_name)
    ]

    if not missing_packages:
        log_success("All Python dependencies are already installed.")
        return

    log_info(f"Installing missing dependencies: {', '.join(missing_packages)}")
    run_command(
        [sys.executable, "-m", "pip", "install", *missing_packages],
        "Installing Python packages with pip.",
    )
    log_success("Missing Python dependencies installed successfully.")


def install_playwright_browsers() -> None:
    run_command(
        [sys.executable, "-m", "playwright", "install"],
        "Ensuring Playwright browsers are installed.",
    )
    log_success("Playwright browsers are ready.")


def setup_environment() -> None:
    ensure_python_version()
    install_missing_dependencies()
    install_playwright_browsers()

from github import Github, GithubException, UnknownObjectException

import config


DEMO_REQUIREMENT = (
    "Calculator web app supports +, -, *, /, decimals, chained operations, "
    "and division by zero handling."
)
DEMO_DESIGN = (
    "UI has number buttons (0-9), operators, equals button, clear button, "
    "and display screen."
)


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def _require_github_config() -> None:
    missing = []
    if not config.GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN")
    if not config.REPO_NAME:
        missing.append("REPO_NAME")

    if missing:
        raise ValueError(
            "Missing GitHub configuration: "
            + ", ".join(missing)
            + ". Set values in environment variables or config.py."
        )


def _repo_full_name() -> str:
    if "/" in config.REPO_NAME:
        return config.REPO_NAME
    if not config.GITHUB_USERNAME:
        raise ValueError(
            "GITHUB_USERNAME is required when REPO_NAME is not in owner/repo format."
        )
    return f"{config.GITHUB_USERNAME}/{config.REPO_NAME}"


def _get_or_create_file(repo, path: str, demo_content: str) -> str:
    try:
        existing = repo.get_contents(path, ref=config.GITHUB_BRANCH)
        content = existing.decoded_content.decode("utf-8")
        log_success(f"Fetched {path} from GitHub.")
        return content
    except UnknownObjectException:
        log_info(f"{path} not found. Creating it with demo content.")
        repo.create_file(
            path=path,
            message=f"Create demo {path}",
            content=demo_content,
            branch=config.GITHUB_BRANCH,
        )
        log_success(f"Created {path} in GitHub with demo content.")
        return demo_content


def _latest_commit_sha(repo, path: str) -> str:
    commits = repo.get_commits(path=path, sha=config.GITHUB_BRANCH)
    try:
        return commits[0].sha
    except IndexError as exc:
        raise RuntimeError(f"Could not find a commit for GitHub file: {path}") from exc


def fetch_or_create_requirements_and_design_with_metadata() -> tuple[str, str, dict[str, str]]:
    _require_github_config()

    try:
        github_client = Github(config.GITHUB_TOKEN)
        repo = github_client.get_repo(_repo_full_name())
        requirement = _get_or_create_file(repo, "requirement.txt", DEMO_REQUIREMENT)
        design = _get_or_create_file(repo, "design.txt", DEMO_DESIGN)
        metadata = {
            "repo": repo.full_name,
            "branch": config.GITHUB_BRANCH,
            "requirement_commit_id": _latest_commit_sha(repo, "requirement.txt"),
            "design_commit_id": _latest_commit_sha(repo, "design.txt"),
        }
        return requirement, design, metadata
    except GithubException as exc:
        log_error(f"GitHub API error: {exc.data if hasattr(exc, 'data') else exc}")
        raise RuntimeError("Unable to fetch or create GitHub files.") from exc
    except Exception as exc:
        log_error(f"GitHub operation failed: {exc}")
        raise


def fetch_or_create_requirements_and_design() -> tuple[str, str]:
    requirement, design, _ = fetch_or_create_requirements_and_design_with_metadata()
    return requirement, design

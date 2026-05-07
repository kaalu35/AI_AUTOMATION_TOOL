import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


METADATA_PATH = Path("generated_data") / "run_metadata.json"
SOURCE_SNAPSHOT_PATH = Path("generated_data") / "source_snapshot.json"


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def load_run_metadata() -> dict[str, Any]:
    if not METADATA_PATH.exists():
        return {}
    return json.loads(METADATA_PATH.read_text(encoding="utf-8"))


def source_changed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    tracked_keys = (
        "repo",
        "branch",
        "requirement_commit_id",
        "design_commit_id",
    )
    if not previous:
        return True
    return any(previous.get(key) != current.get(key) for key in tracked_keys)


def save_run_metadata(current: dict[str, Any]) -> None:
    payload = dict(current)
    payload["last_processed_at_utc"] = datetime.now(timezone.utc).isoformat()
    METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    METADATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log_info(f"Saved run metadata to {METADATA_PATH}.")


def load_source_snapshot() -> dict[str, Any]:
    if not SOURCE_SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SOURCE_SNAPSHOT_PATH.read_text(encoding="utf-8"))


def save_source_snapshot(requirement: str, design: str, metadata: dict[str, Any]) -> None:
    payload = {
        "requirement": requirement,
        "design": design,
        "metadata": dict(metadata),
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    SOURCE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log_info(f"Saved source snapshot to {SOURCE_SNAPSHOT_PATH}.")

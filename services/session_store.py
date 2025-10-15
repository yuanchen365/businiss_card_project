from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_STORE_DIR = BASE_DIR / "session_payloads"
SESSION_STORE_DIR.mkdir(exist_ok=True)


def _batch_path(session_key: str, batch_id: str) -> Path:
    return SESSION_STORE_DIR / f"{session_key}_{batch_id}.json"


def save_payload(session_key: str, batch_id: str, payload: Dict[str, Any]) -> str:
    path = _batch_path(session_key, batch_id)
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    return str(path)


def load_payload(session_key: str, batch_id: str) -> Optional[Dict[str, Any]]:
    path = _batch_path(session_key, batch_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return None


def delete_payload(session_key: str, batch_id: str) -> None:
    path = _batch_path(session_key, batch_id)
    path.unlink(missing_ok=True)


def cleanup_session(session_key: str) -> None:
    pattern = f"{session_key}_*.json"
    for path in SESSION_STORE_DIR.glob(pattern):
        path.unlink(missing_ok=True)

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
STORE_PATH = DATA_DIR / "billing_state.json"

_lock = threading.Lock()
_HISTORY_LIMIT = 20
_INITIAL_FREE_CREDITS = 5
_PACK_TIERS: List[Dict[str, int]] = []


def set_pack_tiers(tiers: List[Dict[str, int]]) -> None:
    global _PACK_TIERS
    _PACK_TIERS = tiers or []


def get_credits_for_tier(index: int) -> int:
    if not _PACK_TIERS:
        return 50
    if index < 0 or index >= len(_PACK_TIERS):
        index = 0
    return int(_PACK_TIERS[index]["credits"])


def _load_state() -> Dict[str, Dict]:
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text("utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_state(state: Dict[str, Dict]) -> None:
    STORE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


def _append_history(customer: Dict, action: str, amount: Optional[int] = None, note: Optional[str] = None) -> None:
    entry = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        "action": action,
    }
    if amount is not None:
        entry["amount"] = amount
    if note:
        entry["note"] = note
    history = customer.get("history") or []
    history.insert(0, entry)
    customer["history"] = history[:_HISTORY_LIMIT]


def _new_customer(user_key: str) -> Dict:
    customer = {
        "quota": _INITIAL_FREE_CREDITS,
        "stripe_customer_id": None,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "history": [],
        "free_trial": True,
        "processed_sessions": [],
    }
    _append_history(customer, "free_trial", amount=_INITIAL_FREE_CREDITS, note="新帳號免費試用 5 張名片額度。")
    return customer


def ensure_customer(user_key: str) -> Dict:
    with _lock:
        state = _load_state()
        customer = state.get(user_key)
        changed = False
        if not customer:
            customer = _new_customer(user_key)
            state[user_key] = customer
            changed = True
        else:
            if not isinstance(customer.get("history"), list):
                customer["history"] = customer.get("history") or []
                changed = True
            if customer.get("quota") is None:
                customer["quota"] = 0
                changed = True
            if "quota" not in customer:
                customer["quota"] = 0
                changed = True
            if customer.get("plan"):
                customer["plan"] = None
                changed = True
            if "free_trial" not in customer:
                customer["free_trial"] = customer.get("quota", 0) >= _INITIAL_FREE_CREDITS and not customer.get("history")
                changed = True
            # Ensure processed_sessions exists for idempotent Stripe handling
            if not isinstance(customer.get("processed_sessions"), list):
                customer["processed_sessions"] = []
                changed = True
        if changed:
            state[user_key] = customer
            _save_state(state)
        return customer


def get_customer(user_key: str) -> Optional[Dict]:
    with _lock:
        state = _load_state()
        return state.get(user_key)


def add_quota(user_key: str, amount: int, action_note: Optional[str] = None) -> Dict:
    ensure_customer(user_key)
    with _lock:
        state = _load_state()
        customer = state[user_key]
        customer["quota"] = max(0, int(customer.get("quota", 0))) + amount
        customer["free_trial"] = False
        note = action_note or f"新增 {amount} 張名片額度。"
        _append_history(customer, "quota_added", amount=amount, note=note)
        customer["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
        state[user_key] = customer
        _save_state(state)
        return customer


def add_history(user_key: str, action: str, note: str) -> Dict:
    ensure_customer(user_key)
    with _lock:
        state = _load_state()
        customer = state[user_key]
        _append_history(customer, action, note=note)
        customer["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
        state[user_key] = customer
        _save_state(state)
        return customer


def has_quota(user_key: str, required: int) -> bool:
    customer = ensure_customer(user_key)
    return (customer.get("quota") or 0) >= required


def deduct_quota(user_key: str, amount: int = 1) -> bool:
    ensure_customer(user_key)
    with _lock:
        state = _load_state()
        customer = state[user_key]
        quota = int(customer.get("quota") or 0)
        if quota < amount:
            return False
        quota -= amount
        customer["quota"] = quota
        if quota <= 0:
            customer["free_trial"] = False
        _append_history(customer, "quota_used", amount=amount, note=f"使用 {amount} 張名片，剩餘 {quota} 張。")
        customer["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
        state[user_key] = customer
        _save_state(state)
        return True


def set_stripe_customer_id(user_key: str, customer_id: str) -> Dict:
    ensure_customer(user_key)
    return update_customer(user_key, stripe_customer_id=customer_id)


def update_customer(user_key: str, **fields) -> Dict:
    ensure_customer(user_key)
    with _lock:
        state = _load_state()
        customer = state[user_key]
        customer.update(fields)
        customer["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
        state[user_key] = customer
        _save_state(state)
        return customer


def find_user_by_customer(customer_id: str) -> Optional[str]:
    if not customer_id:
        return None
    with _lock:
        state = _load_state()
        for user, info in state.items():
            if info.get("stripe_customer_id") == customer_id:
                return user
    return None


def was_session_processed(user_key: str, session_id: Optional[str]) -> bool:
    """Check if a Stripe Checkout session has already been applied."""
    if not session_id:
        return False
    with _lock:
        state = _load_state()
        customer = state.get(user_key) or {}
        processed = customer.get("processed_sessions") or []
        return session_id in processed


def mark_session_processed(user_key: str, session_id: Optional[str]) -> Dict:
    """Mark a Stripe Checkout session as processed to ensure idempotency."""
    ensure_customer(user_key)
    if not session_id:
        return get_customer(user_key) or {}
    with _lock:
        state = _load_state()
        customer = state[user_key]
        processed = list(customer.get("processed_sessions") or [])
        if session_id not in processed:
            processed.insert(0, session_id)
        customer["processed_sessions"] = processed[:100]
        customer["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
        state[user_key] = customer
        _save_state(state)
        return customer

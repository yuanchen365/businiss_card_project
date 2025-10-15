from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:  # Optional dependency for production persistence
    from google.cloud import firestore  # type: ignore
except Exception:  # pragma: no cover - local/dev without Firestore
    firestore = None  # type: ignore


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
STORE_PATH = DATA_DIR / "billing_state.json"

_lock = threading.Lock()
_HISTORY_LIMIT = 20
_INITIAL_FREE_CREDITS = 5
_PACK_TIERS: List[Dict[str, int]] = []

FIRESTORE_COLLECTION = (os.getenv("FIRESTORE_COLLECTION") or "").strip()
_USE_FIRESTORE = bool(FIRESTORE_COLLECTION and firestore is not None)
_fs_client = None

MutationResult = Tuple[Dict[str, Any], Any, bool]


def _firestore_client():
    global _fs_client
    if not _USE_FIRESTORE:
        return None
    if _fs_client is None:
        try:
            _fs_client = firestore.Client()  # type: ignore[arg-type]
        except Exception:  # pragma: no cover - fallback to local JSON store
            _fs_client = None
    return _fs_client


def _doc_ref(user_key: str):
    client = _firestore_client()
    if client is None:
        return None
    try:
        return client.collection(FIRESTORE_COLLECTION).document(user_key)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        return None


def set_pack_tiers(tiers: List[Dict[str, int]]) -> None:
    global _PACK_TIERS
    _PACK_TIERS = tiers or []


def get_credits_for_tier(index: int) -> int:
    if not _PACK_TIERS:
        return 50
    if index < 0 or index >= len(_PACK_TIERS):
        index = 0
    return int(_PACK_TIERS[index]["credits"])


def _load_state() -> Dict[str, Dict[str, Any]]:
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text("utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_state(state: Dict[str, Dict[str, Any]]) -> None:
    STORE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


def _append_history(customer: Dict[str, Any], action: str, amount: Optional[int] = None, note: Optional[str] = None) -> None:
    entry: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        "action": action,
    }
    if amount is not None:
        entry["amount"] = amount
    if note:
        entry["note"] = note
    history = list(customer.get("history") or [])
    history.insert(0, entry)
    customer["history"] = history[:_HISTORY_LIMIT]


def _new_customer(user_key: str) -> Dict[str, Any]:
    customer: Dict[str, Any] = {
        "quota": _INITIAL_FREE_CREDITS,
        "stripe_customer_id": None,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "history": [],
        "free_trial": True,
        "processed_sessions": [],
    }
    _append_history(customer, "free_trial", amount=_INITIAL_FREE_CREDITS, note="新帳號免費試用 5 張名片額度")
    return customer


def _fs_mutation(user_key: str, mutator: Callable[[Dict[str, Any], bool], MutationResult]) -> Optional[Any]:
    if not _USE_FIRESTORE:
        return None
    doc = _doc_ref(user_key)
    client = _firestore_client()
    if doc is None or client is None or firestore is None:
        return None

    transaction = client.transaction()

    @firestore.transactional  # type: ignore[attr-defined]
    def txn(transaction, doc_ref):  # type: ignore[no-redef]
        snapshot = doc_ref.get(transaction=transaction)
        created = not snapshot.exists
        data = snapshot.to_dict() if snapshot.exists else _new_customer(user_key)
        new_data, result, changed = mutator(data or {}, created)  # type: ignore[arg-type]
        if created or changed:
            new_data["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
            transaction.set(doc_ref, new_data)
        return result if result is not None else new_data

    try:
        return txn(transaction, doc)
    except Exception:  # pragma: no cover - surface fallback
        return None


def ensure_customer(user_key: str) -> Dict[str, Any]:
    def mutate(data: Dict[str, Any], created: bool) -> MutationResult:
        changed = created
        if not isinstance(data.get("history"), list):
            data["history"] = data.get("history") or []
            changed = True
        if data.get("quota") is None or "quota" not in data:
            data["quota"] = int(data.get("quota") or 0)
            changed = True
        if data.get("plan"):
            data["plan"] = None
            changed = True
        if "free_trial" not in data:
            data["free_trial"] = (data.get("quota", 0) >= _INITIAL_FREE_CREDITS and not data.get("history"))
            changed = True
        if not isinstance(data.get("processed_sessions"), list):
            data["processed_sessions"] = []
            changed = True
        return data, data, changed

    fs_result = _fs_mutation(user_key, mutate)
    if isinstance(fs_result, dict):
        return fs_result

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
            if customer.get("quota") is None or "quota" not in customer:
                customer["quota"] = int(customer.get("quota") or 0)
                changed = True
            if customer.get("plan"):
                customer["plan"] = None
                changed = True
            if "free_trial" not in customer:
                customer["free_trial"] = customer.get("quota", 0) >= _INITIAL_FREE_CREDITS and not customer.get("history")
                changed = True
            if not isinstance(customer.get("processed_sessions"), list):
                customer["processed_sessions"] = []
                changed = True
        if changed:
            customer["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
            state[user_key] = customer
            _save_state(state)
        return customer


def get_customer(user_key: str) -> Optional[Dict[str, Any]]:
    doc = _doc_ref(user_key)
    if doc is not None:
        try:
            snapshot = doc.get()
            if snapshot.exists:
                return snapshot.to_dict() or {}
            return None
        except Exception:
            pass
    with _lock:
        state = _load_state()
        return state.get(user_key)


def add_quota(user_key: str, amount: int, action_note: Optional[str] = None) -> Dict[str, Any]:
    def mutate(data: Dict[str, Any], created: bool) -> MutationResult:
        quota = max(0, int(data.get("quota", 0))) + int(amount)
        data["quota"] = quota
        data["free_trial"] = False
        note = action_note or f"增加 {amount} 張名片額度"
        _append_history(data, "quota_added", amount=amount, note=note)
        return data, data, True

    fs_result = _fs_mutation(user_key, mutate)
    if isinstance(fs_result, dict):
        return fs_result

    ensure_customer(user_key)
    with _lock:
        state = _load_state()
        customer = state[user_key]
        customer["quota"] = max(0, int(customer.get("quota", 0))) + amount
        customer["free_trial"] = False
        note = action_note or f"增加 {amount} 張名片額度"
        _append_history(customer, "quota_added", amount=amount, note=note)
        customer["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
        state[user_key] = customer
        _save_state(state)
        return customer


def add_history(user_key: str, action: str, note: str) -> Dict[str, Any]:
    def mutate(data: Dict[str, Any], created: bool) -> MutationResult:
        _append_history(data, action, note=note)
        return data, data, True

    fs_result = _fs_mutation(user_key, mutate)
    if isinstance(fs_result, dict):
        return fs_result

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
    def mutate(data: Dict[str, Any], created: bool) -> MutationResult:
        quota = int(data.get("quota") or 0)
        if quota < amount:
            return data, False, False
        quota -= amount
        data["quota"] = quota
        if quota <= 0:
            data["free_trial"] = False
        _append_history(data, "quota_used", amount=amount, note=f"使用 {amount} 張；剩餘 {quota} 張")
        return data, True, True

    fs_result = _fs_mutation(user_key, mutate)
    if isinstance(fs_result, bool):
        return fs_result

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
        _append_history(customer, "quota_used", amount=amount, note=f"使用 {amount} 張；剩餘 {quota} 張")
        customer["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
        state[user_key] = customer
        _save_state(state)
        return True


def set_stripe_customer_id(user_key: str, customer_id: str) -> Dict[str, Any]:
    return update_customer(user_key, stripe_customer_id=customer_id)


def update_customer(user_key: str, **fields: Any) -> Dict[str, Any]:
    def mutate(data: Dict[str, Any], created: bool) -> MutationResult:
        data.update(fields)
        return data, data, True

    fs_result = _fs_mutation(user_key, mutate)
    if isinstance(fs_result, dict):
        return fs_result

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
    client = _firestore_client()
    if client is not None:
        try:
            col = client.collection(FIRESTORE_COLLECTION)
            docs = list(col.where("stripe_customer_id", "==", customer_id).limit(1).stream())
            if docs:
                return docs[0].id
        except Exception:
            pass
    with _lock:
        state = _load_state()
        for user, info in state.items():
            if info.get("stripe_customer_id") == customer_id:
                return user
    return None


def was_session_processed(user_key: str, session_id: Optional[str]) -> bool:
    if not session_id:
        return False
    doc = _doc_ref(user_key)
    if doc is not None:
        try:
            snapshot = doc.get()
            if not snapshot.exists:
                return False
            data = snapshot.to_dict() or {}
            processed = data.get("processed_sessions") or []
            return session_id in processed
        except Exception:
            pass
    with _lock:
        state = _load_state()
        customer = state.get(user_key) or {}
        processed = customer.get("processed_sessions") or []
        return session_id in processed


def mark_session_processed(user_key: str, session_id: Optional[str]) -> Dict[str, Any]:
    if not session_id:
        return get_customer(user_key) or {}

    def mutate(data: Dict[str, Any], created: bool) -> MutationResult:
        processed = list(data.get("processed_sessions") or [])
        if session_id not in processed:
            processed.insert(0, session_id)
        data["processed_sessions"] = processed[:100]
        return data, data, True

    fs_result = _fs_mutation(user_key, mutate)
    if isinstance(fs_result, dict):
        return fs_result

    ensure_customer(user_key)
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

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import stripe

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

from services.session_store import save_payload, load_payload, delete_payload, cleanup_session
from services import billing

from google.auth import exceptions as google_auth_exceptions

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests


load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
if (
    os.getenv("OAUTHLIB_INSECURE_TRANSPORT") != "1"
    and (
        os.getenv("GOOGLE_REDIRECT_URI", "").startswith("http://")
        or os.getenv("ENV", "dev").lower() in {"dev", "development", "local"}
    )
):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


app = FastAPI(title="名片辨識 × Google 通訊錄")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev"))

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
TOKEN_DIR = BASE_DIR / ".tokens"
TOKEN_DIR.mkdir(exist_ok=True)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

STRIPE_PRICE_CREDITS = os.getenv("STRIPE_PRICE_CREDITS")
CREDIT_PACK_PRICE = os.getenv("CREDIT_PACK_PRICE", "5")
CREDIT_PACK_TIERS_ENV = os.getenv("CREDIT_PACK_TIERS")
PACK_TIERS: List[Dict[str, int]] = []
if CREDIT_PACK_TIERS_ENV:
    for part in CREDIT_PACK_TIERS_ENV.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            credits_str, price_str = part.split(":", 1)
            PACK_TIERS.append({"credits": int(credits_str), "price": price_str})
        except ValueError:
            continue
else:
    default_options = [(50, "5"), (100, "10"), (150, "15")]
    for credits, price in default_options:
        PACK_TIERS.append({"credits": credits, "price": price})

billing.set_pack_tiers(PACK_TIERS)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def ensure_session_id(request: Request) -> str:
    session_id = request.session.get("session_key")
    if not session_id:
        session_id = uuid.uuid4().hex
        request.session["session_key"] = session_id
    return session_id


REQUIRED_SCOPES = {
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/contacts",
}


def get_google_flow(state: Optional[str] = None):
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [os.getenv("GOOGLE_REDIRECT_URI")],
        }
    }
    default_scopes = "https://www.googleapis.com/auth/contacts,openid,https://www.googleapis.com/auth/userinfo.email"
    scopes = [scope.strip() for scope in (os.getenv("GOOGLE_SCOPES") or default_scopes).split(",") if scope.strip()]
    scope_set = set(scopes)
    scope_set.update(REQUIRED_SCOPES)
    scopes = sorted(scope_set)
    flow = Flow.from_client_config(client_config, scopes=scopes, state=state)
    flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    return flow


def credentials_from_session(request: Request):
    from google.oauth2.credentials import Credentials

    user_key = request.session.get("user_key")
    if not user_key:
        return None
    token_path = TOKEN_DIR / f"{user_key}.json"
    if not token_path.exists():
        return None
    data = json.loads(token_path.read_text("utf-8"))
    return Credentials.from_authorized_user_info(data)


def save_credentials(user_key: str, credentials: Any) -> None:
    data = json.loads(credentials.to_json())
    (TOKEN_DIR / f"{user_key}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def revoke_credentials(creds: Any) -> None:
    import requests

    try:
        requests.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": creds.token},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
    except Exception:
        pass


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    ensure_session_id(request)
    user_key = request.session.get("user_key")
    flash_error = request.session.pop("flash_error", None)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user_key": user_key,
            "scopes": os.getenv("GOOGLE_SCOPES") or "https://www.googleapis.com/auth/contacts",
            "error": flash_error,
            "upload_disabled": not bool(user_key),
        },
    )


@app.get("/auth/login")
async def auth_login(request: Request):
    flow = get_google_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    request.session["oauth_state"] = state
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        from starlette.datastructures import URL
        from services.people_service import build_google_service

        stored_state = request.session.get("oauth_state")
        request_state = request.query_params.get("state")
        if not stored_state or stored_state != request_state:
            print("[auth_callback] state mismatch; stored=", stored_state, "request=", request_state)
            request.session.clear()
            request.session["flash_error"] = "登入逾時，請重新登入。"
            return RedirectResponse("/", status_code=303)

        flow = get_google_flow(state=stored_state)

        url = URL(str(request.url)).replace(scheme="http")
        flow.fetch_token(authorization_response=str(url))
        request.session.pop("oauth_state", None)
        creds = flow.credentials

        user_key: Optional[str] = None
        try:
            svc = build_google_service(creds)
            me = svc.people().get(resourceName="people/me", personFields="emailAddresses,names").execute()
            emails = me.get("emailAddresses") or []
            if emails and emails[0].get("value"):
                user_key = emails[0]["value"]
        except Exception as exc:
            print("[auth_callback] failed to fetch profile:", exc)

        if not user_key:
            try:
                idinfo = google_id_token.verify_oauth2_token(
                    creds.id_token,
                    google_requests.Request(),
                    os.getenv("GOOGLE_CLIENT_ID"),
                )
                user_key = idinfo.get("email")
            except Exception as exc:
                print("[auth_callback] failed to decode id_token:", exc)

        if not user_key:
            request.session["flash_error"] = (
                "登入失敗：無法取得 Google 帳號 Email，請確認 OAuth scope 設定並重新授權。"
            )
            return RedirectResponse("/", status_code=303)

        request.session["user_key"] = user_key
        save_credentials(user_key, creds)
        billing.ensure_customer(user_key)
        return RedirectResponse("/")
    except google_auth_exceptions.RefreshError as exc:
        for token_file in TOKEN_DIR.glob("*.json"):
            token_file.unlink(missing_ok=True)
        request.session.clear()
        request.session["flash_error"] = (
            "Google 授權範圍已變更，請確認 GOOGLE_SCOPES 含 `https://www.googleapis.com/auth/contacts,openid,https://www.googleapis.com/auth/userinfo.email` 後重新登入。"
        )
        print("[auth_callback] scope refresh error:", exc)
        return RedirectResponse("/", status_code=303)
    except Exception as exc:
        message = str(exc)
        if "scope has changed" in message.lower():
            for token_file in TOKEN_DIR.glob("*.json"):
                token_file.unlink(missing_ok=True)
            request.session.clear()
            request.session["flash_error"] = "Google 授權已更新，請重新登入一次。"
            print("[auth_callback] scope changed, cleared tokens")
            return RedirectResponse("/", status_code=303)
        request.session["flash_error"] = f"OAuth 回呼失敗：{exc}"
        return RedirectResponse("/")

@app.get("/auth/logout")
async def auth_logout(request: Request):
    session_id = request.session.get("session_key")
    creds = credentials_from_session(request)
    if creds:
        revoke_credentials(creds)
        token_path = TOKEN_DIR / f"{request.session.get('user_key')}.json"
        if token_path.exists():
            token_path.unlink(missing_ok=True)
    if session_id:
        cleanup_session(session_id)
    request.session.clear()
    return RedirectResponse("/")


@app.post("/upload")
async def upload(request: Request, files: List[UploadFile] = File(...)):
    if not request.session.get("user_key"):
        request.session["flash_error"] = "請先登入 Google 後再上傳名片。"
        return RedirectResponse("/", status_code=303)

    if not files:
        request.session["flash_error"] = "請選擇至少 1 張名片。"
        return RedirectResponse("/", status_code=303)

    if len(files) > 5:
        request.session["flash_error"] = "一次最多處理 5 張名片。"
        return RedirectResponse("/", status_code=303)

    from services.ocr_service import extract_text
    from services.parse_service import parse_text_to_schema

    session_id = ensure_session_id(request)
    batch_id = uuid.uuid4().hex

    data_list: List[Dict[str, Any]] = []
    ocr_list: List[str] = []
    file_names: List[str] = []
    upload_paths: List[str] = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for upload in files:
        content = await upload.read()
        if len(content) > 10 * 1024 * 1024:
            request.session["flash_error"] = f"{upload.filename} 超過 10MB 限制。"
            return RedirectResponse("/", status_code=303)

        ext = (upload.filename or "").split(".")[-1].lower()
        if ext not in {"jpg", "jpeg", "png", "pdf"}:
            request.session["flash_error"] = f"{upload.filename} 僅支援 JPG/PNG/PDF。"
            return RedirectResponse("/", status_code=303)

        stored_name = f"{uuid.uuid4().hex}_{upload.filename}"
        path = UPLOAD_DIR / stored_name
        path.write_bytes(content)

        ocr_text = extract_text(str(path))
        parsed = parse_text_to_schema(ocr_text)
        parsed["notes"] = f"名片掃描於 {timestamp}，來源：上傳（檔名：{upload.filename}）"

        data_list.append(parsed)
        ocr_list.append(ocr_text)
        file_names.append(upload.filename or stored_name)
        upload_paths.append(str(path))

    draft_defaults = []
    for idx, parsed in enumerate(data_list):
        name = parsed.get("name") or {}
        org = parsed.get("organization") or {}
        draft_defaults.append(
            {
                "index": idx,
                "skip": False,
                "fullName": name.get("fullName", ""),
                "givenName": name.get("givenName", ""),
                "familyName": name.get("familyName", ""),
                "company": org.get("company", ""),
                "title": org.get("title", ""),
                "phones": ",".join([p.get("value", "") for p in (parsed.get("phones") or []) if p.get("value")]),
                "emails": ",".join([e.get("value", "") for e in (parsed.get("emails") or []) if e.get("value")]),
                "addresses": ",".join([
                    a.get("formatted", "")
                    for a in (parsed.get("addresses") or [])
                    if a.get("formatted")
                ]),
                "urls": ",".join([u.get("value", "") for u in (parsed.get("urls") or []) if u.get("value")]),
                "notes": parsed.get("notes", ""),
            }
        )

    payload = {
        "created_at": timestamp,
        "data_list": data_list,
        "ocr_list": ocr_list,
        "file_names": file_names,
        "upload_paths": upload_paths,
        "order": list(range(len(data_list))),
        "draft": draft_defaults,
    }
    save_payload(session_id, batch_id, payload)
    request.session["active_batch_id"] = batch_id

    return RedirectResponse("/review", status_code=303)


def _draft_lookup(payload: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    draft_entries = payload.get("draft") or []
    return {int(entry.get("index", -1)): entry for entry in draft_entries}


@app.get("/review", response_class=HTMLResponse)
async def review(request: Request):
    session_id = ensure_session_id(request)
    batch_id = request.session.get("active_batch_id")
    if not batch_id:
        request.session["flash_error"] = "請先上傳名片再進行辨識。"
        return RedirectResponse("/", status_code=303)

    payload = load_payload(session_id, batch_id)
    if not payload:
        request.session["flash_error"] = "找不到名片辨識資料，請重新上傳。"
        return RedirectResponse("/", status_code=303)

    data_list: List[Dict[str, Any]] = payload.get("data_list") or []
    if not data_list:
        request.session["flash_error"] = "沒有可供審核的名片，請重新上傳。"
        return RedirectResponse("/", status_code=303)

    ocr_list: List[str] = payload.get("ocr_list") or []
    file_names: List[str] = payload.get("file_names") or []
    order = [int(x) for x in payload.get("order") or list(range(len(data_list)))]
    draft_lookup = _draft_lookup(payload)

    user_key = request.session.get("user_key")
    dedupe_entries: List[Optional[Dict[str, Any]]] = [None] * len(data_list)
    if user_key:
        try:
            from services.people_service import PeopleService
            from services.dedupe_service import decide_action

            creds = credentials_from_session(request)
            if creds:
                svc = PeopleService(creds)
                existing = svc.list_connections(page_size=200)
                for idx, data in enumerate(data_list):
                    action, matched, _ = decide_action(data, existing)
                    dedupe_entries[idx] = {
                        "action": action,
                        "resourceName": matched.get("resourceName") if matched else None,
                    }
        except Exception:  # pragma: no cover - fail softly
            dedupe_entries = [None] * len(data_list)

    entries = []
    for idx in order:
        base = data_list[idx]
        draft = draft_lookup.get(idx, {})
        merged_name = {
            "fullName": draft.get("fullName", (base.get("name") or {}).get("fullName", "")),
            "givenName": draft.get("givenName", (base.get("name") or {}).get("givenName", "")),
            "familyName": draft.get("familyName", (base.get("name") or {}).get("familyName", "")),
        }
        merged_org = {
            "company": draft.get("company", (base.get("organization") or {}).get("company", "")),
            "title": draft.get("title", (base.get("organization") or {}).get("title", "")),
        }
        phones = draft.get("phones") or ",".join(
            [p.get("value", "") for p in (base.get("phones") or []) if p.get("value")]
        )
        emails = draft.get("emails") or ",".join(
            [e.get("value", "") for e in (base.get("emails") or []) if e.get("value")]
        )
        addresses = draft.get("addresses") or ",".join(
            [a.get("formatted", "") for a in (base.get("addresses") or []) if a.get("formatted")]
        )
        urls = draft.get("urls") or ",".join(
            [u.get("value", "") for u in (base.get("urls") or []) if u.get("value")]
        )
        notes = draft.get("notes", base.get("notes", ""))

        entries.append(
            {
                "index": idx,
                "data": {
                    "name": merged_name,
                    "organization": merged_org,
                    "notes": notes,
                },
                "phones_str": phones,
                "emails_str": emails,
                "addresses_str": addresses,
                "urls_str": urls,
                "skip": bool(draft.get("skip")),
                "ocr": ocr_list[idx] if idx < len(ocr_list) else "",
                "dedupe": dedupe_entries[idx] if idx < len(dedupe_entries) else None,
                "filename": file_names[idx] if idx < len(file_names) else f"名片 {idx + 1}",
            }
        )

    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "entries": entries,
            "user_key": user_key,
            "total_items": len(entries),
            "order_json": json.dumps([entry["index"] for entry in entries]),
        },
    )


@app.post("/review/draft")
async def save_draft_endpoint(request: Request):
    session_id = ensure_session_id(request)
    batch_id = request.session.get("active_batch_id")
    if not batch_id:
        return JSONResponse({"error": "no active batch"}, status_code=400)

    try:
        payload = await request.body()
        data = json.loads(payload.decode("utf-8")) if payload else {}
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid payload"}, status_code=400)

    store = load_payload(session_id, batch_id) or {}
    order = data.get("order") or store.get("order") or []
    items = data.get("items") or []
    store["order"] = [int(i) for i in order]
    store["draft"] = items
    save_payload(session_id, batch_id, store)
    return JSONResponse({"ok": True})


@app.post("/apply")
async def apply(request: Request):
    from services.phone_email_utils import normalize_phone, validate_email
    from services.dedupe_service import decide_action
    from services.people_service import PeopleService
    from services.log_service import LogSession

    session_id = ensure_session_id(request)
    batch_id = request.session.get("active_batch_id")
    payload = load_payload(session_id, batch_id) if batch_id else None
    if not payload:
        request.session["flash_error"] = "找不到名片批次資料，請重新上傳。"
        return RedirectResponse("/", status_code=303)

    form = await request.form()
    data_list: List[Dict[str, Any]] = payload.get("data_list") or []
    file_names: List[str] = payload.get("file_names") or []
    upload_paths: List[str] = payload.get("upload_paths") or []

    try:
        order_form = json.loads(form.get("order", "[]"))
        order = [int(i) for i in order_form]
    except Exception:
        order = payload.get("order") or list(range(len(data_list)))

    # Ensure only valid indices
    order = [i for i in order if 0 <= i < len(data_list)]
    if len(order) != len(data_list):
        # Fallback to sequential order
        order = list(range(len(data_list)))

    parsed_items = []
    draft_updates = []

    def parse_multi(raw: str) -> List[str]:
        return [value.strip() for value in (raw or "").split(",") if value and value.strip()]

    for idx in order:
        skip = form.get(f"skip_{idx}") == "on"
        full_name = (form.get(f"fullName_{idx}") or "").strip()
        given_name = (form.get(f"givenName_{idx}") or "").strip()
        family_name = (form.get(f"familyName_{idx}") or "").strip()
        company = (form.get(f"company_{idx}") or "").strip()
        title = (form.get(f"title_{idx}") or "").strip()
        phones_raw = parse_multi(form.get(f"phones_{idx}", ""))
        emails_raw = parse_multi(form.get(f"emails_{idx}", ""))
        addresses_raw = parse_multi(form.get(f"addresses_{idx}", ""))
        urls_raw = parse_multi(form.get(f"urls_{idx}", ""))
        notes = (form.get(f"notes_{idx}") or "").strip()

        draft_updates.append(
            {
                "index": idx,
                "skip": skip,
                "fullName": full_name,
                "givenName": given_name,
                "familyName": family_name,
                "company": company,
                "title": title,
                "phones": ",".join(phones_raw),
                "emails": ",".join(emails_raw),
                "addresses": ",".join(addresses_raw),
                "urls": ",".join(urls_raw),
                "notes": notes,
            }
        )

        phone_entries = []
        for phone in phones_raw:
            normalized = normalize_phone(phone)
            if normalized:
                phone_entries.append({"type": "mobile", "value": normalized})

        email_entries = []
        for email in emails_raw:
            valid = validate_email(email)
            if valid:
                email_entries.append({"type": "work", "value": valid})

        parsed_items.append(
            {
                "index": idx,
                "skip": skip,
                "filename": file_names[idx] if idx < len(file_names) else f"名片 {idx + 1}",
                "photo_path": upload_paths[idx] if idx < len(upload_paths) else None,
                "data": {
                    "name": {
                        "fullName": full_name,
                        "givenName": given_name,
                        "familyName": family_name,
                    },
                    "organization": {"company": company, "title": title},
                    "phones": phone_entries,
                    "emails": email_entries,
                    "addresses": [{"type": "work", "formatted": a} for a in addresses_raw],
                    "urls": [{"type": "work", "value": url} for url in urls_raw],
                    "notes": notes,
                },
            }
        )

    payload["order"] = order
    payload["draft"] = draft_updates
    save_payload(session_id, batch_id, payload)

    log = LogSession()
    results: List[Dict[str, Any]] = []

    user_key = request.session.get("user_key") or ""
    creds = credentials_from_session(request)
    if not creds:
        for item in parsed_items:
            row = {
                "index": item["index"] + 1,
                "filename": item["filename"],
                "action": "skip",
                "status": "skipped",
                "reason": "未登入，僅預覽",
                "photoStatus": "未上傳（未登入）",
            }
            log.append({"timestamp": datetime.now().isoformat(timespec="seconds"), **row})
            results.append(row)
        csv_path = log.save_csv(str(LOG_DIR))
        return templates.TemplateResponse(
            "result.html",
            {"request": request, "results": results, "csv_filename": Path(csv_path).name},
        )

    needed = sum(1 for item in parsed_items if not item["skip"])
    if needed > 0 and not billing.has_quota(user_key, needed):
        request.session["flash_error"] = "可用額度不足，請先購買方案或點數。"
        return RedirectResponse("/billing", status_code=303)

    svc = PeopleService(creds)
    existing = svc.list_connections(page_size=200)

    for item in parsed_items:
        idx = item["index"]
        filename = item["filename"]
        photo_path = item["photo_path"]
        data = item["data"]
        row: Dict[str, Any] = {"index": idx + 1, "filename": filename}

        if item["skip"]:
            row.update({
                "action": "skip",
                "status": "skipped",
                "reason": "使用者略過",
                "photoStatus": "未處理（使用者略過）",
            })
            log.append({"timestamp": datetime.now().isoformat(timespec="seconds"), **row})
            results.append(row)
            continue

        try:
            action, matched, _ = decide_action(data, existing)
            row["action"] = action
            if action == "create":
                res = svc.create_contact(data)
                resource_name = res.get("resourceName")
                row.update({"status": "success", "resourceName": resource_name})
                photo_res = None
                if resource_name and photo_path:
                    photo_res = svc.update_contact_photo(resource_name, photo_path)
                    row["photoStatus"] = "已更新" if photo_res else "照片未更新"
                existing.append(photo_res or res)
                billing.deduct_quota(user_key, 1)
            elif action == "update" and matched:
                resource_name = matched.get("resourceName") if isinstance(matched, dict) else None
                if not resource_name:
                    row.update({"status": "failed", "reason": "找不到 resourceName"})
                else:
                    etag = matched.get("etag")
                    if not etag:
                        metadata = matched.get("metadata") or {}
                        sources = metadata.get("sources") or []
                        if sources:
                            etag = sources[0].get("etag")
                    res = svc.update_contact(resource_name, data, etag=etag)
                    updated_resource = res.get("resourceName") or resource_name
                    row.update({"status": "success", "resourceName": updated_resource})
                    photo_res = None
                    if photo_path:
                        photo_res = svc.update_contact_photo(updated_resource, photo_path)
                        row["photoStatus"] = "已更新" if photo_res else "照片未更新"
                    replaced = False
                    for pos, person in enumerate(existing):
                        if person.get("resourceName") == resource_name:
                            existing[pos] = photo_res or res
                            replaced = True
                            break
                    if not replaced:
                        existing.append(photo_res or res)
                    billing.deduct_quota(user_key, 1)
            else:
                row.update({"status": "ok", "reason": "完全相同"})
                if matched and photo_path:
                    resource_name = matched.get("resourceName") if isinstance(matched, dict) else None
                    if resource_name:
                        photo_res = svc.update_contact_photo(resource_name, photo_path)
                        row["photoStatus"] = "已更新" if photo_res else "照片未更新"
                        if photo_res:
                            for pos, person in enumerate(existing):
                                if person.get("resourceName") == resource_name:
                                    existing[pos] = photo_res
                                    break
        except Exception as exc:
            row.update({"status": "failed", "reason": str(exc)})
        finally:
            log.append({"timestamp": datetime.now().isoformat(timespec="seconds"), **row})
            results.append(row)

    csv_path = log.save_csv(str(LOG_DIR))
    for path_str in payload.get("upload_paths", []):
        try:
            Path(path_str).unlink(missing_ok=True)
        except Exception:
            pass
    delete_payload(session_id, batch_id)
    request.session.pop("active_batch_id", None)

    return templates.TemplateResponse(
        "result.html",
        {"request": request, "results": results, "csv_filename": Path(csv_path).name},
    )


@app.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request):
    user_key = request.session.get("user_key")
    if not user_key:
        request.session["flash_error"] = "請先登入帳號。"
        return RedirectResponse("/", status_code=303)

    customer = billing.ensure_customer(user_key)
    status = request.query_params.get("status")
    # Fallback: if redirected from Stripe with a session_id and webhook failed,
    # process the paid Checkout Session here (idempotent via processed_sessions).
    session_id = request.query_params.get("session_id")
    if status == "success" and session_id:
        try:
            if not billing.was_session_processed(user_key, session_id):
                sess = stripe.checkout.Session.retrieve(session_id)
                metadata = sess.get("metadata") or {}
                is_paid = (sess.get("payment_status") == "paid")
                # Basic validation to avoid cross-account crediting
                if is_paid and metadata.get("user_key") == user_key:
                    credits = 0
                    try:
                        credits = int(metadata.get("credits") or 0)
                    except (TypeError, ValueError):
                        credits = 0
                    if credits <= 0:
                        try:
                            tier_index = int(metadata.get("tier_index") or 0)
                        except (TypeError, ValueError):
                            tier_index = 0
                        credits = billing.get_credits_for_tier(tier_index)
                    if credits > 0:
                        billing.add_quota(user_key, credits, action_note=f"Stripe 結帳成功，增加 {credits} 張（session {session_id}）")
                        billing.mark_session_processed(user_key, session_id)
                        # Refresh local snapshot after update
                        customer = billing.ensure_customer(user_key)
        except Exception:
            # Swallow errors in fallback path; webhook remains the primary mechanism
            pass

    quota = int(customer.get("quota") or 0)
    history = customer.get("history") or []
    is_free_trial = customer.get("free_trial", False) and quota > 0 and not any(
        h.get("action") == "quota_added" for h in history
    )

    if is_free_trial:
        plan_label = "免費試用中"
        plan_hint = f"每個帳號享有 {quota} 張免費試用額度，購買點數後即轉為正式方案。"
    elif quota > 0:
        plan_label = "點數方案"
        plan_hint = "已購買點數包，可繼續加值以獲得更多名片額度。"
    else:
        plan_label = "尚未購買"
        plan_hint = "目前沒有可用額度，請購買點數包以繼續使用名片同步功能。"

    status_message = None
    status_level = None
    if status == "success":
        status_message = "付款完成，額度已更新。"
        status_level = "success"
    elif status == "cancelled":
        status_message = "已取消 Stripe 付款或付款失敗，尚未扣款。"
        status_level = "warning"

    pack_options = []
    for idx, tier in enumerate(PACK_TIERS):
        price_value = tier.get("price", CREDIT_PACK_PRICE)
        pack_options.append({
            "index": idx,
            "credits": tier["credits"],
            "price": price_value,
            "price_display": f"US${price_value}",
        })

    return templates.TemplateResponse(
        "billing.html",
        {
            "request": request,
            "user_key": user_key,
            "plan": plan_label,
            "plan_hint": plan_hint,
            "quota": f"{quota} 張",
            "updated_at": customer.get("updated_at"),
            "status_message": status_message,
            "status_level": status_level,
            "history": history,
            "pack_options": pack_options,
        },
    )


@app.post("/billing/checkout")
async def billing_checkout(request: Request):
    user_key = request.session.get("user_key")
    if not user_key:
        request.session["flash_error"] = "請先登入帳號。"
        return RedirectResponse("/", status_code=303)

    form = await request.form()
    tier_index = form.get("tier")
    try:
        tier_index = int(tier_index)
    except (TypeError, ValueError):
        tier_index = 0
    if tier_index < 0 or tier_index >= len(PACK_TIERS):
        tier_index = 0
    selected_tier = PACK_TIERS[tier_index]

    price_id_env = os.getenv(f"STRIPE_PRICE_CREDITS_{tier_index}")
    if not price_id_env and tier_index == 0:
        price_id_env = os.getenv("STRIPE_PRICE_CREDITS")
    if not price_id_env:
        request.session["flash_error"] = "尚未設定對應的點數價格 ID。"
        return RedirectResponse("/billing", status_code=303)

    customer_info = billing.ensure_customer(user_key)
    stripe_customer_id = customer_info.get("stripe_customer_id")

    # Include session_id in success_url to allow fallback quota update if webhook fails
    success_url = str(request.url_for("billing_page")) + "?status=success&session_id={CHECKOUT_SESSION_ID}"
    cancel_url = str(request.url_for("billing_page")) + "?status=cancelled"

    checkout_kwargs = {
        "mode": "payment",
        "line_items": [{"price": price_id_env, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {
            "user_key": user_key,
            "product": "credits",
            "tier_index": str(tier_index),
            "credits": str(selected_tier.get("credits", 0)),
        },
    }
    if stripe_customer_id:
        checkout_kwargs["customer"] = stripe_customer_id
    else:
        checkout_kwargs["customer_email"] = user_key

    session = stripe.checkout.Session.create(**checkout_kwargs)
    return RedirectResponse(session.url, status_code=303)


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not endpoint_secret or not sig_header:
        return JSONResponse({"error": "missing signature"}, status_code=400)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return JSONResponse({"error": "invalid payload"}, status_code=400)
    except stripe.error.SignatureVerificationError:
        return JSONResponse({"error": "invalid signature"}, status_code=400)

    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        metadata = data_object.get("metadata") or {}
        user_key = metadata.get("user_key")
        tier_index = metadata.get("tier_index")
        customer_id = data_object.get("customer")
        if user_key:
            if customer_id:
                billing.set_stripe_customer_id(user_key, customer_id)
            try:
                tier_index = int(tier_index) if tier_index is not None else 0
            except ValueError:
                tier_index = 0
            credits = billing.get_credits_for_tier(tier_index)
            billing.add_quota(user_key, credits, action_note=f"購買點數方案（方案 #{tier_index + 1}）。")

    # Mark session as processed to avoid double crediting in fallback flow
    if event_type == "checkout.session.completed":
        obj = event.get("data", {}).get("object", {})
        metadata2 = obj.get("metadata") or {}
        user_key2 = metadata2.get("user_key")
        session_id2 = obj.get("id")
        if user_key2 and session_id2:
            try:
                billing.mark_session_processed(user_key2, session_id2)
            except Exception:
                pass

    return JSONResponse({"received": True})


@app.get("/logs/{filename}")
async def get_log(filename: str):
    path = LOG_DIR / filename
    return FileResponse(path) if path.exists() else FileResponse(LOG_DIR / "")

from __future__ import annotations

import os
import base64
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image


def build_google_service(credentials: Any):
    """Lazy import to avoid hard dependency during tests."""
    from googleapiclient.discovery import build

    return build("people", "v1", credentials=credentials, cache_discovery=False)


def unify_schema_to_people_body(data: Dict) -> Dict:
    body: Dict = {}
    name = data.get("name") or {}
    org = data.get("organization") or {}
    if any(name.get(k) for k in ("givenName", "familyName", "fullName")):
        body["names"] = [{
            "displayName": name.get("fullName") or None,
            "givenName": name.get("givenName") or None,
            "familyName": name.get("familyName") or None,
        }]
    if any(org.get(k) for k in ("company", "title")):
        body["organizations"] = [{
            "name": org.get("company") or None,
            "title": org.get("title") or None,
        }]
    if data.get("phones"):
        body["phoneNumbers"] = [{"value": p.get("value"), "type": p.get("type") or None} for p in data["phones"]]
    if data.get("emails"):
        body["emailAddresses"] = [{"value": e.get("value"), "type": e.get("type") or None} for e in data["emails"]]
    if data.get("addresses"):
        body["addresses"] = [{"formattedValue": a.get("formatted"), "type": a.get("type") or None} for a in data["addresses"]]
    if data.get("urls"):
        body["urls"] = [{"value": u.get("value"), "type": u.get("type") or None} for u in data["urls"]]
    if data.get("notes"):
        body["biographies"] = [{"value": data.get("notes") or ""}]
    if data.get("etag"):
        body["etag"] = data["etag"]
    return body


def fields_from_body(body: Dict) -> str:
    keys = []
    mapping = {
        "names": "names",
        "organizations": "organizations",
        "phoneNumbers": "phoneNumbers",
        "emailAddresses": "emailAddresses",
        "addresses": "addresses",
        "urls": "urls",
        "biographies": "biographies",
    }
    for k in mapping:
        if body.get(k) is not None:
            keys.append(mapping[k])
    return ",".join(sorted(keys))


class PeopleService:
    def __init__(self, credentials: Any) -> None:
        self.credentials = credentials
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = build_google_service(self.credentials)
        return self._service

    def list_connections(self, page_size: int = 500) -> List[Dict]:
        people = []
        page_token = None
        while True:
            req = self.service.people().connections().list(
                resourceName="people/me",
                pageSize=page_size,
                pageToken=page_token,
                personFields="names,emailAddresses,phoneNumbers,organizations,addresses,urls,biographies,metadata",
            )
            res = req.execute()
            people.extend(res.get("connections", []))
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return people

    def create_contact(self, data: Dict) -> Dict:
        body = unify_schema_to_people_body(data)
        req = self.service.people().createContact(body=body)
        return req.execute()

    def update_contact(self, resource_name: str, data: Dict, etag: Optional[str] = None) -> Dict:
        body = unify_schema_to_people_body(data)
        etag_value = etag or data.get("etag")
        if not etag_value:
            metadata = data.get("metadata")
            if metadata:
                sources = metadata.get("sources") or []
                if sources:
                    etag_value = sources[0].get("etag")
        if etag_value:
            body["etag"] = etag_value
        fields = fields_from_body(body)
        req = self.service.people().updateContact(
            resourceName=resource_name,
            updatePersonFields=fields,
            body=body,
        )
        return req.execute()

    def update_contact_photo(self, resource_name: str, image_path: str) -> Dict:
        if not resource_name or not image_path:
            return {}
        path = Path(image_path)
        if not path.exists():
            return {}
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                try:
                    resample = Image.Resampling.LANCZOS  # Pillow >=9.1
                except AttributeError:
                    resample = Image.LANCZOS
                img.thumbnail((720, 720), resample)
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=90)
            photo_bytes = base64.b64encode(buffer.getvalue()).decode("utf-8")
            req = self.service.people().updateContactPhoto(
                resourceName=resource_name,
                body={"photoBytes": photo_bytes},
            )
            return req.execute()
        except Exception:
            return {}

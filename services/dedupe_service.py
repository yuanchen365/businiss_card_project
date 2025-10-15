from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from slugify import slugify

from .phone_email_utils import normalize_phone, validate_email


def build_keys_from_schema(data: Dict) -> Dict[str, List[str]]:
    emails = [e.get("value", "").lower() for e in (data.get("emails") or []) if validate_email(e.get("value"))]
    phones = [normalize_phone(p.get("value", "")) for p in (data.get("phones") or [])]
    phones = [p for p in phones if p]
    name = (data.get("name") or {}).get("fullName") or ""
    company = (data.get("organization") or {}).get("company") or ""
    name_company = slugify(f"{name}-{company}", allow_unicode=True) if (name and company) else None
    return {
        "emails": sorted(set(emails)),
        "phones": sorted(set(phones)),
        "name_company": [name_company] if name_company else [],
    }


def build_keys_from_person(person: Dict) -> Dict[str, List[str]]:
    emails = [e.get("value", "").lower() for e in (person.get("emailAddresses") or []) if e.get("value")]
    phones = []
    for p in (person.get("phoneNumbers") or []):
        v = p.get("value")
        n = normalize_phone(v) if v else None
        if n:
            phones.append(n)
    name = None
    if person.get("names"):
        name = person["names"][0].get("displayName") or person["names"][0].get("givenName")
    company = None
    if person.get("organizations"):
        company = person["organizations"][0].get("name")
    name_company = slugify(f"{name}-{company}", allow_unicode=True) if (name and company) else None
    return {
        "emails": sorted(set(emails)),
        "phones": sorted(set(phones)),
        "name_company": [name_company] if name_company else [],
    }


def decide_action(candidate: Dict, existing_people: List[Dict]) -> Tuple[str, Optional[Dict], Dict]:
    """
    Return (action, matched_person, updates)
    action in {create, update, skip}
    """
    cand_keys = build_keys_from_schema(candidate)
    best_match = None
    match_score = -1
    best_keys = None
    for p in existing_people or []:
        keys = build_keys_from_person(p)
        score = 0
        if set(cand_keys["emails"]) & set(keys["emails"]):
            score += 3
        if set(cand_keys["phones"]) & set(keys["phones"]):
            score += 2
        if set(cand_keys["name_company"]) & set(keys["name_company"]):
            score += 1
        if score > match_score:
            match_score = score
            best_match = p
            best_keys = keys

    if not best_match or match_score <= 0:
        return ("create", None, {})

    cand_nc = set(cand_keys.get("name_company") or [])
    matched_nc = set((best_keys or {}).get("name_company") or [])
    if not cand_nc or not matched_nc or not (cand_nc & matched_nc):
        return ("create", None, {})

    # Compare fields to decide update vs skip
    updates: Dict = compute_updates(candidate, best_match)
    if updates:
        return ("update", best_match, updates)
    return ("skip", best_match, {})


def compute_updates(candidate: Dict, person: Dict) -> Dict:
    updates: Dict = {}
    # Name updates
    if candidate.get("name"):
        cand_full = (candidate["name"].get("fullName") or "").strip()
        existing = ""
        if person.get("names"):
            existing = (person["names"][0].get("displayName") or "").strip()
        if cand_full and cand_full != existing:
            updates.setdefault("names", []).append({
                "displayName": cand_full,
                "givenName": candidate["name"].get("givenName") or None,
                "familyName": candidate["name"].get("familyName") or None,
            })

    # Organization updates
    if candidate.get("organization"):
        cand_org = candidate["organization"]
        cand_company = (cand_org.get("company") or "").strip()
        cand_title = (cand_org.get("title") or "").strip()
        exist_company = exist_title = ""
        if person.get("organizations"):
            exist_company = (person["organizations"][0].get("name") or "").strip()
            exist_title = (person["organizations"][0].get("title") or "").strip()
        if cand_company and cand_company != exist_company or cand_title and cand_title != exist_title:
            updates.setdefault("organizations", []).append({
                "name": cand_company or None,
                "title": cand_title or None,
            })

    # Phones/Emails/URLs/Addresses: merge unique
    def _merge_unique(key_schema: str, key_person: str, type_key: str = "type", value_key: str = "value"):
        new_vals = []
        exist_vals = set()
        for it in person.get(key_person) or []:
            v = it.get(value_key)
            if v:
                exist_vals.add(v)
        for it in candidate.get(key_schema) or []:
            v = it.get(value_key)
            if v and v not in exist_vals:
                new_vals.append(it)
        if new_vals:
            updates[key_person] = (person.get(key_person) or []) + new_vals

    _merge_unique("phones", "phoneNumbers")
    _merge_unique("emails", "emailAddresses")
    _merge_unique("urls", "urls")
    _merge_unique("addresses", "addresses", value_key="formatted")

    # Notes: append
    note = (candidate.get("notes") or "").strip()
    if note:
        existing_notes = ""
        if person.get("biographies"):
            existing_notes = person["biographies"][0].get("value") or ""
        if note not in existing_notes:
            updates["biographies"] = [{"value": (existing_notes + "\n" + note).strip()}]

    return updates

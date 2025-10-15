from __future__ import annotations

import re
from typing import Optional, List

import phonenumbers
from email_validator import validate_email as _validate_email, EmailNotValidError


E164_PATTERN = re.compile(r"^\+\d{6,15}$")


def normalize_phone(value: str, default_region: str = "TW") -> Optional[str]:
    if not value:
        return None
    s = re.sub(r"[\s\-()\.]+", "", value)
    # Convert Taiwan mobile like 09xx... to +8869...
    if s.startswith("09") and default_region.upper() == "TW":
        s = "+886" + s[1:]
    try:
        if s.startswith("+"):
            num = phonenumbers.parse(s, None)
        else:
            num = phonenumbers.parse(s, default_region)
        if phonenumbers.is_valid_number(num):
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        # Fallback to E.164-looking strings even if not fully validated
        return s if E164_PATTERN.match(s) else None
    # If parsing succeeded but not a "valid" number, still accept E.164-looking input
    return s if E164_PATTERN.match(s) else None


def is_e164(phone: str) -> bool:
    return bool(phone and E164_PATTERN.match(phone))


def validate_email(email: str) -> Optional[str]:
    if not email:
        return None
    email = email.strip()
    try:
        info = _validate_email(email, allow_smtputf8=True, check_deliverability=False)
        # normalized field is recommended
        return (getattr(info, "normalized", None) or getattr(info, "email", None) or "").lower()
    except EmailNotValidError:
        return None


def dedupe_values(items: List[dict], key: str = "value") -> List[dict]:
    seen = set()
    out: List[dict] = []
    for it in items or []:
        val = (it or {}).get(key)
        if not val:
            continue
        if val not in seen:
            seen.add(val)
            out.append(it)
    return out

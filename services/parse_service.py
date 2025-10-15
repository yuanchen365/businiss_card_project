from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .phone_email_utils import normalize_phone, validate_email, dedupe_values


# Simple heuristics and regex for business card parsing
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{3,4}")
URL_RE = re.compile(r"https?://[\w.-]+(?:/[\w\-./?%&=]*)?")

COMPANY_HINTS = ["有限公司", "股份有限公司", "Inc", "LLC", "Co.", "Company", "股份", "科技", "資訊", "International", "Corp", "Corporation"]
TITLE_HINTS = [
    "執行長", "營運長", "技術長", "行銷長", "財務長", "董事長", "總經理", "副總", "經理", "副理", "主任",
    "Director", "VP", "CEO", "CTO", "COO", "CFO", "Manager", "Lead", "Head"
]


def parse_text_to_schema(text: str) -> Dict:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]

    emails = []
    phones = []
    urls = []
    addresses = []

    # Collect via regex
    for m in EMAIL_RE.finditer(text or ""):
        e = validate_email(m.group(0))
        if e:
            emails.append({"type": "work", "value": e})

    for m in PHONE_RE.finditer(text or ""):
        p = normalize_phone(m.group(0))
        if p:
            phones.append({"type": "mobile", "value": p})

    for m in URL_RE.finditer(text or ""):
        urls.append({"type": "work", "value": m.group(0)})

    # Guess name/company/title from first few lines
    name_parts = guess_name(lines)
    company, title = guess_company_title(lines)

    # Try to guess address: last long line with CJK or numbers and punctuation
    for ln in reversed(lines):
        if len(ln) > 10 and any(ch.isdigit() for ch in ln):
            addresses.append({"type": "work", "formatted": ln})
            break

    data = {
        "name": {
            "fullName": name_parts[0] or "",
            "givenName": name_parts[1] or "",
            "familyName": name_parts[2] or "",
        },
        "organization": {
            "company": company or "",
            "title": title or "",
        },
        "phones": dedupe_values(phones),
        "emails": dedupe_values(emails),
        "addresses": dedupe_values(addresses, key="formatted"),
        "urls": dedupe_values(urls),
        "notes": "",
    }
    return data


def guess_name(lines: List[str]) -> Tuple[str, str, str]:
    # Return (full, given, family)
    if not lines:
        return ("", "", "")
    # Heuristic: the shortest non-empty top line that contains no '@' and no URL
    candidates = [ln for ln in lines[:5] if '@' not in ln and not ln.lower().startswith('http')]
    if candidates:
        full = min(candidates, key=len)
        fam, giv = split_chinese_name(full)
        if fam or giv:
            return (full, giv, fam)
        # Fallback for English-like names
        parts = full.split()
        if len(parts) >= 2:
            return (full, parts[-1], " ".join(parts[:-1]))
        return (full, full, "")
    return ("", "", "")


def split_chinese_name(name: str) -> Tuple[str, str]:
    # Very naive split for CJK names: assume family is first char if length 2-3
    n = re.sub(r"\s+", "", name)
    if 2 <= len(n) <= 4 and all(_is_cjk(c) for c in n):
        return (n[0], n[1:])
    return ("", "")


def _is_cjk(ch: str) -> bool:
    return any([
        '\u4e00' <= ch <= '\u9fff',  # CJK Unified Ideographs
        '\u3400' <= ch <= '\u4dbf',  # CJK Extension A
    ])


def guess_company_title(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    company = None
    title = None
    for ln in lines[:8]:
        if any(h in ln for h in TITLE_HINTS) and not title:
            title = ln
        if any(h in ln for h in COMPANY_HINTS) and not company:
            company = ln
        if company and title:
            break
    return company, title


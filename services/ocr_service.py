from __future__ import annotations

import base64
import io
import os
from typing import Optional

import requests
from PIL import Image


def _read_image_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def extract_text(image_path: str) -> str:
    api_key = os.getenv("VISION_API_KEY")
    if api_key:
        txt = _extract_with_vision(image_path, api_key)
        if txt:
            return txt
    fallback = (os.getenv("OCR_FALLBACK") or "tesseract").lower()
    if fallback == "tesseract":
        try:
            import pytesseract
        except Exception:
            return ""
        try:
            img = Image.open(image_path)
            return pytesseract.image_to_string(img)
        except Exception:
            return ""
    return ""


def _extract_with_vision(image_path: str, api_key: str) -> Optional[str]:
    try:
        img_b64 = base64.b64encode(_read_image_bytes(image_path)).decode("utf-8")
        url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
        payload = {
            "requests": [
                {
                    "image": {"content": img_b64},
                    "features": [{"type": "TEXT_DETECTION"}],
                }
            ]
        }
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        ann = (data.get("responses") or [{}])[0].get("fullTextAnnotation")
        if ann and ann.get("text"):
            return ann["text"]
    except Exception:
        return None
    return None


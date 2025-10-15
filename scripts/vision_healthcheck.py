import os
import base64
from io import BytesIO
import json

import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv


def make_test_image_bytes() -> bytes:
    img = Image.new("RGB", (360, 120), color="white")
    drw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    drw.text((10, 40), "HELLO 123", fill="black", font=font)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main():
    load_dotenv()
    api_key = os.getenv("VISION_API_KEY")
    if not api_key:
        print("VISION_API_KEY is missing in environment")
        raise SystemExit(2)

    img_b64 = base64.b64encode(make_test_image_bytes()).decode("utf-8")
    url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
    payload = {
        "requests": [
            {
                "image": {"content": img_b64},
                "features": [{"type": "TEXT_DETECTION"}],
            }
        ]
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        print("HTTP status:", resp.status_code)
        data = resp.json()
        if resp.status_code != 200:
            print("Error payload:", json.dumps(data, ensure_ascii=False)[:800])
            raise SystemExit(1)
        first = (data.get("responses") or [{}])[0]
        if "error" in first:
            print("API error:", first["error"]) 
            raise SystemExit(1)
        text = (first.get("fullTextAnnotation") or {}).get("text")
        print("Detected text:", repr((text or "").strip()))
        print("Vision healthcheck: OK")
    except Exception as e:
        print("Vision healthcheck failed:", e)
        raise


if __name__ == "__main__":
    main()


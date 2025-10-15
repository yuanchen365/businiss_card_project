from io import BytesIO

from starlette.testclient import TestClient
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from main import app


def make_png_bytes():
    try:
        from PIL import Image
    except Exception:
        return b"PNG"
    img = Image.new("RGB", (10, 10), color=(200, 200, 200))
    bio = BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def run():
    client = TestClient(app)

    r = client.get("/")
    print("GET / ->", r.status_code)

    r = client.get("/auth/login", allow_redirects=False)
    print("GET /auth/login ->", r.status_code, r.headers.get("location", ""))

    files = [("files", ("card.png", make_png_bytes(), "image/png"))]
    r = client.post("/upload", files=files, allow_redirects=False)
    print("POST /upload ->", r.status_code, r.headers.get("location"))


if __name__ == "__main__":
    run()

import os
from dotenv import load_dotenv


def mask(val: str, keep: int = 4) -> str:
    if not val:
        return "<missing>"
    if len(val) <= keep * 2:
        return val[0:2] + "***" + val[-2:]
    return val[:keep] + "***" + val[-keep:]


def main():
    load_dotenv()
    keys = [
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "GOOGLE_SCOPES",
        "VISION_API_KEY",
        "OCR_FALLBACK",
        "OAUTHLIB_INSECURE_TRANSPORT",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_CREDITS",
        "STRIPE_PRICE_CREDITS_1",
        "STRIPE_PRICE_CREDITS_2",
        "CREDIT_PACK_TIERS",
        "CREDIT_PACK_PRICE",
    ]
    print("Loaded env (masked):")
    for k in keys:
        v = os.getenv(k)
        if k in {"GOOGLE_CLIENT_SECRET", "VISION_API_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"}:
            print(f"- {k} = {mask(v or '')}")
        else:
            print(f"- {k} = {v}")


if __name__ == "__main__":
    main()

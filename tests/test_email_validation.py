from services.phone_email_utils import validate_email


def test_validate_email_lowercased():
    assert validate_email("Dm.Wang@Example.com") == "dm.wang@example.com"


def test_validate_email_invalid():
    assert validate_email("bad@@example..com") is None


from services.phone_email_utils import normalize_phone, is_e164


def test_taiwan_mobile_to_e164():
    assert normalize_phone("0912-345-678") == "+886912345678"


def test_international_e164_pass_through():
    num = "+886-912-345-678"
    assert normalize_phone(num) == "+886912345678"
    assert is_e164("+886912345678")


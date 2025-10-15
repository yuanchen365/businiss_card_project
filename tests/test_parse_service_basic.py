from services.parse_service import parse_text_to_schema


def test_parse_basic_fields():
    text = """
    王大明 營運長
    能量叢林股份有限公司
    Mobile: 0912-345-678
    Email: dm.wang@example.com
    https://example.com
    台北市大安區仁愛路三段 100 號
    """
    data = parse_text_to_schema(text)
    assert data["organization"]["company"].startswith("能量叢林")
    assert any(e["value"] == "dm.wang@example.com" for e in data["emails"])
    assert any(p["value"].startswith("+886") for p in data["phones"])
    assert data["urls"][0]["value"].startswith("https://")
    assert data["addresses"][0]["formatted"].startswith("台北市")


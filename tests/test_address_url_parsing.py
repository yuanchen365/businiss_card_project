from services.parse_service import parse_text_to_schema


def test_address_url_parsing():
    text = "Visit us at https://example.com\n地址：台北市信義區松高路 11 號"
    data = parse_text_to_schema(text)
    assert any(u["value"].startswith("https://") for u in data["urls"]) 
    assert any("台北市" in a["formatted"] for a in data["addresses"]) 


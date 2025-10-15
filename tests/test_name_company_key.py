from services.dedupe_service import build_keys_from_schema


def test_name_company_slug_key():
    cand = {"name": {"fullName": "王大明"}, "organization": {"company": "能量叢林"}}
    keys = build_keys_from_schema(cand)
    assert keys["name_company"] and keys["name_company"][0].startswith("wang-da-ming") is False  # Chinese kept slugged
    assert len(keys["name_company"][0]) > 0


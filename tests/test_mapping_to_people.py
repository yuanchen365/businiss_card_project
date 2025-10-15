from services.people_service import unify_schema_to_people_body, fields_from_body


def test_unify_mapping_and_fields():
    data = {
        "name": {"fullName": "王大明", "givenName": "大明", "familyName": "王"},
        "organization": {"company": "能量叢林", "title": "營運長"},
        "phones": [{"type": "mobile", "value": "+886912345678"}],
        "emails": [{"type": "work", "value": "dm.wang@example.com"}],
        "addresses": [{"type": "work", "formatted": "台北市"}],
        "urls": [{"type": "work", "value": "https://example.com"}],
        "notes": "note"
    }
    body = unify_schema_to_people_body(data)
    assert body["names"][0]["displayName"] == "王大明"
    assert body["organizations"][0]["name"] == "能量叢林"
    fields = fields_from_body(body)
    assert "names" in fields and "emailAddresses" in fields and "biographies" in fields


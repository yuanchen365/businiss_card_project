from services.dedupe_service import build_keys_from_schema, build_keys_from_person, decide_action


def test_build_keys_from_schema():
    cand = {
        "name": {"fullName": "王大明"},
        "organization": {"company": "能量叢林"},
        "emails": [{"value": "a@b.com"}],
        "phones": [{"value": "+886912345678"}],
    }
    keys = build_keys_from_schema(cand)
    assert keys["emails"] == ["a@b.com"]
    assert keys["phones"] == ["+886912345678"]
    assert keys["name_company"]


def test_decide_action_create_when_no_match():
    cand = {
        "name": {"fullName": "張三"},
        "organization": {"company": "ACME"},
        "emails": [{"value": "c@d.com"}],
        "phones": [{"value": "+11234567890"}],
    }
    action, matched, updates = decide_action(cand, [])
    assert action == "create"
    assert matched is None


def test_decide_action_update_when_phone_matches():
    existing = [{
        "resourceName": "people/c123",
        "phoneNumbers": [{"value": "+11234567890"}],
        "names": [{"displayName": "John"}],
        "organizations": [{"name": "New Co."}],
    }]
    cand = {
        "name": {"fullName": "John"},
        "organization": {"company": "New Co."},
        "phones": [{"value": "+11234567890"}],
        "emails": [],
    }
    action, matched, updates = decide_action(cand, existing)
    assert action in ("skip", "update")
    assert matched is not None


def test_decide_action_create_when_name_company_diff():
    existing = [{
        "resourceName": "people/c456",
        "emailAddresses": [{"value": "shared@corp.com"}],
        "names": [{"displayName": "Alice"}],
        "organizations": [{"name": "Same Corp"}],
    }]
    cand = {
        "name": {"fullName": "Bob"},
        "organization": {"company": "Other Corp"},
        "emails": [{"value": "shared@corp.com"}],
        "phones": [],
    }
    action, matched, updates = decide_action(cand, existing)
    assert action == "create"
    assert matched is None

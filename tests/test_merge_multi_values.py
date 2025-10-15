from services.dedupe_service import compute_updates


def test_merge_multi_values_adds_new_only():
    cand = {"phones": [{"value": "+1123"}, {"value": "+4455"}], "emails": [{"value": "a@b.com"}]}
    person = {"phoneNumbers": [{"value": "+1123"}], "emailAddresses": []}
    updates = compute_updates(cand, person)
    assert "+4455" in [p["value"] for p in updates.get("phoneNumbers", [])]
    assert "a@b.com" in [e["value"] for e in updates.get("emailAddresses", [])]


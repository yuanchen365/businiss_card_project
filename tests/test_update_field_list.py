from services.people_service import fields_from_body


def test_fields_sorted_and_joined():
    body = {"emailAddresses": [{"value": "a@b.com"}], "names": [{"displayName": "A"}]}
    fields = fields_from_body(body)
    # alphabetically sorted by our function
    assert fields == "emailAddresses,names"


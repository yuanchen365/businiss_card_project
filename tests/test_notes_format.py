from datetime import datetime
from services.people_service import unify_schema_to_people_body


def test_notes_to_biography():
    note = f"名片掃描於 {datetime.now().strftime('%Y-%m-%d')}，來源：上傳"
    data = {"notes": note}
    body = unify_schema_to_people_body(data)
    assert body["biographies"][0]["value"].startswith("名片掃描於 ")


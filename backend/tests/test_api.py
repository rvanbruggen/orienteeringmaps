from tests.conftest import make_pdf, make_png


def upload(client, name, data):
    r = client.post("/api/files", files=[("files", (name, data))])
    assert r.status_code == 200, r.text
    return r.json()[0]


def test_upload_create_map_and_history(client):
    pdf = make_pdf("Schaal 1/5.000 Hoogtelijnen 2m", pages=2)
    res = upload(client, "HITTA-Routes-OV-Leuven-Kort.pdf", pdf)
    assert res["status"] == "created"
    f = res["file"]
    assert f["page_count"] == 2 and len(f["pages"]) == 2
    assert f["suggestions"]["scale"] == 5000
    assert client.get(f["pages"][0]["image_url"]).status_code == 200
    assert client.get(f["original_url"]).headers["content-type"] == "application/pdf"

    # Same bytes again -> duplicate
    again = upload(client, "copy.pdf", pdf)
    assert again["status"] == "duplicate" and again["file"]["id"] == f["id"]

    club = client.post("/api/clubs", json={"name": "OMEGA"}).json()
    r = client.post("/api/maps", json={
        "name": "Leuven Arenbergpark", "location": "Leuven", "club_id": club["id"], "tags": ["HITTA"],
        "version": {"scale": 5000, "contour_interval": 2, "survey_date": "2021-05"},
        "file_ids": [f["id"]],
        "event": {"name": "HITTA Leuven", "event_type": "permanent", "date": "2022"},
        "courses": [{"name": "Kort", "file_id": f["id"], "page_no": 2, "length_km": 2}],
    })
    assert r.status_code == 201, r.text
    mp = r.json()
    assert mp["last_survey"] == "2021-05" and mp["last_event"] == "2022"
    assert mp["course_count"] == 1 and mp["file_count"] == 1
    v1 = mp["versions"][0]

    # Second, newer version with its own event
    v2 = client.post(f"/api/maps/{mp['id']}/versions", json={"survey_date": "2024-03", "scale": 4000}).json()
    client.post(f"/api/versions/{v2['id']}/events", json={"name": "Club training", "date": "2024-10-01"})
    summary = next(x for x in client.get("/api/maps").json() if x["id"] == mp["id"])
    assert summary["scale"] == 4000 and summary["last_survey"] == "2024-03"
    assert summary["last_event"] == "2024-10-01" and summary["version_count"] == 2
    assert summary["club_name"] == "OMEGA"

    # Invalid partial date is rejected
    assert client.patch(f"/api/versions/{v1['id']}", json={"survey_date": "May 2021"}).status_code == 422

    # Deleting the map returns its files to the inbox
    assert client.delete(f"/api/maps/{mp['id']}").status_code == 204
    inbox = client.get("/api/files?unassigned=true").json()
    assert f["id"] in [x["id"] for x in inbox]


def test_image_upload_and_similarity(client):
    a = upload(client, "map.png", make_png())
    b = upload(client, "map-copy.jpg", make_png(size=(600, 400)))
    assert a["status"] == "created" and a["file"]["format"] == "png"
    assert b["status"] == "created" and b["file"]["format"] == "jpg"
    assert any(s["file_id"] == a["file"]["id"] for s in b["similar"])


def test_courses_from_pages_and_delete_file(client):
    f = upload(client, "multi.pdf", make_pdf("Alle Posten", pages=3))["file"]
    mp = client.post("/api/maps", json={"name": "Multi", "file_ids": [f["id"]]}).json()
    v = mp["versions"][0]
    ev = client.post(f"/api/versions/{v['id']}/events", json={"name": "Parcours"}).json()
    courses = client.post(f"/api/events/{ev['id']}/courses/from-file", json={"file_id": f["id"]}).json()
    assert [c["page_no"] for c in courses] == [1, 2, 3]
    assert courses[0]["thumb_url"]
    assert client.delete(f"/api/files/{f['id']}").status_code == 204
    detail = client.get(f"/api/maps/{mp['id']}").json()
    assert detail["file_count"] == 0
    assert detail["versions"][0]["events"][0]["courses"][0]["file_id"] is None


def test_unsupported_and_export(client):
    r = client.post("/api/files", files=[("files", ("notes.txt", b"hello"))]).json()[0]
    assert r["status"] == "error"
    upload(client, "a.png", make_png())
    resp = client.get("/api/export")
    assert resp.status_code == 200 and resp.content[:2] == b"PK"
    assert client.get("/api/meta").json()["counts"]["inbox"] == 1

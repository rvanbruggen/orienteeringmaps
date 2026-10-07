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


def test_georeference_page(client):
    from tests.test_georef import synth
    f = upload(client, "map.pdf", make_pdf("Schaal 1/5.000", pages=2))["file"]
    mp = client.post("/api/maps", json={"name": "Placed", "file_ids": [f["id"]],
                                        "version": {"scale": 5000}}).json()
    page = f["pages"][0]
    ctx = client.get(f"/api/pages/{page['id']}/georef").json()
    assert ctx["georef"] is None and ctx["stated_scale"] == 5000 and ctx["page"]["dpi"]
    assert [p["id"] for p in ctx["same_layout_pages"]] == [f["pages"][1]["id"]]

    w, h = page["width"], page["height"]
    pts = synth([(50, 60), (w - 40, 80), (w - 60, h - 50), (70, h - 90)])
    fit = client.post("/api/georef/fit", json={"width": w, "height": h, "dpi": ctx["page"]["dpi"], "points": pts[:2]}).json()
    assert fit["method"] == "similarity"
    bad = client.post("/api/georef/fit", json={"width": w, "height": h, "points": pts[:1]})
    assert bad.status_code == 422

    clip = [[0, 0], [w, 0], [w, h / 2]]
    saved = client.put(f"/api/pages/{page['id']}/georef", json={
        "points": pts, "clip": clip, "also_page_ids": [f["pages"][1]["id"]]}).json()
    assert saved["georef"]["method"] == "affine" and saved["georef"]["rms_m"] < 0.5
    assert saved["georef"]["clip"] == clip

    detail = client.get(f"/api/maps/{mp['id']}").json()
    assert detail["placed_count"] == 2 and detail["lat"] is not None
    pages = detail["versions"][0]["files"][0]["pages"]
    assert all(p["georef"]["point_count"] == 4 for p in pages)

    assert client.delete(f"/api/pages/{page['id']}/georef").status_code == 204
    assert client.get(f"/api/maps/{mp['id']}").json()["placed_count"] == 1


def test_exports_and_events(client):
    import io
    import zipfile
    from tests.test_georef import synth
    f = upload(client, "map.pdf", make_pdf("Schaal 1/5.000"))["file"]
    mp = client.post("/api/maps", json={"name": "Kmz Test", "file_ids": [f["id"]],
                                        "event": {"name": "Race", "date": "2024-05-01"},
                                        "courses": [{"name": "A"}]}).json()
    client.post("/api/maps", json={"name": "Pin only", "lat": 51.0, "lon": 4.5})
    assert client.get(f"/api/maps/{mp['id']}/kmz").status_code == 404

    page = f["pages"][0]
    w, h = page["width"], page["height"]
    pts = synth([(50, 60), (w - 40, 80), (w - 60, h - 50)])
    client.put(f"/api/pages/{page['id']}/georef", json={"points": pts, "clip": [[0, 0], [w, 0], [w, h / 2]]})

    summary = next(m for m in client.get("/api/maps").json() if m["id"] == mp["id"])
    assert len(summary["footprint"]) == 3 and summary["overlay"]["page_id"] == page["id"]

    r = client.get(f"/api/maps/{mp['id']}/kmz")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    doc = z.read("doc.kml").decode()
    assert "gx:LatLonQuad" in doc and "Kmz Test" in doc
    assert any(n.endswith(".png") for n in z.namelist())  # clipped -> transparent PNG

    allz = zipfile.ZipFile(io.BytesIO(client.get("/api/export/kmz").content)).read("doc.kml").decode()
    assert "Pin only" in allz and "Kmz Test" in allz

    gj = client.get("/api/export/geojson").json()
    kinds = {feat["properties"]["name"]: feat["geometry"]["type"] for feat in gj["features"]}
    assert kinds == {"Kmz Test": "Polygon", "Pin only": "Point"}

    events = client.get("/api/events").json()
    assert events[0]["name"] == "Race" and events[0]["map_name"] == "Kmz Test" and events[0]["course_names"] == ["A"]


def test_bulk_update_maps(client):
    club = client.post("/api/clubs", json={"name": "TROL"}).json()
    a = client.post("/api/maps", json={"name": "A", "tags": ["HITTA", "old"], "map_type": "park"}).json()
    b = client.post("/api/maps", json={"name": "B", "tags": ["old"], "needs_review": True}).json()
    c = client.post("/api/maps", json={"name": "C", "map_type": "forest"}).json()
    r = client.post("/api/maps/bulk", json={
        "ids": [a["id"], b["id"]], "club_id": club["id"], "publish_level": "overlay", "needs_review": False,
        "add_tags": ["Gent", "HITTA"], "remove_tags": ["old"]})
    assert r.status_code == 200 and r.json() == {"updated": 2}
    maps = {x["name"]: x for x in client.get("/api/maps").json()}
    assert maps["A"]["tags"] == ["HITTA", "Gent"] and maps["B"]["tags"] == ["Gent", "HITTA"]
    assert maps["A"]["club_name"] == maps["B"]["club_name"] == "TROL" and maps["C"]["club_name"] is None
    assert maps["A"]["publish_level"] == "overlay" and maps["C"]["publish_level"] == "private"
    assert not maps["B"]["needs_review"]
    assert maps["A"]["map_type"] == "park"  # not sent, so unchanged

    # Explicit null clears; missing maps and bad values are rejected.
    client.post("/api/maps/bulk", json={"ids": [a["id"]], "club_id": None, "map_type": None})
    maps = {x["name"]: x for x in client.get("/api/maps").json()}
    assert maps["A"]["club_name"] is None and maps["A"]["map_type"] is None
    assert client.post("/api/maps/bulk", json={"ids": [a["id"], 9999], "map_type": "park"}).status_code == 404
    assert client.post("/api/maps/bulk", json={"ids": [a["id"]], "publish_level": None}).status_code == 422
    assert client.post("/api/maps/bulk", json={"ids": [], "map_type": "park"}).status_code == 422
    assert client.post("/api/maps/bulk", json={"ids": [c["id"]], "club_id": 9999}).status_code == 404


def test_missing_media_is_not_cached(client):
    r = client.get("/media/00/nope/p1.webp")
    assert r.status_code == 404 and "immutable" not in r.headers.get("cache-control", "")

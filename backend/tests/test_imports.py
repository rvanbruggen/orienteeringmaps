"""Import tasks: upload a batch, process it in the background, match scans to runs by date, review."""
from pathlib import Path

from tests.conftest import make_pdf
from tests.test_strava import _activity, _connect, _encode, _placed_map, fake  # noqa: F401 - fixture


def _process():
    from app import db, imports
    return imports.process_all(db.SessionLocal)


def _upload(client, task_id, names):
    files = [("files", (n, make_pdf(n) if n.endswith(".pdf") else b"hello", "application/octet-stream")) for n in names]
    r = client.post(f"/api/imports/{task_id}/files", files=files)
    assert r.status_code == 200, r.text
    return r.json()


def _by_name(task):
    return {i["original_name"]: i for i in task["items"]}


def test_day_from_name():
    from app.imports import day_from_name
    assert day_from_name("20190413 Grobbendonk.pdf") == "2019-04-13"
    assert day_from_name("20190413-Kort.pdf") == "2019-04-13"
    assert day_from_name("dir/20190413_x.pdf") == "2019-04-13"
    assert day_from_name("20191313 bad month.pdf") is None
    assert day_from_name("201904131 too long.pdf") is None
    assert day_from_name("Grobbendonk 20190413.pdf") is None


def test_import_matches_scans_to_runs(client, fake):
    mp, route = _placed_map(client)
    fake.activities = [
        _activity(1, "Orienteering Leuven", day=19, map={"summary_polyline": _encode(route)}),
        _activity(2, "Orienteering race, morning", day=20),
        _activity(3, "Orienteering race, afternoon", day=20),
        _activity(6, "Bike to the race", "Ride", day=20),
        _activity(4, "Orienteering in the woods", day=21),  # far from any map
        _activity(5, "Sprint orienteering in Lier", day=22),
    ]
    _connect(client)
    client.post("/api/strava/sync", json={})
    # One run is linked already, to a map of its own.
    lier = client.put("/api/strava/activities/1005/link", json={
        "new_map": {"name": "Lier centrum"}, "new_event": {"name": "Sprint Lier"}}).json()["link"]

    task = client.post("/api/imports", json={"name": "Archive"}).json()
    assert task["name"] == "Archive" and task["match_by_date"] and task["total"] == 0
    up = _upload(client, task["id"], ["20260919 Arenberg.pdf", "20260920 Race.pdf", "20260921 Bos.pdf",
                                      "20260922 Lier.pdf", "Undated scan.pdf", "20260925 Nothing.pdf", "notes.txt"])
    assert [u["status"] for u in up] == ["queued"] * 6 + ["error"]
    t = client.get(f"/api/imports/{task['id']}").json()
    assert t["state"] == "processing" and t["groups"]["waiting"] == 6 and t["processed"] == 1

    assert _process() == 6
    t = client.get(f"/api/imports/{task['id']}").json()
    items = _by_name(t)
    assert t["state"] == "review" and t["processed"] == 7

    # The route lies on the placed map: linked to its open permanent course, the scan went with it.
    a = items["20260919 Arenberg.pdf"]
    assert a["outcome"] == "auto_linked" and a["group"] == "check" and a["day"] == "2026-09-19"
    assert a["file"]["map_id"] == mp["id"] and a["activity"]["link"]["event_name"] == "HITTA Leuven"
    assert "Arenbergpark" in a["note"]
    # Two orienteering runs that day (the ride doesn't count): you choose.
    r = items["20260920 Race.pdf"]
    assert r["outcome"] == "several" and r["group"] == "choose" and {c["id"] for c in r["candidates"]} == {1002, 1003}
    # One run, but no placed map under it: you link it.
    b = items["20260921 Bos.pdf"]
    assert b["outcome"] == "one" and b["group"] == "link" and b["activity"]["id"] == 1004 and b["file"]["map_id"] is None
    assert b["file"]["suggestions"]["strava_activity_id"] == 1004
    # Run linked already: the scan is on that map, nothing to review.
    li = items["20260922 Lier.pdf"]
    assert li["outcome"] == "linked" and li["group"] == "done" and li["file"]["map_id"] == lier["map_id"]
    assert items["Undated scan.pdf"]["outcome"] == "no_date" and items["Undated scan.pdf"]["group"] == "file"
    assert items["20260925 Nothing.pdf"]["outcome"] == "no_run" and items["20260925 Nothing.pdf"]["group"] == "file"
    assert items["notes.txt"]["group"] == "error" and not items["notes.txt"]["can_retry"]
    assert client.get("/api/meta").json()["counts"]["imports"] == 6  # all but the one that is done

    # Choosing the run of the race scan.
    t = client.put(f"/api/imports/items/{r['id']}/run", json={"activity_id": 1003}).json()
    assert _by_name(t)["20260920 Race.pdf"]["group"] == "link"
    # Runs near a date, to choose one by hand for a scan without a match.
    near = client.get(f"/api/imports/items/{items['Undated scan.pdf']['id']}/runs", params={"around": "2026-09-21"}).json()
    assert {x["id"] for x in near} == {1001, 1002, 1003, 1004, 1005}

    # Linking the run in the link dialog takes its scan along onto the map.
    link = client.put("/api/strava/activities/1004/link", json={
        "new_map": {"name": "Bos"}, "new_event": {"name": "Bosloop"}}).json()["link"]
    t = client.get(f"/api/imports/{task['id']}").json()
    b = _by_name(t)["20260921 Bos.pdf"]
    assert b["group"] == "check" and b["file"]["map_id"] == link["map_id"]
    t = client.put(f"/api/imports/items/{b['id']}/review", json={"review": "confirmed"}).json()
    assert _by_name(t)["20260921 Bos.pdf"]["group"] == "done"
    t = client.put(f"/api/imports/items/{items['20260925 Nothing.pdf']['id']}/review", json={"review": "set_aside"}).json()
    assert _by_name(t)["20260925 Nothing.pdf"]["group"] == "aside"

    # Taking the run off a scan puts it back to "file by hand".
    t = client.put(f"/api/imports/items/{r['id']}/run", json={"activity_id": None}).json()
    r = _by_name(t)["20260920 Race.pdf"]
    assert r["group"] == "file" and r["outcome"] == "no_run" and "strava_activity_id" not in r["file"]["suggestions"]

    # The list shows a summary per task; deleting the task keeps the files in the library.
    (summary,) = client.get("/api/imports").json()
    assert summary["groups"]["done"] == 2 and summary["groups"]["aside"] == 1
    n_files = client.get("/api/meta").json()["counts"]["files"]
    assert client.delete(f"/api/imports/{task['id']}").status_code == 204
    assert client.get("/api/imports").json() == []
    assert client.get("/api/meta").json()["counts"]["files"] == n_files


def test_auto_link_uses_the_days_event_or_the_opunch_race(client, fake):
    from app import db, models as m
    mp, route = _placed_map(client)
    version_id = mp["versions"][0]["id"]
    client.post(f"/api/versions/{version_id}/events", json={"name": "Club race", "date": "2026-09-19"})
    with db.SessionLocal() as s:
        s.add(m.OpunchEvent(id=4242, name="Regional Arenberg", date="2026-09-20", url="https://example/4242"))
        s.commit()
    fake.activities = [_activity(1, "Orienteering", day=19, map={"summary_polyline": _encode(route)}),
                       _activity(2, "Orienteering", day=20, map={"summary_polyline": _encode(route)})]
    _connect(client)
    client.post("/api/strava/sync", json={})
    task = client.post("/api/imports", json={}).json()
    assert task["name"].startswith("Import ")
    _upload(client, task["id"], ["20260919 a.pdf", "20260920 b.pdf"])
    _process()
    items = _by_name(client.get(f"/api/imports/{task['id']}").json())
    assert items["20260919 a.pdf"]["activity"]["link"]["event_name"] == "Club race"
    b = items["20260920 b.pdf"]["activity"]["link"]
    assert b["event_name"] == "Regional Arenberg"
    ev = next(e for v in client.get(f"/api/maps/{mp['id']}").json()["versions"] for e in v["events"] if e["id"] == b["event_id"])
    assert ev["opunch_id"] == 4242 and ev["date"] == "2026-09-20"


def test_import_without_date_matching_and_duplicates(client):
    pdf = make_pdf("same scan")
    task = client.post("/api/imports", json={"name": "Plain", "match_by_date": False}).json()
    client.post(f"/api/imports/{task['id']}/files", files=[("files", ("20260919 a.pdf", pdf, "application/pdf"))])
    _process()
    task2 = client.post("/api/imports", json={"name": "Again"}).json()
    client.post(f"/api/imports/{task2['id']}/files", files=[("files", ("20260919 a.pdf", pdf, "application/pdf"))])
    _process()
    (a,) = client.get(f"/api/imports/{task['id']}").json()["items"]
    assert a["status"] == "done" and a["outcome"] is None and a["group"] == "file"
    (b,) = client.get(f"/api/imports/{task2['id']}").json()["items"]
    assert b["status"] == "duplicate" and b["file"]["id"] == a["file"]["id"] and b["outcome"] == "no_run"


def test_import_from_server_folder(client):
    from app import config
    root = Path(config.IMPORT_DIR)
    (root / "archive" / "2005").mkdir(parents=True)
    (root / "archive" / "2005" / "20050403 Kalmthout.pdf").write_bytes(make_pdf("Kalmthout"))
    (root / "archive" / "20060101 Zoersel.pdf").write_bytes(make_pdf("Zoersel"))
    (root / "archive" / "readme.txt").write_text("not a map")
    folders = client.get("/api/imports/folders").json()["folders"]
    assert {"path": "archive", "files": 2} in folders and {"path": "archive/2005", "files": 1} in folders

    task = client.post("/api/imports", json={"name": "Archive"}).json()
    assert client.post(f"/api/imports/{task['id']}/folder", json={"path": "../.."}).status_code == 422
    assert client.post(f"/api/imports/{task['id']}/folder", json={"path": "archive"}).json() == {"added": 2}
    assert client.post(f"/api/imports/{task['id']}/folder", json={"path": "archive"}).json() == {"added": 0}
    _process()
    t = client.get(f"/api/imports/{task['id']}").json()
    assert [i["status"] for i in t["items"]] == ["done", "done"]
    # Files in the import folder are read in place, never removed.
    assert (root / "archive" / "2005" / "20050403 Kalmthout.pdf").exists()


def test_staged_files_are_removed(client):
    from app import config
    task = client.post("/api/imports", json={"name": "x"}).json()
    _upload(client, task["id"], ["20260919 a.pdf", "20260920 b.pdf"])
    staged = list((Path(config.STAGING_DIR) / str(task["id"])).iterdir())
    assert len(staged) == 2
    first = client.get(f"/api/imports/{task['id']}").json()["items"][0]
    assert client.delete(f"/api/imports/items/{first['id']}").status_code == 204  # still waiting: copy removed
    assert len(list((Path(config.STAGING_DIR) / str(task["id"])).iterdir())) == 1
    _process()
    assert list((Path(config.STAGING_DIR) / str(task["id"])).iterdir()) == []


def test_interrupted_processing_restarts(client, monkeypatch):
    """A file that was processing when the app stopped is processed again by the worker."""
    import time
    from app import config, db, imports, models as m
    task = client.post("/api/imports", json={"name": "x"}).json()
    _upload(client, task["id"], ["20260919 a.pdf"])
    with db.SessionLocal() as s:
        s.query(m.ImportItem).one().status = "processing"
        s.commit()
    monkeypatch.setattr(config, "IMPORT_WORKER", True)
    imports.start_worker(db.SessionLocal)
    for _ in range(100):
        if client.get(f"/api/imports/{task['id']}").json()["state"] != "processing":
            break
        time.sleep(0.1)
    (item,) = client.get(f"/api/imports/{task['id']}").json()["items"]
    assert item["status"] == "done"

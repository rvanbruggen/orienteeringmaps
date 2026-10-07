import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


def _activity(i, name="Morning Run", sport="Run", day=1, **kw):
    return {
        "id": 1000 + i, "name": name, "sport_type": sport, "type": sport,
        "start_date": f"2026-09-{day:02d}T08:00:00Z", "start_date_local": f"2026-09-{day:02d}T10:00:00Z",
        "distance": 5000.0, "moving_time": 1800, "elapsed_time": 1900, "total_elevation_gain": 12.0,
        "workout_type": None, "commute": False, "private": False,
        "start_latlng": [51.05, 3.72], "map": {"summary_polyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"}, **kw,
    }


class FakeStrava:
    """Stands in for www.strava.com: OAuth endpoints and the activity list."""

    def __init__(self, activities):
        self.activities = activities
        self.calls = []
        self.refreshes = 0
        self.deauthorized = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path == "/oauth/token":
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["refresh_token"]:
                self.refreshes += 1
            return httpx.Response(200, json={
                "access_token": f"access-{len(self.calls)}", "refresh_token": "refresh-1",
                "expires_at": int(time.time()) + 6 * 3600,
                "athlete": {"id": 7, "firstname": "Rik", "lastname": "Van Bruggen"},
            })
        if path == "/oauth/deauthorize":
            self.deauthorized = True
            return httpx.Response(200, json={})
        if path == "/api/v3/athlete/activities":
            assert request.headers["authorization"].startswith("Bearer access-")
            page, per = int(request.url.params["page"]), int(request.url.params["per_page"])
            after = int(request.url.params.get("after", 0))
            items = [a for a in self.activities
                     if int(time.mktime(time.strptime(a["start_date"], "%Y-%m-%dT%H:%M:%SZ"))) > after - 86400 * 2]
            return httpx.Response(200, json=items[(page - 1) * per: page * per])
        return httpx.Response(404)


@pytest.fixture()
def fake(client, monkeypatch):
    from app import config, strava
    monkeypatch.setattr(config, "STRAVA_CLIENT_ID", "123")
    monkeypatch.setattr(config, "STRAVA_CLIENT_SECRET", "s3cret")
    f = FakeStrava([
        _activity(1, "Ghent Orienteering Series - Centrum", day=19),
        _activity(2, "To the start of the BK orienteering", "Walk", day=20, commute=True),
        _activity(3, "BK Long Orienteering - Bois de Wéris", "TrailRun", day=20, workout_type=1),
        _activity(4, "Gravel voor de Koers", "Ride", day=21),
        _activity(5, "HITTA Leuven Kort", "Run", day=22),
    ])
    monkeypatch.setattr(strava, "_client", lambda: httpx.Client(transport=httpx.MockTransport(f)))
    return f


def _connect(client):
    r = client.get("/api/strava/connect", follow_redirects=False)
    assert r.status_code == 302
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "www.strava.com" and q["scope"] == ["read,activity:read_all"]
    assert q["redirect_uri"][0].endswith("/api/strava/callback")
    r = client.get("/api/strava/callback", params={"code": "abc", "state": q["state"][0],
                                                    "scope": "read,activity:read_all"}, follow_redirects=False)
    assert r.headers["location"] == "/#/runs?connected=1"


def test_not_configured(client):
    st = client.get("/api/strava/status").json()
    assert st["configured"] is False and st["connected"] is False
    r = client.get("/api/strava/connect", follow_redirects=False)
    assert r.headers["location"].startswith("/#/runs?error=")


def test_connect_sync_and_classify(client, fake):
    _connect(client)
    st = client.get("/api/strava/status").json()
    assert st["connected"] and st["athlete"]["name"] == "Rik Van Bruggen" and st["private_activities"]
    # Tokens never leave the server.
    assert "refresh" not in json.dumps(st) and "access-" not in json.dumps(st)

    r = client.post("/api/strava/sync", json={}).json()
    assert r == {"added": 5, "updated": 0, "next": None}
    names = {a["name"]: a for a in client.get("/api/strava/activities").json()}
    assert set(names) == {"Ghent Orienteering Series - Centrum", "BK Long Orienteering - Bois de Wéris",
                          "HITTA Leuven Kort"}
    bk = names["BK Long Orienteering - Bois de Wéris"]
    assert bk["race"] and bk["strava_url"].endswith("/1003") and len(bk["bbox"]) == 4
    assert len(client.get("/api/strava/activities?all=true").json()) == 5

    # Your choice sticks across a full re-sync.
    client.patch("/api/strava/activities/1005", json={"orienteering": False})
    client.patch("/api/strava/activities/1004", json={"orienteering": True})
    r = client.post("/api/strava/sync", json={"full": True}).json()
    assert r["added"] == 0 and r["updated"] == 5
    ids = {a["id"] for a in client.get("/api/strava/activities").json()}
    assert ids == {1001, 1003, 1004}
    assert client.get("/api/strava/status").json()["counts"] == {"activities": 5, "orienteering": 3}


def test_sync_pages_and_token_refresh(client, fake, monkeypatch):
    from app import strava
    monkeypatch.setattr(strava, "PER_PAGE", 2)
    monkeypatch.setattr(strava, "PAGES_PER_CALL", 2)
    _connect(client)
    first = client.post("/api/strava/sync", json={"full": True}).json()
    assert first["added"] == 4 and first["next"] == {"after": None, "page": 3}
    second = client.post("/api/strava/sync", json={"full": True, "cursor": first["next"]}).json()
    assert second["added"] == 1 and second["next"] is None
    assert client.get("/api/strava/status").json()["last_sync"]

    # An expired access token is renewed before the next call.
    from app import db as dbmod
    with dbmod.SessionLocal() as s:
        conn = strava.connection(s)
        strava._put(s, "strava", conn | {"expires_at": 0})
    client.post("/api/strava/sync", json={})
    assert fake.refreshes == 1


def test_callback_rejects_bad_state_and_missing_scope(client, fake):
    r = client.get("/api/strava/callback", params={"code": "x", "state": "nope", "scope": "read"},
                   follow_redirects=False)
    assert "error=" in r.headers["location"]
    r = client.get("/api/strava/connect", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    r = client.get("/api/strava/callback", params={"code": "x", "state": state, "scope": "read"},
                   follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert client.get("/api/strava/status").json()["connected"] is False
    r = client.get("/api/strava/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert "error=" in r.headers["location"]


def test_disconnect_deletes_everything(client, fake):
    _connect(client)
    client.post("/api/strava/sync", json={})
    assert client.post("/api/strava/disconnect").json() == {"deleted": 5}
    assert fake.deauthorized
    st = client.get("/api/strava/status").json()
    assert not st["connected"] and st["counts"]["activities"] == 0


def test_polyline_and_detection():
    from app import strava
    assert strava.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    yes = ["Orienteering in Grobbendonk.", "Oriëntatieloop Kalmthout", "Course d'orientation Spa", "Mapico Brielmeersen"]
    no = ["Morning Run", "Hard forking the weirdness", "Stomping the stomping grounds"]
    assert all(strava.looks_like_orienteering({"name": n, "sport_type": "Run"}) for n in yes)
    assert not any(strava.looks_like_orienteering({"name": n, "sport_type": "Run"}) for n in no)
    assert not strava.looks_like_orienteering({"name": "Orienteering", "sport_type": "Ride"})


# --- step 2: linking runs to maps and events -------------------------------------

def _encode(points):
    """Google encoded polyline, the inverse of strava.decode_polyline."""
    out, plat, plon = [], 0, 0
    for lat, lon in points:
        ilat, ilon = round(lat * 1e5), round(lon * 1e5)
        for v in (ilat - plat, ilon - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def _placed_map(client):
    """A map placed near Leuven with a dated race and a permanent course; returns (map, route on it)."""
    from tests.conftest import make_pdf
    from tests.test_api import upload
    from tests.test_georef import synth
    f = upload(client, "park.pdf", make_pdf("Schaal 1/5.000"))["file"]
    mp = client.post("/api/maps", json={
        "name": "Arenbergpark", "location": "Leuven", "file_ids": [f["id"]],
        "version": {"survey_date": "2021-05"},
        "event": {"name": "HITTA Leuven", "event_type": "permanent"},
        "courses": [{"name": "Kort"}, {"name": "Lang"}],
    }).json()
    page = f["pages"][0]
    w, h = page["width"], page["height"]
    client.put(f"/api/pages/{page['id']}/georef",
               json={"points": synth([(50, 60), (w - 40, 80), (w - 60, h - 50), (70, h - 90)])})
    mp = client.get(f"/api/maps/{mp['id']}").json()
    lat = sum(p[0] for p in mp["footprint"]) / len(mp["footprint"])
    lon = sum(p[1] for p in mp["footprint"]) / len(mp["footprint"])
    route = [(lat + d, lon + d) for d in (-0.0003, -0.0001, 0, 0.0001, 0.0003)]
    return mp, route


def test_suggest_and_link_existing_event(client, fake):
    mp, route = _placed_map(client)
    fake.activities = [
        _activity(1, "HITTA Leuven, the long one", day=19, map={"summary_polyline": _encode(route)}),
        _activity(2, "Orienteering far away", day=20),  # Strava's sample route in California
    ]
    _connect(client)
    client.post("/api/strava/sync", json={})
    acts = {a["id"]: a for a in client.get("/api/strava/activities").json()}
    assert acts[1001]["suggestion"]["map_id"] == mp["id"] and acts[1001]["suggestion"]["inside"] == 1.0
    assert acts[1002]["suggestion"] is None

    ch = client.get("/api/strava/activities/1001/choices").json()
    (choice,) = ch["maps"]
    ev = choice["events"][0]
    assert choice["map_id"] == mp["id"] and ev["name"] == "HITTA Leuven" and ev["fit"] == "open"
    kort, lang = ev["courses"]

    r = client.put("/api/strava/activities/1001/link", json={
        "map_id": mp["id"], "event_id": ev["id"], "course_id": lang["id"], "result_time_s": 3725, "position": 3})
    assert r.status_code == 200, r.text
    link = r.json()["link"]
    assert link["course_name"] == "Lang" and link["map_name"] == "Arenbergpark" and link["date"] == "2026-09-19"

    # The map page and the events list show the run.
    detail = client.get(f"/api/maps/{mp['id']}").json()
    (p,) = detail["versions"][0]["events"][0]["participations"]
    assert p["result_time_s"] == 3725 and p["strava"]["url"].endswith("/1001")
    assert client.get("/api/events").json()[0]["run_dates"] == ["2026-09-19"]

    # A course of another event is refused; unlinking keeps the event and its courses.
    other = client.post(f"/api/versions/{detail['versions'][0]['id']}/events", json={"name": "Other"}).json()
    r = client.put("/api/strava/activities/1001/link", json={"map_id": mp["id"], "event_id": other["id"],
                                                             "course_id": lang["id"]})
    assert r.status_code == 422
    assert client.delete("/api/strava/activities/1001/link").status_code == 204
    assert client.get("/api/strava/activities").json()[1]["link"] is None
    assert len(client.get(f"/api/maps/{mp['id']}").json()["versions"][0]["events"][0]["courses"]) == 2


def test_link_creates_map_event_and_course(client, fake):
    fake.activities = [_activity(1, "Sprint orienteering in Lier", day=17, workout_type=1)]
    _connect(client)
    client.post("/api/strava/sync", json={})
    r = client.put("/api/strava/activities/1001/link", json={
        "new_map": {"name": "Lier centrum", "location": "Lier", "map_type": "sprint"},
        "new_event": {"name": "National Sprint, Lier", "event_type": "race", "discipline": "sprint"},
        "new_course": {"name": "H50", "length_km": 3.2},
        "position": 12, "competitors": 40,
    })
    assert r.status_code == 200, r.text
    link = r.json()["link"]
    mp = client.get(f"/api/maps/{link['map_id']}").json()
    assert mp["name"] == "Lier centrum" and mp["needs_review"] and mp["lat"] is not None
    ev = mp["versions"][0]["events"][0]
    assert ev["date"] == "2026-09-17" and ev["courses"][0]["name"] == "H50"
    assert ev["participations"][0]["position"] == 12

    # Now that the map exists (located, not placed), the same route suggests it.
    assert client.get("/api/strava/activities/1001/choices").json()["maps"][0]["map_id"] == mp["id"]

    # Results stay when Strava is disconnected; only the Strava part goes.
    client.post("/api/strava/disconnect")
    p = client.get(f"/api/maps/{mp['id']}").json()["versions"][0]["events"][0]["participations"][0]
    assert p["position"] == 12 and p["strava"] is None and p["strava_activity_id"] is None


def test_date_fit_and_version():
    from types import SimpleNamespace as NS
    from app import runs
    ev = lambda **kw: NS(**({"name": "", "date": None, "end_date": None, "event_type": None} | kw))  # noqa: E731
    assert runs.date_fit(ev(date="2026-09-19"), "2026-09-19") == "same_day"
    assert runs.date_fit(ev(date="2026-09-18"), "2026-09-19") is None
    assert runs.date_fit(ev(date="2026-08-21", end_date="2026-08-23"), "2026-08-22") == "open"
    assert runs.date_fit(ev(event_type="permanent"), "2026-01-24") == "open"
    assert runs.date_fit(ev(event_type="permanent", date="2027"), "2026-01-24") is None
    assert runs.date_fit(ev(date="2026-09"), "2026-09-19") == "open"
    assert runs.date_fit(ev(name="20261004 Grobbendonk"), "2026-10-04") == "same_day"
    mp = NS(versions=[NS(id=1, survey_date="2015"), NS(id=2, survey_date="2024-03"), NS(id=3, survey_date=None)])
    assert runs.version_on(mp, "2020-05-01").id == 1
    assert runs.version_on(mp, "2026-05-01").id == 2


def test_not_a_race():
    from app import strava
    for n in ["Orienteering in Hulst, to the start of race 1", "Orienteering in As - back to the cc.",
              "Sylvester Orienteering: back from the finish"]:
        assert not strava.looks_like_orienteering({"name": n, "sport_type": "Walk"})

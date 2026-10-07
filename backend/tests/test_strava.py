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

"""O'Punch: the calendar feed, a race's page, the daily pull and linking races to events and runs."""
import httpx
import pytest

FEED = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//opunch//NONSGML kigkonsult.se iCalcreator 2.41.92//\r
X-WR-TIMEZONE:Europe/Brussels\r
BEGIN:VEVENT\r
UID:3641\r
DTSTAMP:20261009T060512Z\r
DESCRIPTION:<p>Deze oriëntatieloop gaat door in het noorden van Gent: Dok N\r
 oord.</p><ul><li>Omloop 1: 8.500 m</li><li>Omloop 2: 6.000 m</li></ul>\\nhttps://www.op\r
 unch.org/in/event/3641\r
DTSTART;TZID=Europe/Brussels:20261010T100000\r
DTEND;TZID=Europe/Brussels:20261010T120000\r
GEO:+51.063400;+3.733600\r
LOCATION:Grand Café\\nMeulesteedsesteenweg\\nGent\\nBelgium\\nKom je met de auto\\, par\r
 keer dan op de P+R Muide.\r
SUMMARY:Gent Orienteering Series - Dok Noord\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:4059\r
DTSTAMP:20261009T060512Z\r
DESCRIPTION:<p>Stage in de Grand-Est.</p>\\nhttps://www.opunch.org/in/event/4059\r
DTSTART;TZID=Europe/Brussels:20261029T140000\r
DTEND;TZID=Europe/Brussels:20261101T120000\r
SUMMARY:Mégastage d'automne\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:4128\r
DTSTAMP:20261009T060512Z\r
DESCRIPTION:Training\\nhttps://www.opunch.org/in/event/4128\r
DTSTART;TZID=Europe/Brussels:20261009T171500\r
DTEND;TZID=Europe/Brussels:20261009T174500\r
SUMMARY:Entrainement & Ecole CO: Sart-Tilman\r
END:VEVENT\r
END:VCALENDAR\r
"""


def _page(id_, name, date_text, club=("trol", "TROL"), level=2, map_name="Zonnebeke", venue="d&#039;Oude Timmerie, Zonnebeke",
          geo=("50.873848", "2.991016"), regs=84):
    d = date_text
    return f"""<!DOCTYPE html><html><head><title>O'Punch | {d['title']} - {name}</title></head><body>
<div class="title-logo-image"><span class="rpad10"><img class="org-logo" src="/static/img/orgs/{club[0]}.jpg" title="{club[1]}"></span></div>
<h2> {name} <div class="badge bg-light-blue" title="{regs} registrations">{regs}</div></h2>
<h4> {venue}<br /> <small> {d['when']} </small></h4>
<div class="box box-default"><div class="box-header with-border"><div class="box-title"><i class="fa fa-info-circle"></i> Informations</div></div>
<div class="box-body"><p>Starten kan <strong>tussen 10 en 12 uur</strong>.</p><p>Baanlegger: X</p><br />
<ul class="list-unstyled hidden-print"><li class="link" id="helga_start" hidden>Registrations</li></ul></div></div>
<ul class="inline tags"><li><a class="nolink" href="#"><span class="event-level event-level-{level}" title="Regional level">REG</span></a></li></ul>
<div class="box box-default"><div class="box-header with-border"><div class="box-title"><i class="fa fa-map"></i> {map_name}</div></div><div class="box-body">ISOM</div></div>
<div class="box-body"><ul class="list-unstyled">
<li class="link" id="helga_res" hidden><a id="helga_res_a" href="https://www.helga-o.com/webres/index.php?opunch={id_}">res</a></li>
<li class="link" id="helga_splits" hidden><a id="helga_splits_a" href="https://www.helga-o.com/webres/splits/splitsbrowser.php?opunch={id_}">splits</a></li>
</ul></div>
<div id="map" class="map-sm" hidden data-geo='{{"longitude":"{geo[1]}","latitude":"{geo[0]}","zoom":"12"}}'></div>
</body></html>"""


HOME = "<html><head><title>O'Punch | Home</title></head><body>Welcome</body></html>"

PAGES = {
    3630: _page(3630, "Regionale Zonnebeke", {"title": "04/10/2025", "when": "On Saturday, 4 October 2025"}),
    3631: _page(3631, "Old training", {"title": "01/01/2024", "when": "On Monday, 1 January 2024"}, club=("hoc", "Hainaut O.C."), level=1),
    3641: _page(3641, "Gent Orienteering Series - Dok Noord", {"title": "10/10/2026", "when": "On Saturday, 10 October 2026"},
                club=("ugent", "Gent Orienteering Series"), level=1, map_name="Dok Noord", geo=("51.0634", "3.7336")),
    4059: _page(4059, "Mégastage d'automne", {"title": "29/10/2026", "when": "From Thursday, 29 October 2026 to Sunday, 1 November 2026"}),
}


@pytest.fixture()
def fake(client, monkeypatch):
    from app import opunch
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/calendar/all":
            return httpx.Response(200, text=FEED, headers={"content-type": "text/calendar; charset=utf-8"})
        if request.url.path.startswith("/in/event/"):
            return httpx.Response(200, text=PAGES.get(int(request.url.path.rsplit("/", 1)[1]), HOME))
        return httpx.Response(404)
    monkeypatch.setattr(opunch, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return calls


def test_parse_feed():
    from app.opunch import parse_ics
    evs = {e["id"]: e for e in parse_ics(FEED)}
    assert set(evs) == {3641, 4059, 4128}
    g = evs[3641]
    assert g["name"] == "Gent Orienteering Series - Dok Noord"
    assert (g["date"], g["start"], g["end"], g["end_date"]) == ("2026-10-10", "2026-10-10T10:00", "2026-10-10T12:00", None)
    assert (g["lat"], g["lon"]) == (51.0634, 3.7336)
    assert g["venue"] == "Grand Café" and g["town"] == "Gent"
    assert "P+R Muide" in g["location"] and "\\," not in g["location"]
    assert "Omloop 1: 8.500 m" in g["description"] and "<" not in g["description"] and "opunch.org" not in g["description"]
    assert g["url"] == "https://www.opunch.org/in/event/3641"
    # Several days, no location.
    s = evs[4059]
    assert (s["date"], s["end_date"], s["lat"], s["venue"], s["town"]) == ("2026-10-29", "2026-11-01", None, None, None)


def test_parse_event_page():
    from app.opunch import parse_event_page
    assert parse_event_page(HOME) is None
    p = parse_event_page(PAGES[3630])
    assert p["name"] == "Regionale Zonnebeke" and p["date"] == "2025-10-04" and p["end_date"] is None
    assert (p["club_code"], p["club_name"], p["level"], p["registrations"]) == ("trol", "TROL", 2, 84)
    assert p["map_name"] == "Zonnebeke" and p["venue"] == "d'Oude Timmerie, Zonnebeke"
    assert (p["lat"], p["lon"]) == (50.873848, 2.991016)
    assert p["results_url"].endswith("opunch=3630") and "splitsbrowser" in p["splits_url"]
    assert p["description"].startswith("Starten kan tussen 10 en 12 uur.")
    assert parse_event_page(PAGES[4059])["end_date"] == "2026-11-01"


def test_pull_status_and_details(client, fake):
    st = client.get("/api/opunch/status").json()
    assert st["last_pull"] is None and st["counts"]["races"] == 0 and st["auto_pull"] is False

    assert client.post("/api/opunch/pull").json() == {"added": 3, "updated": 0, "in_feed": 3}
    assert client.post("/api/opunch/pull").json() == {"added": 0, "updated": 3, "in_feed": 3}
    st = client.get("/api/opunch/status").json()
    assert st["last_pull"] and st["error"] is None and st["counts"]["races"] == 3

    races = client.get("/api/opunch/races").json()
    assert [r["id"] for r in races] == [4059, 3641, 4128]  # newest first
    g = next(r for r in races if r["id"] == 3641)
    assert g["events"] == [] and g["you_ran"] is False and g["has_details"] is False and g["town"] == "Gent"

    # Details from the race's page: club, level, map name, results. Feed data is kept.
    g = client.post("/api/opunch/races/3641/details").json()
    assert g["has_details"] and g["club_name"] == "Gent Orienteering Series" and g["level_name"] == "local"
    assert g["map_name"] == "Dok Noord" and g["results_url"].endswith("opunch=3641") and g["venue"] == "Grand Café"
    assert client.post("/api/opunch/races/9999/details").status_code == 404

    # "I ran this", also without a map in the library.
    assert client.patch("/api/opunch/races/4128", json={"ran": True}).json()["you_ran"] is True
    assert client.get("/api/opunch/status").json()["counts"]["ran"] == 1


def test_pull_error_is_recorded(client, monkeypatch):
    from app import opunch
    monkeypatch.setattr(opunch, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(503, text="down"))))
    assert client.post("/api/opunch/pull").status_code == 502
    assert "503" in client.get("/api/opunch/status").json()["error"]


def test_link_race_to_event(client, fake):
    client.post("/api/opunch/pull")
    client.post("/api/opunch/races/3641/details")
    mp = client.post("/api/maps", json={"name": "Dok Noord", "event": {"name": "GOS Dok Noord"}}).json()
    ev = mp["versions"][0]["events"][0]
    assert ev["opunch_id"] is None and mp["lat"] is None

    r = client.post("/api/opunch/races/3641/link", json={"event_id": ev["id"]}).json()
    assert r["events"][0]["id"] == ev["id"] and r["events"][0]["map_name"] == "Dok Noord"
    full = client.get(f"/api/maps/{mp['id']}").json()
    ev = full["versions"][0]["events"][0]
    # The event's blanks come from the race; the map gets the race's pin and town.
    assert ev["opunch_id"] == 3641 and ev["date"] == "2026-10-10" and ev["organiser_name"] == "Gent Orienteering Series"
    assert ev["results_url"] is None  # the race is still ahead: no results yet
    assert (full["lat"], full["lon"], full["location"]) == (51.0634, 3.7336, "Gent")
    assert [c["name"] for c in client.get("/api/clubs").json()] == ["Gent Orienteering Series"]
    assert client.get("/api/events").json()[0]["opunch_id"] == 3641

    client.delete(f"/api/opunch/races/3641/link/{ev['id']}")
    assert client.get("/api/opunch/races/3641").json()["events"] == []
    # And by hand, through the event form.
    assert client.patch(f"/api/events/{ev['id']}", json={"opunch_id": 3641}).json()["opunch_id"] == 3641
    assert client.post("/api/opunch/races/3641/link", json={"event_id": 999}).status_code == 404


def test_races_for_a_run(client, fake):
    from app import db as dbmod
    from app import models as m
    from datetime import datetime, timezone
    client.post("/api/opunch/pull")
    with dbmod.SessionLocal() as s:
        # A run that started 300 m from the Dok Noord meeting point, on the day of the race.
        s.add(m.StravaActivity(id=1001, name="Saturday orienteering", sport_type="Run",
                               start_date=datetime(2026, 10, 10, 8, 10, tzinfo=timezone.utc), start_local="2026-10-10T10:10:00",
                               distance_m=6000, moving_time_s=2500, elapsed_time_s=2600, commute=0, private=0,
                               start_lat=51.066, start_lon=3.7336, orienteering=1, orienteering_manual=0))
        # One far away on the same day, and one on a day without races.
        s.add(m.StravaActivity(id=1002, name="Orienteering elsewhere", sport_type="Run",
                               start_date=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc), start_local="2026-10-10T10:00:00",
                               commute=0, private=0, start_lat=50.4, start_lon=4.8, orienteering=1, orienteering_manual=0))
        s.add(m.StravaActivity(id=1003, name="Orienteering stage day 2", sport_type="Run",
                               start_date=datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc), start_local="2026-10-30T10:00:00",
                               commute=0, private=0, orienteering=1, orienteering_manual=0))
        s.commit()

    acts = {a["id"]: a for a in client.get("/api/strava/activities").json()}
    assert acts[1001]["opunch_race"] == {"id": 3641, "name": "Gent Orienteering Series - Dok Noord", "distance_m": 289}
    assert acts[1002]["opunch_race"] is None  # 150 km from the only race with coordinates that day
    assert acts[1003]["opunch_race"]["id"] == 4059  # the only race on that day: the stage, which runs over four days

    ch = client.get("/api/strava/activities/1001/choices").json()
    assert [r["id"] for r in ch["races"]] == [3641]
    assert ch["races"][0]["distance_m"] == 289 and ch["maps"] == []

    # Link the run: a new map and a new event made from the race.
    r = client.put("/api/strava/activities/1001/link", json={
        "new_map": {"name": "Dok Noord"}, "new_event": {"name": "Gent Orienteering Series - Dok Noord", "opunch_id": 3641},
        "result_time_s": 2345, "position": 12,
    }).json()
    assert r["link"]["event_name"] == "Gent Orienteering Series - Dok Noord" and r["opunch_race"] is None
    ev = client.get(f"/api/maps/{r['link']['map_id']}").json()["versions"][0]["events"][0]
    assert ev["opunch_id"] == 3641 and ev["date"] == "2026-10-10" and ev["event_type"] == "race"
    race = client.get("/api/opunch/races/3641").json()
    assert race["you_ran"] is True and race["events"][0]["runs"] == 1 and race["events"][0]["map_id"] == r["link"]["map_id"]
    # The event is now offered for this map, marked as the race.
    ch = client.get(f"/api/strava/activities/1001/choices?map_id={r['link']['map_id']}").json()
    assert ch["maps"][0]["events"][0]["opunch_id"] == 3641
    assert client.put("/api/strava/activities/1002/link", json={
        "new_map": {"name": "X"}, "new_event": {"name": "Y", "opunch_id": 1}}).status_code == 422


def test_backfill(client, fake):
    from app import db as dbmod
    from app import opunch
    seen = []
    with dbmod.SessionLocal() as s:
        r = opunch.backfill(s, 3629, 3632, since="2025-01-01", delay=0, progress=lambda i, st: seen.append((i, st)))
    assert r == {"kept": 1, "skipped": 1, "missing": 2}
    assert [i for i, _ in seen] == [3629, 3630, 3631, 3632] and seen[1][1].startswith("added  2025-10-04")
    races = client.get("/api/opunch/races").json()
    assert [x["id"] for x in races] == [3630]
    z = races[0]
    assert z["source"] == "page" and z["has_details"] and z["club_name"] == "TROL" and z["level_name"] == "regional"
    assert (z["lat"], z["venue"], z["map_name"]) == (50.873848, "d'Oude Timmerie, Zonnebeke", "Zonnebeke")
    # A later feed pull doesn't wipe what the page gave.
    client.post("/api/opunch/pull")
    assert client.get("/api/opunch/races/3630").json()["club_name"] == "TROL"
    assert len(client.get("/api/opunch/races").json()) == 4


def test_scheduler_is_off_in_tests_and_due():
    from app import config, opunch
    assert config.OPUNCH_AUTO_PULL is False
    assert opunch.start_scheduler(None) is None

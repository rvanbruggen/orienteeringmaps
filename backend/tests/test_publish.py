import subprocess

import pytest

from tests.conftest import make_pdf
from tests.test_api import upload


@pytest.fixture()
def site_dist(tmp_path, monkeypatch):
    """A stand-in for the built viewer (frontend/dist-site)."""
    from app import config
    dist = tmp_path / "dist-site"
    (dist / "assets").mkdir(parents=True)
    (dist / "site.html").write_text('<!doctype html><html><head><title>x</title>'
                                    '<script type="module" src="./assets/site.js"></script></head>'
                                    '<body><div id="app"></div></body></html>')
    (dist / "assets" / "site.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    monkeypatch.setattr(config, "SITE_DIST", dist)
    return dist


def _library(client):
    from tests.test_georef import synth
    club = client.post("/api/clubs", json={"name": "OMEGA", "website": "https://omega.example"}).json()
    f = upload(client, "park.pdf", make_pdf("Schaal 1/5.000", pages=2))["file"]
    full = client.post("/api/maps", json={
        "name": "Arenbergpark Één", "location": "Leuven", "club_id": club["id"], "file_ids": [f["id"]],
        "notes": "SECRET-NOTE", "publish_level": "full", "public_note": "Nice park",
        "version": {"scale": 5000, "survey_date": "2021-05", "notes": "SECRET-VERSION"},
        "event": {"name": "HITTA Leuven", "date": "2022", "notes": "SECRET-EVENT"},
        "courses": [{"name": "Kort", "file_id": f["id"], "page_no": 2}],
    }).json()
    page = f["pages"][0]
    w, h = page["width"], page["height"]
    client.put(f"/api/pages/{page['id']}/georef",
               json={"points": synth([(50, 60), (w - 40, 80), (w - 60, h - 50), (70, h - 90)])})
    g = upload(client, "forest.pdf", make_pdf("Schaal 1/10.000"))["file"]
    outline = client.post("/api/maps", json={"name": "Forest", "lat": 50.9, "lon": 4.5, "file_ids": [g["id"]],
                                             "publish_level": "outline"}).json()
    client.post("/api/maps", json={"name": "Hidden", "notes": "SECRET-PRIVATE"})
    return full, outline, f, g


def test_publish_levels_and_settings(client):
    r = client.post("/api/maps", json={"name": "X", "publish_level": "everything"})
    assert r.status_code == 422
    mp = client.post("/api/maps", json={"name": "X"}).json()
    assert mp["publish_level"] == "private"
    mp = client.patch(f"/api/maps/{mp['id']}", json={"publish_level": "overlay", "public_note": "hi"}).json()
    assert mp["publish_level"] == "overlay" and mp["public_note"] == "hi"
    assert client.patch(f"/api/maps/{mp['id']}", json={"publish_level": None}).status_code == 422

    st = client.get("/api/publish/settings").json()
    assert st["settings"]["github_repo"] == "orienteeringmaps-public" and st["token"] is False
    assert st["site_url"] is None  # owner unknown until the token is checked
    client.put("/api/publish/settings", json={"github_repo": "rik/omaps-public", "site_title": "Rik's maps"})
    st = client.get("/api/publish/settings").json()
    assert st["site_url"] == "https://rik.github.io/omaps-public/" and st["settings"]["site_title"] == "Rik's maps"
    assert client.put("/api/publish/settings", json={"site_url": "kaarten.example"}).status_code == 422
    assert client.put("/api/publish/settings", json={"bogus": 1}).status_code == 422


def test_build_site(client, site_dist):
    from app import db, publish
    full, outline, f, g = _library(client)
    with db.SessionLocal() as session:
        settings = publish.get_settings(session) | {"site_url": "https://maps.example.org/"}
        site = publish.build_site(session, settings, "https://maps.example.org/")

    names = [m["name"] for m in site.data["maps"]]
    assert names == ["Arenbergpark Één", "Forest"]
    assert site.counts == {"outline": 1, "overlay": 0, "full": 1}

    # Nothing private leaks into any file.
    for path, src in site.files.items():
        if isinstance(src, bytes):
            assert b"SECRET" not in src, path

    full_rec = site.data["maps"][0]
    assert full_rec["slug"] == f"{full['id']}-arenbergpark-een"
    assert full_rec["note"] == "Nice park" and full_rec["club_url"] == "https://omega.example"
    assert full_rec["hero"]["place"]["corners"] and full_rec["footprint"]
    files = full_rec["versions"][0]["files"]
    assert len(files[0]["pages"]) == 2 and files[0]["url"] in site.files
    course = full_rec["versions"][0]["events"][0]["courses"][0]
    assert course == {"name": "Kort", "file": files[0]["key"], "page": 2}

    out_rec = site.data["maps"][1]
    assert "hero" not in out_rec and "thumb" not in out_rec and out_rec["versions"][0].get("files", []) == []
    assert not any(g["pages"][0]["image_url"].removeprefix("/media/") in p for p in site.files)

    page = site.files[f"map/{full_rec['slug']}/index.html"].decode()
    assert '<base href="/">' in page and "Arenbergpark Één – Orienteering maps" in page
    assert f'<link rel="canonical" href="https://maps.example.org/map/{full_rec["slug"]}/">' in page
    assert "HITTA Leuven" in page  # crawlable text
    assert f"map/{full_rec['slug']}/" in site.files["sitemap.xml"].decode()
    assert site.files["CNAME"] == b"maps.example.org\n"
    assert "assets/site.js" in site.files and "404.html" in site.files
    data_paths = [p for p in site.files if p.startswith("data/site-")]
    assert len(data_paths) == 1 and data_paths[0] in page
    # One warning: Forest has no club.
    assert [w["name"] for w in site.warnings] == ["Forest"]


def test_preview_endpoint(client, site_dist):
    _library(client)
    r = client.post("/api/publish/preview")
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["maps"] == 2 and res["pending"] is None
    home = client.get("/site-preview/")
    assert home.status_code == 200 and '<base href="/site-preview/">' in home.text
    assert client.get("/site-preview/nope/").status_code == 404
    assert client.get("/site-preview/../orienteeringmaps.db").status_code == 404


def test_sync_dir(tmp_path):
    from app.publish import sync_dir
    src = tmp_path / "img.webp"
    src.write_bytes(b"12345")
    target = tmp_path / "out"
    first = sync_dir(target, {"index.html": b"a", "media/x/img.webp": src})
    assert first["added"] == 2 and (target / "media/x/img.webp").read_bytes() == b"12345"
    (target / ".git").mkdir()
    (target / ".git" / "HEAD").write_text("x")
    again = sync_dir(target, {"index.html": b"b"}, dry_run=True)
    assert (again["added"], again["changed"], again["removed"]) == (0, 1, 1)
    assert (target / "media/x/img.webp").exists()  # dry run
    sync_dir(target, {"index.html": b"b"})
    assert not (target / "media").exists() and (target / ".git" / "HEAD").exists()


def test_publish_pushes_with_git(client, site_dist, tmp_path, monkeypatch):
    """The whole publish run against a local bare repository instead of GitHub."""
    from app import config, github
    remote_root = tmp_path / "remote"
    (remote_root / "rik").mkdir(parents=True)
    bare = remote_root / "rik" / "omaps-public.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    monkeypatch.setattr(config, "GITHUB_GIT", f"file://{remote_root}")
    monkeypatch.setattr(config, "GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(github, "status", lambda settings: {
        "token": True, "login": "rik", "repo": "rik/omaps-public", "repo_exists": True, "can_push": True})
    monkeypatch.setattr(github, "_ensure_pages", lambda *a: None)
    _library(client)

    def publish_once():
        run = client.post("/api/publish")
        assert run.status_code == 202, run.text
        for _ in range(200):
            r = client.get(f"/api/publish/runs/{run.json()['id']}").json()
            if r["status"] != "running":
                return r
            __import__("time").sleep(0.05)
        raise AssertionError("publish did not finish")

    first = publish_once()
    assert first["status"] == "done", first["log"]
    assert first["summary"]["maps"] == 2 and first["summary"]["added"] > 5
    files = subprocess.run(["git", "--git-dir", str(bare), "ls-tree", "-r", "--name-only", "main"],
                           capture_output=True, text=True, check=True).stdout.split()
    assert "index.html" in files and "sitemap.xml" in files and any(f.startswith("media/") for f in files)

    assert publish_once()["status"] == "unchanged"

    preview = client.post("/api/publish/preview").json()
    assert preview["pending"]["added"] == 0 and preview["pending"]["changed"] == 0

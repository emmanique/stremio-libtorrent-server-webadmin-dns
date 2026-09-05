import io
import json

from fastapi.testclient import TestClient

from stremiosrv.admin.api import _clear_logs, _restart_process, load_overrides
from stremiosrv.app import create_app
from stremiosrv.config import Settings


class _Engine:
    def __init__(self):
        self.applied = None
        self.removed = None
        self.pinned = None
        self.unpinned = None

    def active(self):
        return []

    def apply_admin_settings(self, **values):
        self.applied = values

    def remove(self, info_hash):
        self.removed = info_hash

    def pin(self, info_hash):
        self.pinned = info_hash
        return {"infoHash": info_hash}

    def unpin(self, info_hash):
        self.unpinned = info_hash


def test_admin_page_and_status(tmp_path):
    app = create_app(Settings(cache_root=str(tmp_path)))
    client = TestClient(app)
    assert client.get("/admin/").status_code == 200
    body = client.get("/admin/api/status").json()
    assert body["server"]["running"] is True
    assert body["urls"]["webPlayer"].endswith(":8080")


def test_github_version_is_exposed_and_cached(tmp_path, monkeypatch):
    from stremiosrv.admin import api

    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return Response(b'[project]\nname = "stremiosrv"\nversion = "1.4.0"\n')

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(api, "_github_version_cache", (0.0, None))
    client = TestClient(create_app(Settings(cache_root=str(tmp_path))))
    first = client.get("/admin/api/github-version").json()
    second = client.get("/admin/api/github-version").json()
    assert first["version"] == "1.4.0"
    assert first["available"] is True
    assert second == first
    assert len(calls) == 1


def test_portugal_theme_title_and_background(tmp_path):
    client = TestClient(create_app(Settings(cache_root=str(tmp_path))))
    page = client.get("/admin/").text
    assert "STREMIO SERVER WEB ADMIN" in page
    assert "feito por Velha Guarda de Almada" in page
    assert "Open Pi-hole Admin" in page
    assert "location.hostname}:8053/admin/" in page
    assert "theme-background.jpg" in page
    background = client.get("/admin/theme-background.jpg")
    assert background.status_code == 200
    assert background.headers["content-type"] == "image/jpeg"
    assert len(background.content) > 100_000
    assert 'rel="icon" href="favicon.ico"' in page
    favicon = client.get("/admin/favicon.ico")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"] == "image/x-icon"
    assert favicon.content[:4] == b"\x00\x00\x01\x00"


def test_admin_copy_has_http_lan_fallback(tmp_path):
    client = TestClient(create_app(Settings(cache_root=str(tmp_path))))
    page = client.get("/admin/").text
    assert "navigator.clipboard&&window.isSecureContext" in page
    assert "document.execCommand('copy')" in page


def test_settings_apply_and_survive_restart(tmp_path):
    engine = _Engine()
    settings = Settings(cache_root=str(tmp_path))
    client = TestClient(create_app(settings, engine=engine))
    values = {
        "seed_on_complete": False, "max_seed_minutes": 15, "max_streams": 2,
        "download_rate_limit": 1_000_000, "upload_rate_limit": 250_000,
        "idle_download_rate_limit": 50_000,
    }
    assert client.put("/admin/api/settings", json=values).json()["ok"] is True
    assert engine.applied == values
    assert json.loads((tmp_path / "admin-settings.json").read_text()) == values
    restarted = Settings(cache_root=str(tmp_path))
    load_overrides(restarted)
    assert restarted.max_streams == 2
    assert restarted.seed_on_complete is False


def test_remove_rejects_bad_hash_and_removes_valid_hash(tmp_path):
    engine = _Engine()
    client = TestClient(create_app(Settings(cache_root=str(tmp_path)), engine=engine))
    assert client.delete("/admin/api/streams/nope").status_code == 400
    info_hash = "a" * 40
    assert client.delete(f"/admin/api/streams/{info_hash}").json() == {"ok": True}
    assert engine.removed == info_hash


def test_qr_is_real_svg(tmp_path):
    client = TestClient(create_app(Settings(cache_root=str(tmp_path))))
    response = client.get("/admin/api/qr.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in response.content


def test_pin_and_unpin_active_stream(tmp_path):
    engine = _Engine()
    client = TestClient(create_app(Settings(cache_root=str(tmp_path)), engine=engine))
    info_hash = "b" * 40
    assert client.post(f"/admin/api/streams/{info_hash}/pin").status_code == 200
    assert engine.pinned == info_hash
    assert client.delete(f"/admin/api/streams/{info_hash}/pin").status_code == 200
    assert engine.unpinned == info_hash


def test_full_configuration_is_typed_and_persisted(tmp_path):
    settings = Settings(cache_root=str(tmp_path))
    client = TestClient(create_app(settings))
    items = client.get("/admin/api/config").json()["items"]
    by_name = {item["name"]: item for item in items}
    assert by_name["seed_on_complete"]["type"] == "boolean"
    assert by_name["debug_logs"]["type"] == "boolean"
    assert by_name["debug_logs"]["restartRequired"] is True
    assert by_name["extra_trackers"]["type"] == "text"
    assert by_name["cache_root"]["editable"] is False
    response = client.put("/admin/api/config", json={"values": {
        "extra_trackers": "udp://tracker.example:80", "prefetch_next": True,
    }})
    assert response.status_code == 200
    assert response.json()["restartRequired"] is True
    saved = json.loads((tmp_path / "admin-settings.json").read_text())
    assert saved["prefetch_next"] is True


def test_restart_stops_the_uvicorn_process_not_container_pid_one(monkeypatch):
    calls = []
    monkeypatch.setattr("stremiosrv.admin.api.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("stremiosrv.admin.api.os.kill", lambda pid, sig: calls.append((pid, sig)))
    _restart_process(4321)
    assert calls == [(4321, 15)]


def test_logs_are_separated_by_source_and_tailed(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "application.log").write_text("old\nline two\nline three\n", encoding="utf-8")
    (logs / "nginx.log").write_text("nginx only\n", encoding="utf-8")
    client = TestClient(create_app(Settings(cache_root=str(tmp_path))))

    application = client.get("/admin/api/logs?source=application&lines=10").json()
    nginx = client.get("/admin/api/logs?source=nginx&lines=10").json()
    assert application["lines"] == ["old", "line two", "line three"]
    assert application["debug"] is False
    assert nginx["lines"] == ["nginx only"]
    assert {item["id"] for item in application["availableSources"]} == {
        "application", "nginx", "container", "updater", "admin",
    }


def test_logs_reject_unknown_source(tmp_path):
    client = TestClient(create_app(Settings(cache_root=str(tmp_path))))
    assert client.get("/admin/api/logs?source=../../etc/passwd").status_code == 400


def test_clean_selected_and_all_logs(tmp_path):
    for relative in ("logs/application.log", "logs/nginx.log", "logs/container.log",
                     "logs/admin.log", "admin-update.log"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("debug line\n", encoding="utf-8")
    assert _clear_logs(tmp_path, "application") == ["application"]
    assert (tmp_path / "logs/application.log").read_text() == ""
    assert (tmp_path / "logs/nginx.log").read_text() == "debug line\n"
    cleared = _clear_logs(tmp_path)
    assert set(cleared) == {"application", "nginx", "container", "updater", "admin"}
    assert (tmp_path / "logs/nginx.log").read_text() == ""


def test_clean_logs_endpoint(tmp_path):
    path = tmp_path / "logs/nginx.log"
    path.parent.mkdir(parents=True)
    path.write_text("warning\n", encoding="utf-8")
    client = TestClient(create_app(Settings(cache_root=str(tmp_path))))
    response = client.post("/admin/api/logs/clear", json={"source": "nginx"})
    assert response.status_code == 200
    assert response.json()["cleared"] == ["nginx"]
    assert path.read_text() == ""


def test_status_includes_inactive_cache_and_capacity(tmp_path, monkeypatch):
    from stremiosrv import cache as cachemod

    monkeypatch.setattr(cachemod, "scan_cache", lambda _root: [
        {"name": "finished.mkv", "size": 250, "mtime": 123.0, "path": "/unused"},
    ])
    monkeypatch.setattr(cachemod, "load_name_index", lambda _root: {
        "finished.mkv": "c" * 40,
    })
    monkeypatch.setattr(cachemod, "usage", lambda _root, budget: {
        "cacheUsed": 250, "cacheSize": budget, "transcodeUsed": 0,
        "diskFree": 750, "diskTotal": 1000,
    })
    client = TestClient(create_app(Settings(cache_root=str(tmp_path), cache_size=1000)))
    body = client.get("/admin/api/status").json()
    assert body["cache"]["cacheUsed"] == 250
    assert body["cache"]["cacheSize"] == 1000
    assert body["streams"][0]["name"] == "finished.mkv"
    assert body["streams"][0]["cached"] is True
    assert body["streams"][0]["active"] is False


def test_admin_can_delete_inactive_cached_content(tmp_path):
    cached = tmp_path / "finished.mkv"
    cached.write_bytes(b"cached")
    client = TestClient(create_app(Settings(cache_root=str(tmp_path))))
    response = client.post("/admin/api/cache/remove", json={"name": "finished.mkv"})
    assert response.status_code == 200
    assert not cached.exists()

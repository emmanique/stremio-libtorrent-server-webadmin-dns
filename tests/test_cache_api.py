from fastapi.testclient import TestClient

from stremiosrv.app import create_app


def test_cache_list_shape(monkeypatch):
    from stremiosrv import cache as cachemod
    monkeypatch.setattr(
        cachemod, "scan_cache",
        lambda root: [{"name": "a.iso", "size": 10, "mtime": 1.0}],
    )
    client = TestClient(create_app())  # engine is None
    body = client.get("/cache.json").json()
    assert body == [
        {"name": "a.iso", "size": 10, "mtime": 1.0, "active": False, "infoHash": None}
    ]


def test_cache_list_marks_active(monkeypatch):
    from stremiosrv import cache as cachemod
    monkeypatch.setattr(
        cachemod, "scan_cache",
        lambda root: [{"name": "a.iso", "size": 10, "mtime": 1.0}],
    )

    class FakeEngine:
        def name_to_hash(self):
            return {"a.iso": "deadbeef"}

    client = TestClient(create_app(engine=FakeEngine()))
    body = client.get("/cache.json").json()
    assert body[0]["active"] is True
    assert body[0]["infoHash"] == "deadbeef"


def test_cache_list_idle_item_gets_infohash_from_index(monkeypatch):
    """An item not in the live engine map gets infoHash from the persisted index, active=False."""
    from stremiosrv import cache as cachemod
    monkeypatch.setattr(
        cachemod, "scan_cache",
        lambda root: [{"name": "a.iso", "size": 10, "mtime": 1.0}],
    )
    monkeypatch.setattr(
        cachemod, "load_name_index",
        lambda root: {"a.iso": "cafebabe"},
    )
    client = TestClient(create_app())  # engine is None -> no live entry
    body = client.get("/cache.json").json()
    assert body == [
        {"name": "a.iso", "size": 10, "mtime": 1.0, "active": False, "infoHash": "cafebabe"}
    ]


def test_cache_remove_rejects_unsafe_names():
    client = TestClient(create_app())
    for bad in ["../x", "a/b", "..", ".", ""]:
        resp = client.post("/cache/remove", json={"name": bad})
        assert resp.status_code == 400, bad


def test_cache_remove_rejects_protected():
    client = TestClient(create_app())
    resp = client.post("/cache/remove", json={"name": "certificates.pem"})
    assert resp.status_code == 400


def test_cache_remove_valid(monkeypatch):
    from stremiosrv import cache as cachemod
    removed = []
    monkeypatch.setattr(cachemod, "_remove", lambda p: removed.append(p))
    client = TestClient(create_app())
    resp = client.post("/cache/remove", json={"name": "a.iso"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert removed and removed[0].endswith("a.iso")


def test_cache_remove_stops_active_torrent(monkeypatch):
    from stremiosrv import cache as cachemod
    monkeypatch.setattr(cachemod, "_remove", lambda p: None)
    stopped = []

    class FakeEngine:
        def name_to_hash(self):
            return {"a.iso": "deadbeef"}

        def remove(self, ih):
            stopped.append(ih)

    client = TestClient(create_app(engine=FakeEngine()))
    client.post("/cache/remove", json={"name": "a.iso"})
    assert stopped == ["deadbeef"]

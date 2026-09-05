import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from stremiosrv import cache as cachemod

router = APIRouter()


class RemoveBody(BaseModel):
    name: str


def _name_to_hash(engine) -> dict:
    return engine.name_to_hash() if engine is not None else {}


@router.get("/cache.json")
def cache_list(request: Request) -> list[dict]:
    """On-disk cache entries (the LRU store) — distinct from /active.json (loaded torrents).
    Content-neutral: names only, the owner's own box."""
    s = request.app.state.settings
    live = _name_to_hash(request.app.state.engine)
    idle = cachemod.load_name_index(s.cache_root)
    out = []
    for item in cachemod.scan_cache(s.cache_root):
        ih = live.get(item["name"]) or idle.get(item["name"])
        out.append({
            "name": item["name"],
            "size": item["size"],
            "mtime": item["mtime"],
            "active": item["name"] in live,
            "infoHash": ih,
        })
    return out


@router.post("/cache/remove")
def cache_remove(body: RemoveBody, request: Request) -> dict:
    """Delete one cache entry. Guard: must be a plain direct child of cache_root and not a
    protected system file."""
    name = body.name
    if (not name or name in (".", "..") or os.path.basename(name) != name
            or name in cachemod.PROTECTED):
        raise HTTPException(status_code=400, detail="invalid cache entry name")
    engine = request.app.state.engine
    if engine is not None:
        ih = engine.name_to_hash().get(name)
        if ih:
            engine.remove(ih)  # stop libtorrent before deleting its files
    cachemod._remove(os.path.join(request.app.state.settings.cache_root, name))
    return {"ok": True}

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from collections import deque
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import segno
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from stremiosrv import cache as cachemod
from stremiosrv import health
from stremiosrv import pins as pinsmod
from stremiosrv.api.playback import serialize_active
from stremiosrv.certcheck import cert_days_left
from stremiosrv.config import Settings
from stremiosrv.torrent.engine import PinSpaceError

router = APIRouter(prefix="/admin")
_STARTED = time.monotonic()
_STATIC = Path(__file__).with_name("static")
_GITHUB_VERSION_URL = (
    "https://raw.githubusercontent.com/emmanique/stremio-libtorrent-server-webadmin-dns/main/pyproject.toml"
)
_GITHUB_REPOSITORY_URL = "https://github.com/emmanique/stremio-libtorrent-server-webadmin-dns"
_github_version_cache: tuple[float, str | None] = (0.0, None)
_github_version_lock = threading.Lock()
_FIELDS = (
    "seed_on_complete", "max_seed_minutes", "max_streams",
    "download_rate_limit", "upload_rate_limit", "idle_download_rate_limit",
)
_READ_ONLY = {"cache_root", "http_port", "cert_file", "bt_listen_port"}
_CONFIG_DESCRIPTIONS = {
    "dns_server": "DNS resolver used by the complete container. Leave empty to keep Docker DNS.",
}
_LOG_SOURCES = {
    "application": ("logs/application.log", "Application / Uvicorn"),
    "nginx": ("logs/nginx.log", "Nginx"),
    "container": ("logs/container.log", "Docker container (combined)"),
    "updater": ("admin-update.log", "Software updates"),
    "admin": ("logs/admin.log", "Web Admin actions"),
}


class AdminSettings(BaseModel):
    seed_on_complete: bool = True
    max_seed_minutes: int = Field(0, ge=0, le=525_600)
    max_streams: int = Field(0, ge=0, le=1000)
    download_rate_limit: int = Field(0, ge=0)
    upload_rate_limit: int = Field(0, ge=0)
    idle_download_rate_limit: int = Field(0, ge=0)


class ConfigUpdate(BaseModel):
    values: dict[str, object]


class CacheRemove(BaseModel):
    name: str


class LogClear(BaseModel):
    source: str | None = None


def _override_path(settings) -> Path:
    return Path(settings.cache_root) / "admin-settings.json"


def load_overrides(settings) -> None:
    """Apply settings saved by the admin UI before the torrent engine is created."""
    try:
        raw = json.loads(_override_path(settings).read_text())
        allowed = {key: value for key, value in raw.items() if key in Settings.model_fields}
        values = Settings(**allowed)
    except (OSError, ValueError, TypeError):
        return
    for key in allowed:
        setattr(settings, key, getattr(values, key))


def _save(settings, values: dict[str, object]) -> None:
    path = _override_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        current = json.loads(path.read_text())
    except (OSError, ValueError):
        current = {}
    current.update(values)
    tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _audit(settings, action: str, detail: str = "") -> None:
    path = Path(settings.cache_root) / "logs/admin.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as output:
        output.write(f"{timestamp} action={action} {detail}".rstrip() + "\n")


def _tail(path: Path, limit: int) -> list[str]:
    try:
        with path.open(encoding="utf-8", errors="replace") as source:
            return list(deque((line.rstrip("\n") for line in source), maxlen=limit))
    except OSError:
        return []


def _github_version() -> str | None:
    """Read the version declared on GitHub, cached to avoid dashboard polling traffic."""
    global _github_version_cache
    checked, version = _github_version_cache
    if time.monotonic() - checked < 900:
        return version
    with _github_version_lock:
        checked, version = _github_version_cache
        if time.monotonic() - checked < 900:
            return version
        try:
            request = urllib.request.Request(
                _GITHUB_VERSION_URL, headers={"User-Agent": "stremiosrv-web-admin"},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                text = response.read(131_072).decode("utf-8", errors="replace")
            match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
            version = match.group(1) if match else None
        except (OSError, ValueError):
            version = None
        _github_version_cache = (time.monotonic(), version)
        return version


def _clear_logs(root: Path, source: str | None = None) -> list[str]:
    if source is not None and source not in _LOG_SOURCES:
        raise HTTPException(400, "unknown log source")
    selected = [source] if source else list(_LOG_SOURCES)
    for key in selected:
        relative = _LOG_SOURCES[key][0]
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate instead of unlinking: tee keeps the files open while the container runs.
        path.write_text("", encoding="utf-8")
    return selected


def _lan_ip() -> str:
    configured = os.getenv("IPADDRESS", "").strip()
    if configured:
        return configured
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def _memory() -> tuple[int, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return 0, 0
    return values.get("MemTotal", 0), values.get("MemAvailable", 0)


def _cpu_percent() -> float:
    try:
        load = os.getloadavg()[0]
        return round(min(100.0, load / max(1, os.cpu_count() or 1) * 100), 1)
    except OSError:
        return 0.0


def _urls() -> dict:
    ip = _lan_ip()
    https = os.getenv("SERVER_URL", "").strip().rstrip("/")
    if not https and os.getenv("IPADDRESS"):
        dashed = ip.replace(".", "-")
        https = f"https://{dashed}.519b6502d940.stremio.rocks:12470"
    server = https or f"http://{ip}:11470"
    return {
        "ip": ip,
        "webPlayer": f"http://{ip}:8080",
        "streamingServer": server,
        "desktopFlag": f"--development --webui-url={server}",
    }


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
def page() -> FileResponse:
    return FileResponse(_STATIC / "index.html", media_type="text/html")


@router.get("/theme-background.jpg", include_in_schema=False)
def theme_background() -> FileResponse:
    return FileResponse(_STATIC / "theme-background.jpg", media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(
        _STATIC / "favicon.ico", media_type="image/x-icon",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@router.get("/api/status")
def status(request: Request) -> dict:
    settings = request.app.state.settings
    engine = getattr(request.app.state, "engine", None)
    total, available = _memory()
    cert_path = Path(settings.cache_root) / settings.cert_file
    days = cert_days_left(str(cert_path)) if cert_path.exists() else None
    loaded = [serialize_active(h) for h in engine.active()] if engine else []
    live_by_name = {item["name"]: item for item in loaded}
    live_names = engine.name_to_hash() if engine and hasattr(engine, "name_to_hash") else {}
    idle_names = cachemod.load_name_index(settings.cache_root)
    pinned = pinsmod.pinned_hashes(settings.cache_root)
    cached = cachemod.scan_cache(settings.cache_root)
    for item in cached:
        stream = live_by_name.get(item["name"])
        info_hash = live_names.get(item["name"]) or idle_names.get(item["name"])
        if stream is None:
            stream = {
                "infoHash": info_hash,
                "name": item["name"],
                "downloadSpeed": 0,
                "uploadSpeed": 0,
                "peers": 0,
                "downloaded": item["size"],
                "uploaded": 0,
                "progress": 1.0,
                "active": False,
                "paused": False,
                "pinned": bool(info_hash and info_hash.lower() in pinned),
            }
            loaded.append(stream)
        stream.update({"cached": True, "cacheBytes": item["size"], "mtime": item["mtime"]})
    for stream in loaded:
        stream.setdefault("cached", False)
        stream.setdefault("cacheBytes", 0)
        stream.setdefault("mtime", None)
    loaded.sort(key=lambda item: (not item["active"], -float(item.get("mtime") or 0)))
    cache_usage = cachemod.usage(settings.cache_root, int(settings.cache_size))
    return {
        "server": {
            "running": True,
            "healthy": days is None or days >= health.CERT_WARN_DAYS,
            "version": health._VERSION or "development",
            "uptimeSeconds": int(time.monotonic() - _STARTED),
            "cpuPercent": _cpu_percent(),
            "memoryUsed": max(0, total - available),
            "memoryTotal": total,
            "certDaysLeft": days,
        },
        "urls": _urls(),
        "settings": {key: getattr(settings, key) for key in _FIELDS},
        "streams": loaded,
        "cache": cache_usage,
        "updates": {
            "mode": "managed-command",
            "enabled": bool(os.getenv("STREMIOSRV_ADMIN_UPDATE_COMMAND", "").strip()),
            "running": (Path(settings.cache_root) / "admin-update.running").exists(),
        },
    }


@router.get("/api/github-version")
def github_version() -> dict:
    version = _github_version()
    return {
        "version": version,
        "available": version is not None,
        "repositoryUrl": _GITHUB_REPOSITORY_URL,
    }


@router.put("/api/settings")
def update_settings(values: AdminSettings, request: Request) -> dict:
    settings = request.app.state.settings
    for key, value in values.model_dump().items():
        setattr(settings, key, value)
    engine = getattr(request.app.state, "engine", None)
    if engine is not None and hasattr(engine, "apply_admin_settings"):
        engine.apply_admin_settings(**values.model_dump())
    _save(settings, values.model_dump())
    _audit(settings, "settings.update", detail="fields=" + ",".join(values.model_dump()))
    return {"ok": True, "settings": values.model_dump()}


@router.get("/api/config")
def config(request: Request) -> dict:
    settings = request.app.state.settings
    items = []
    for name, field in Settings.model_fields.items():
        value = getattr(settings, name)
        kind = "boolean" if isinstance(value, bool) else (
            "number" if isinstance(value, (int, float)) else "text"
        )
        items.append({
            "name": name,
            "value": value,
            "type": kind,
            "description": field.description or _CONFIG_DESCRIPTIONS.get(name, ""),
            "editable": name not in _READ_ONLY,
            "restartRequired": name not in _FIELDS,
        })
    return {"items": items}


@router.put("/api/config")
def update_config(body: ConfigUpdate, request: Request) -> dict:
    unknown = set(body.values) - set(Settings.model_fields)
    locked = set(body.values) & _READ_ONLY
    if unknown:
        raise HTTPException(400, f"unknown settings: {', '.join(sorted(unknown))}")
    if locked:
        raise HTTPException(400, f"read-only settings: {', '.join(sorted(locked))}")
    current = request.app.state.settings.model_dump()
    try:
        candidate = Settings(**(current | body.values))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    normalized = {key: getattr(candidate, key) for key in body.values}
    for key, value in normalized.items():
        setattr(request.app.state.settings, key, value)
    _save(request.app.state.settings, normalized)
    _audit(request.app.state.settings, "config.update", detail="fields=" + ",".join(normalized))
    return {"ok": True, "restartRequired": any(key not in _FIELDS for key in normalized)}


@router.post("/api/streams/{info_hash}/pin")
def pin_stream(info_hash: str, request: Request) -> dict:
    _validate_hash(info_hash)
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(503, "engine unavailable")
    try:
        result = engine.pin(info_hash)
    except PinSpaceError as exc:
        raise HTTPException(409, f"insufficient disk space: need {exc.needed}, free {exc.free}") from exc
    _audit(request.app.state.settings, "stream.pin", detail=f"info_hash={info_hash}")
    return {"ok": True, "pin": result}


@router.delete("/api/streams/{info_hash}/pin")
def unpin_stream(info_hash: str, request: Request) -> dict:
    _validate_hash(info_hash)
    engine = getattr(request.app.state, "engine", None)
    if engine is not None:
        engine.unpin(info_hash)
    _audit(request.app.state.settings, "stream.unpin", detail=f"info_hash={info_hash}")
    return {"ok": True}


def _validate_hash(info_hash: str) -> None:
    if len(info_hash) != 40 or any(c not in "0123456789abcdefABCDEF" for c in info_hash):
        raise HTTPException(400, "invalid info hash")


@router.delete("/api/streams/{info_hash}")
def remove_stream(info_hash: str, request: Request) -> dict:
    _validate_hash(info_hash)
    engine = getattr(request.app.state, "engine", None)
    if engine is not None:
        engine.remove(info_hash)
    _audit(request.app.state.settings, "stream.delete", detail=f"info_hash={info_hash}")
    return {"ok": True}


@router.post("/api/cache/remove")
def remove_cached_content(body: CacheRemove, request: Request) -> dict:
    name = body.name
    if (not name or name in (".", "..") or os.path.basename(name) != name
            or name in cachemod.PROTECTED):
        raise HTTPException(400, "invalid cache entry name")
    engine = getattr(request.app.state, "engine", None)
    if engine is not None:
        info_hash = engine.name_to_hash().get(name)
        if info_hash:
            engine.remove(info_hash)
    cachemod._remove(os.path.join(request.app.state.settings.cache_root, name))
    _audit(request.app.state.settings, "cache.delete", detail=f"name={name!r}")
    return {"ok": True}


def _finish_update(command: str, root: Path) -> None:
    marker = root / "admin-update.running"
    log = root / "admin-update.log"
    marker.write_text(str(time.time()), encoding="utf-8")
    try:
        with log.open("w", encoding="utf-8") as output:
            output.write(f"DEBUG update started at {datetime.now(UTC).isoformat()}\n")
            output.write("DEBUG operator-configured update command launched\n")
            output.flush()
            subprocess.run(command, shell=True, stdout=output, stderr=subprocess.STDOUT,
                           check=False, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.write_text(str(exc), encoding="utf-8")
    finally:
        with log.open("a", encoding="utf-8") as output:
            output.write(f"DEBUG update finished at {datetime.now(UTC).isoformat()}\n")
        marker.unlink(missing_ok=True)


@router.post("/api/update", status_code=202)
def execute_update(request: Request) -> dict:
    command = os.getenv("STREMIOSRV_ADMIN_UPDATE_COMMAND", "").strip()
    if not command:
        raise HTTPException(503, "update command is not configured")
    root = Path(request.app.state.settings.cache_root)
    if (root / "admin-update.running").exists():
        raise HTTPException(409, "update already running")
    threading.Thread(target=_finish_update, args=(command, root), daemon=True).start()
    _audit(request.app.state.settings, "software.update")
    return {"ok": True, "message": "update started; settings volume will be preserved"}


@router.post("/api/restart", status_code=202)
def restart_server(request: Request) -> dict:
    # Stop uvicorn, not PID 1. Linux gives PID 1 special signal semantics and a shell running as
    # init may ignore SIGTERM. entrypoint.sh is waiting for this uvicorn process; when it exits the
    # shell exits too, Docker stops the remaining nginx process, and `restart: unless-stopped`
    # recreates the service.
    _audit(request.app.state.settings, "server.restart", detail="logs=clear")
    _clear_logs(Path(request.app.state.settings.cache_root))
    threading.Thread(target=_restart_process, args=(os.getpid(),), daemon=True).start()
    return {"ok": True, "message": "restart requested"}


def _restart_process(pid: int) -> None:
    time.sleep(0.8)  # allow the HTTP 202 response to reach the browser before the process exits
    os.kill(pid, signal.SIGTERM)


@router.get("/api/logs")
def logs(request: Request, source: str = "application", lines: int = 300) -> dict:
    if source not in _LOG_SOURCES:
        raise HTTPException(400, "unknown log source")
    lines = max(10, min(lines, 1000))
    relative, label = _LOG_SOURCES[source]
    path = Path(request.app.state.settings.cache_root) / relative
    content = _tail(path, lines)
    return {
        "source": source,
        "label": label,
        "lines": content,
        "lineCount": len(content),
        "debug": bool(request.app.state.settings.debug_logs),
        "updatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "availableSources": [
            {"id": key, "label": value[1]} for key, value in _LOG_SOURCES.items()
        ],
    }


@router.post("/api/logs/clear")
def clear_logs(body: LogClear, request: Request) -> dict:
    root = Path(request.app.state.settings.cache_root)
    cleared = _clear_logs(root, body.source)
    # Keep one trace in the audit source when another source is cleared. Clean-all remains empty.
    if body.source and body.source != "admin":
        _audit(request.app.state.settings, "logs.clear", detail=f"source={body.source}")
    return {"ok": True, "cleared": cleared}


@router.get("/api/qr.svg", include_in_schema=False)
def qr_svg() -> Response:
    """Generate the connection QR locally; a private LAN URL is never sent to a third party."""
    output = BytesIO()
    segno.make(_urls()["streamingServer"], error="m").save(
        output, kind="svg", scale=5, border=2, dark="#101115", light="#ffffff"
    )
    return Response(output.getvalue(), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})

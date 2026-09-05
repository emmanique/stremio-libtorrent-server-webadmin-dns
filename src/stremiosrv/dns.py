"""Container DNS configuration selected through Web Admin."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def apply_dns_server(server, resolv_conf: Path = Path("/etc/resolv.conf")) -> bool:
    """Replace resolver entries while preserving Docker search/options directives.

    Docker regenerates resolv.conf whenever the container is created. Running this after the saved
    settings are loaded makes the Web Admin choice effective again on every application restart.
    """
    if server is None or not str(server).strip():
        return False
    try:
        lines = resolv_conf.read_text(encoding="utf-8").splitlines()
        retained = [line for line in lines if not line.lstrip().startswith("nameserver ")]
        content = "\n".join([f"nameserver {server}", *retained]).rstrip() + "\n"
        resolv_conf.write_text(content, encoding="utf-8")
    except OSError as exc:
        log.error("Could not apply DNS server %s: %s", server, exc)
        return False
    log.info("Container DNS resolver configured as %s", server)
    return True

from pathlib import Path

from stremiosrv.dns import apply_dns_server


def test_apply_dns_replaces_nameservers_and_preserves_options(tmp_path: Path):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 127.0.0.11\nsearch local\noptions ndots:0\n")
    assert apply_dns_server("1.1.1.1", resolv) is True
    assert resolv.read_text() == "nameserver 1.1.1.1\nsearch local\noptions ndots:0\n"


def test_empty_dns_keeps_container_configuration(tmp_path: Path):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 127.0.0.11\n")
    assert apply_dns_server(None, resolv) is False
    assert resolv.read_text() == "nameserver 127.0.0.11\n"

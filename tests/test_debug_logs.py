from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_uvicorn_and_nginx_support_normal_and_debug_profiles():
    entrypoint = (ROOT / "docker/entrypoint.sh").read_text()
    nginx = (ROOT / "docker/nginx-allinone.conf").read_text()
    assert 'APP_LOG_LEVEL="debug"' in entrypoint
    assert 'APP_LOG_LEVEL="info"' in entrypoint
    assert 'APP_ACCESS_LOG="--access-log"' in entrypoint
    assert 'APP_ACCESS_LOG="--no-access-log"' in entrypoint
    assert 'NGINX_LOG_LEVEL="debug"' in entrypoint
    assert 'NGINX_LOG_LEVEL="warn"' in entrypoint
    assert "error_log /dev/stderr __LOG_LEVEL__;" in nginx
    assert '"debug_logs"' in entrypoint


def test_debug_logs_are_bounded_on_restart():
    entrypoint = (ROOT / "docker/entrypoint.sh").read_text()
    assert "tail -c 5242880" in entrypoint
    assert "application.log" in entrypoint
    assert "nginx.log" in entrypoint
    assert "container.log" in entrypoint
    assert "mkfifo" in entrypoint

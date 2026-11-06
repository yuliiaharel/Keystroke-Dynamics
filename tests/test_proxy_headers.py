"""Confirms the Dockerfile's uvicorn flags (--proxy-headers
--forwarded-allow-ips=*) actually do what PARTY_LAUNCH_PLAN.md Part 2
needs: client_ip() (api/security.py) sees each real visitor's own IP
from X-Forwarded-For, not DigitalOcean App Platform's proxy address
for every request.

Needs a real uvicorn process, not TestClient: TestClient calls the
ASGI app directly, so it never exercises uvicorn's own CLI-flag-driven
proxy header handling (that's middleware uvicorn wraps the app in at
startup, based on these flags -- there's no way to reach it by
importing keystroke_dynamics.main:app directly).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import httpx
import pytest

from keystroke_dynamics.config import settings


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def proxy_aware_server() -> Iterator[str]:
    port = _free_port()
    env = dict(os.environ)
    env.update(
        ENABLE_ACCOUNTS="false",
        DEBUG="false",
        SESSION_SECRET="a-real-production-secret",
        ALLOWED_ORIGIN="https://typingtwin.example.com",
        PUBLIC_BASE_URL="https://typingtwin.example.com",
    )
    env.pop("DATABASE_URL", None)
    # The same flags the Dockerfile's CMD uses -- this test is only
    # meaningful if it matches what actually ships.
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "keystroke_dynamics.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
            "--proxy-headers",
            "--forwarded-allow-ips=*",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                raise RuntimeError(f"uvicorn exited early (code {proc.returncode}):\n{output}")
            try:
                httpx.get(f"{base_url}/health", timeout=0.2)
                break
            except httpx.TransportError:
                time.sleep(0.1)
        else:
            raise RuntimeError("uvicorn never came up")
        yield base_url
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_forwarded_for_gives_each_real_client_its_own_rate_limit_bucket(
    proxy_aware_server: str,
) -> None:
    # If X-Forwarded-For weren't trusted, every request in this test
    # would share the one real TCP peer (this test process, 127.0.0.1)
    # and client B would already be rate-limited by client A's own
    # budget -- proxy_headers/forwarded_allow_ips is what keeps them
    # separate, the same way it must for two real visitors behind
    # DigitalOcean's proxy.
    origin = {"Origin": "https://typingtwin.example.com"}

    with httpx.Client(base_url=proxy_aware_server, headers=origin) as client:
        headers_a = {"X-Forwarded-For": "203.0.113.10"}
        for _ in range(settings.game_rate_limit_max_attempts):
            resp = client.post("/api/game/party/reset", headers=headers_a)
            assert resp.status_code != 429
        exhausted = client.post("/api/game/party/reset", headers=headers_a)
        assert exhausted.status_code == 429

        # A different forwarded client IP gets a fresh budget.
        headers_b = {"X-Forwarded-For": "203.0.113.20"}
        fresh = client.post("/api/game/party/reset", headers=headers_b)
        assert fresh.status_code != 429

"""api/security.py's client_ip(): DigitalOcean's own Do-Connecting-Ip
header is trusted, X-Forwarded-For is never read at all (on
DigitalOcean's platform, that header holds DigitalOcean's own ingress
address, not the client's -- see client_ip()'s docstring for the
documented source), and the ASGI connection's own peer address is the
fallback when neither is relevant.

Uses /api/game/party/reset's rate limit as an observable proxy for
"which bucket did this request land in", the same technique
tests/api/test_game.py's test_rate_limiting_blocks_after_too_many_requests
already uses: the rate-limit dependency runs before the route body on
every state-changing route, so repeatedly hitting reset is enough,
regardless of its own 204/404 outcome.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from keystroke_dynamics.game.rate_limit import game_rate_limiter
from keystroke_dynamics.main import app


def test_do_connecting_ip_header_is_trusted(client: TestClient) -> None:
    headers_a = {"Do-Connecting-Ip": "203.0.113.10"}
    headers_b = {"Do-Connecting-Ip": "203.0.113.20"}

    for _ in range(game_rate_limiter.max_attempts):
        resp = client.post("/api/game/party/reset", headers=headers_a)
        assert resp.status_code != 429
    exhausted = client.post("/api/game/party/reset", headers=headers_a)
    assert exhausted.status_code == 429

    # A different Do-Connecting-Ip gets its own, fresh budget.
    fresh = client.post("/api/game/party/reset", headers=headers_b)
    assert fresh.status_code != 429


def test_spoofed_x_forwarded_for_has_no_effect_on_the_rate_limit_bucket(
    client: TestClient,
) -> None:
    # No Do-Connecting-Ip here -- every request below shares the same
    # TestClient connection (and therefore the same real fallback
    # identity, api/security.py's peer-address path), regardless of
    # what X-Forwarded-For claims. If a client sending a fresh
    # X-Forwarded-For value on every request could each get a new
    # budget, this loop would never hit 429 -- it must.
    for i in range(game_rate_limiter.max_attempts):
        resp = client.post("/api/game/party/reset", headers={"X-Forwarded-For": f"203.0.113.{i}"})
        assert resp.status_code != 429
    still_same_bucket = client.post(
        "/api/game/party/reset", headers={"X-Forwarded-For": "203.0.113.250"}
    )
    assert still_same_bucket.status_code == 429


def test_falls_back_to_the_connection_peer_when_no_header_is_present() -> None:
    headers = {"origin": "http://testserver"}
    with TestClient(app, headers=headers, client=("203.0.113.30", 12345)) as peer_a:
        for _ in range(game_rate_limiter.max_attempts):
            resp = peer_a.post("/api/game/party/reset")
            assert resp.status_code != 429
        exhausted = peer_a.post("/api/game/party/reset")
        assert exhausted.status_code == 429

    # A different connection peer, still no Do-Connecting-Ip header,
    # gets its own fresh budget.
    with TestClient(app, headers=headers, client=("203.0.113.40", 12345)) as peer_b:
        fresh = peer_b.post("/api/game/party/reset")
        assert fresh.status_code != 429

"""Request-level security helpers with no database dependency, so the
anonymous game module (which must work with no DATABASE_URL at all --
see config.py's enable_accounts) can use the same Origin check and
rate-limiting machinery the account system uses, without importing
anything from db/.

api/deps.py re-exports require_matching_origin and rate_limited for
backward compatibility with auth.py/profile.py, which import them
from there.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, status

from keystroke_dynamics.api.rate_limit import RateLimiter
from keystroke_dynamics.config import settings


def require_matching_origin(request: Request) -> None:
    """CSRF defense for all state-changing requests: the Origin header
    must match this app's own configured origin exactly. The app sets
    no CORS headers and serves no other origin, so a missing or
    mismatched Origin always means either a cross-site request or a
    non-browser client that isn't sending one -- reject both.
    """
    origin = request.headers.get("origin")
    if origin != settings.allowed_origin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "origin mismatch")


def rate_limited(limiter: RateLimiter) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        key = client_ip(request)
        if not limiter.allow(key):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")

    return dependency


#: DigitalOcean App Platform's own header for the real client IP --
#: added by DigitalOcean's own ingress, which sits in front of every
#: request this app ever receives (there is no other way to reach the
#: container). Confirmed from DigitalOcean's own documentation, not
#: assumed: "App Platform adds a do-connecting-ip HTTP header that
#: contains the client's IP address... App Platform uses [X-Forwarded-For]
#: for the IP address of the DigitalOcean ingress server that forwarded
#: the request to your app" -- i.e. X-Forwarded-For on this platform
#: holds DigitalOcean's *own* address, not the client's, and is never
#: usable for this at all, trusted-proxy count or not.
#: https://docs.digitalocean.com/support/where-can-i-find-the-client-ip-address-of-a-request-connecting-to-my-app/
_DO_CONNECTING_IP_HEADER = "do-connecting-ip"


def client_ip(request: Request) -> str:
    """The key rate limiting buckets by.

    Prefers DigitalOcean's own Do-Connecting-Ip header (see above) when
    present. Never reads X-Forwarded-For: a client can set that header
    to anything, and -- unlike Do-Connecting-Ip -- nothing stops a
    forwarded value the client supplied from reaching this app, so
    trusting it (directly, or indirectly through a proxy-aware server
    setting that reads it) would let a client pick its own rate-limit
    identity at will, including someone else's.

    Falls back to the ASGI connection's own peer address when
    Do-Connecting-Ip isn't present -- local development, tests, or any
    host other than DigitalOcean App Platform. That fallback is itself
    never attacker-controlled (it's the literal TCP peer, not a
    header), so it's always safe, just not meaningful behind a real
    proxy that doesn't set Do-Connecting-Ip.
    """
    do_connecting_ip = request.headers.get(_DO_CONNECTING_IP_HEADER)
    if do_connecting_ip:
        return do_connecting_ip
    return request.client.host if request.client else "unknown"

"""Request body size cap.

Checks the Content-Length header before the body is read, so an
oversized request is rejected cheaply without buffering it. A client
that lies about Content-Length or doesn't send one (e.g. chunked
transfer) isn't caught by this -- it's a cheap first line of defense
against accidental or casual oversized payloads, not a hard guarantee;
core.events.validate's max_events is what actually bounds how much
work a request can make the app do.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send


class MaxBodySizeMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        content_length = request.headers.get("content-length")
        if content_length is not None and content_length.isdigit():
            if int(content_length) > self.max_bytes:
                response = Response("request body too large", status_code=413)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)

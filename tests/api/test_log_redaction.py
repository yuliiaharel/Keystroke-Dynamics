"""Room codes never reach the request log in full
(docs/plans/active/ROOMS_PLAN.md Phase 1 section 4)."""

from __future__ import annotations

import logging

import pytest

from keystroke_dynamics.api.log_redaction import RoomCodeRedactingFilter, redact_room_code


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/r/ABCDEFGH", "/r/AB******"),
        ("/r/abcd-efgh", "/r/ab******"),
        ("/r/ABCDEFGH?utm_source=x", "/r/AB******?utm_source=x"),
        ("/api/game/rooms/ABCDEFGH/join", "/api/game/rooms/AB******/join"),
        # Paths with no code in them are left alone.
        ("/api/game/room", "/api/game/room"),
        ("/api/game/room/players/3f2a", "/api/game/room/players/3f2a"),
        ("/static/js/party.js", "/static/js/party.js"),
        ("/", "/"),
    ],
)
def test_redact_room_code(path: str, expected: str) -> None:
    assert redact_room_code(path) == expected


def test_the_access_log_line_never_contains_the_full_code() -> None:
    # The exact shape uvicorn's access logger emits.
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:5000", "POST", "/api/game/rooms/ABCDEFGH/join", "1.1", 200),
        exc_info=None,
    )
    assert RoomCodeRedactingFilter().filter(record) is True
    line = record.getMessage()
    assert "ABCDEFGH" not in line
    assert line == '127.0.0.1:5000 - "POST /api/game/rooms/AB******/join HTTP/1.1" 200'


def test_the_filter_is_installed_on_uvicorns_access_logger() -> None:
    import keystroke_dynamics.main  # noqa: F401  (installs it on import)

    filters = logging.getLogger("uvicorn.access").filters
    assert any(isinstance(f, RoomCodeRedactingFilter) for f in filters)

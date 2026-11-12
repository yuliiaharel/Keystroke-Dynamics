"""Keeps full room codes out of the server's request log.

A room code is the only key to its room
(docs/plans/active/ROOMS_PLAN.md: "Don't log full room codes in
application logs"), and it travels in the URL of both /r/{code} and
/api/game/rooms/{code}/join -- which uvicorn's access log would
otherwise print in full on every request.
"""

from __future__ import annotations

import logging
import re

#: The code segment of the two room URLs, whatever was typed there
#: (valid or not -- a near-miss is worth hiding too).
_ROOM_CODE_IN_PATH = re.compile(r"(/r/|/api/game/rooms/)([^/?\s]{2})[^/?\s]+")

#: Position of the request path in uvicorn's access-log arguments:
#: (client_addr, method, full_path, http_version, status_code).
_PATH_ARG_INDEX = 2


def redact_room_code(path: str) -> str:
    """Keeps the first two characters, enough to tell two rooms apart
    when reading a log, and nothing a room could be joined with."""
    return _ROOM_CODE_IN_PATH.sub(r"\1\2******", path)


class RoomCodeRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > _PATH_ARG_INDEX:
            path = args[_PATH_ARG_INDEX]
            if isinstance(path, str):
                record.args = (
                    *args[:_PATH_ARG_INDEX],
                    redact_room_code(path),
                    *args[_PATH_ARG_INDEX + 1 :],
                )
        return True


def install_room_code_redaction() -> None:
    logging.getLogger("uvicorn.access").addFilter(RoomCodeRedactingFilter())

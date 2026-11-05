"""Request/response schemas: the wire format. Converts to/from
core.events.KeyEvent and core.scoring.ScoreResult at the boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from keystroke_dynamics.core.events import KeyEvent
from keystroke_dynamics.core.scoring import ScoreResult

USERNAME_PATTERN = r"^[A-Za-z0-9_-]{3,32}$"


class KeyEventSchema(BaseModel):
    code: str
    action: Literal["down", "up"]
    t_ms: float

    def to_core(self) -> KeyEvent:
        return KeyEvent(code=self.code, action=self.action, t_ms=self.t_ms)


class RegisterRequest(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=1, max_length=256)
    #: Optional: if included, scored against the user's profile and
    #: returned as a signal alongside a successful login. Never gates
    #: whether login itself succeeds.
    sample: list[KeyEventSchema] | None = None


class SampleRequest(BaseModel):
    events: list[KeyEventSchema]


class VerifyRequest(BaseModel):
    events: list[KeyEventSchema]


class TypingResultSchema(BaseModel):
    decision: str
    score: float | None
    compared_features: int

    @classmethod
    def from_core(cls, result: ScoreResult) -> TypingResultSchema:
        return cls(
            decision=result.decision.value,
            score=result.score,
            compared_features=result.compared_features,
        )


class LoginResponse(BaseModel):
    typing_result: TypingResultSchema | None = None


class SamplesResponse(BaseModel):
    sample_count: int

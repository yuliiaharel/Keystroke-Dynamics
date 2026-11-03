"""Argon2id password hashing."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

# Hashed once at import time, for a password that will never be
# submitted for real. Verifying against this costs about the same CPU
# time as verifying a real hash, so login's response time doesn't
# itself reveal whether a username exists (an unknown user takes
# roughly as long to reject as a wrong password for a real one).
_DUMMY_HASH = _hasher.hash("not-a-real-password-used-only-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False


def verify_password_or_dummy(password_hash: str | None, password: str) -> bool:
    """Same cost whether password_hash is real or the user doesn't
    exist (None) -- see _DUMMY_HASH. Always False when password_hash
    is None, since _DUMMY_HASH matches no real password."""
    return verify_password(password_hash or _DUMMY_HASH, password)

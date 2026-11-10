"""Room codes: format, normalization, and that they're drawn from the
whole alphabet (docs/plans/active/ROOMS_PLAN.md Phase 1)."""

from __future__ import annotations

import pytest

from keystroke_dynamics.game.codes import (
    CODE_ALPHABET,
    CODE_LENGTH,
    generate_code,
    normalize_code,
)


def test_alphabet_has_no_lookalike_characters() -> None:
    assert CODE_ALPHABET == "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    assert not set(CODE_ALPHABET) & set("IO01")
    assert len(set(CODE_ALPHABET)) == 32


def test_generated_codes_are_eight_characters_from_the_alphabet() -> None:
    codes = [generate_code() for _ in range(500)]
    assert all(len(code) == CODE_LENGTH for code in codes)
    assert all(set(code) <= set(CODE_ALPHABET) for code in codes)
    # 500 draws from 32^8 colliding would mean the generator is broken.
    assert len(set(codes)) == 500
    # Every character gets used -- not, say, letters only.
    assert set("".join(codes)) == set(CODE_ALPHABET)


def test_a_generated_code_normalizes_to_itself() -> None:
    code = generate_code()
    assert normalize_code(code) == code


@pytest.mark.parametrize(
    "raw",
    [
        "ABCDEFGH",
        "abcdefgh",
        "ABCD-EFGH",
        "abcd-efgh",
        " abcd efgh ",
        "AbCd-eFgH",
        "A-B-C-D-E-F-G-H",
    ],
)
def test_normalize_accepts_any_case_dashes_and_spaces(raw: str) -> None:
    assert normalize_code(raw) == "ABCDEFGH"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "ABCDEFG",  # too short
        "ABCDEFGHJ",  # too long
        "ABCDEFG1",  # 1 is not in the alphabet
        "ABCDEFG0",
        "ABCDEFGI",
        "ABCDEFGO",
        "ABCD_EFG",
        "ABCDEFGÉ",
        "../../etc",
    ],
)
def test_normalize_rejects_anything_that_cannot_be_a_code(raw: str) -> None:
    assert normalize_code(raw) is None

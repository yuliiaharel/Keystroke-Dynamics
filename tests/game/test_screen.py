"""game/screen.py: the four screen size buckets."""

from __future__ import annotations

import pytest

from keystroke_dynamics.game.screen import SCREEN_SIZES, screen_size_bucket


@pytest.mark.parametrize(
    ("viewport_width", "bucket"),
    [
        (1, "small"),
        (320, "small"),  # the narrowest width the game supports
        (359, "small"),
        (360, "medium"),
        (375, "medium"),
        (390, "medium"),
        (393, "medium"),
        (399, "medium"),
        (400, "large"),
        (412, "large"),
        (430, "large"),
        (479, "large"),
        (480, "xlarge"),
        (768, "xlarge"),  # a tablet
        (1366, "xlarge"),  # a touchscreen laptop
        (20_000, "xlarge"),
    ],
)
def test_screen_size_bucket(viewport_width: int, bucket: str) -> None:
    assert screen_size_bucket(viewport_width) == bucket


def test_there_are_exactly_four_buckets() -> None:
    assert SCREEN_SIZES == ("small", "medium", "large", "xlarge")
    assert {screen_size_bucket(w) for w in range(1, 2000)} == set(SCREEN_SIZES)


def test_the_plans_three_test_widths_fall_in_three_different_buckets() -> None:
    assert [screen_size_bucket(w) for w in (320, 390, 430)] == ["small", "medium", "large"]

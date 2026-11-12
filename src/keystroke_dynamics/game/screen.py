"""The screen size bucket saved with a touch attempt's scores
(docs/plans/active/MOBILE_PLAN.md, open decision 5). Key size can
change where taps land, so shared scores record roughly how wide the
phone was -- one of four buckets, never the width itself.
"""

from __future__ import annotations

from typing import Literal, get_args

ScreenSize = Literal["small", "medium", "large", "xlarge"]

SCREEN_SIZES: tuple[ScreenSize, ...] = get_args(ScreenSize)

#: Each bucket's upper edge, in CSS pixels of viewport width, not
#: included in the bucket. Anything at or past the last edge is
#: "xlarge". The edges sit between the common phone widths rather
#: than on them:
#: - small: under 360 (320 and 340-wide phones, the narrowest the
#:   game supports)
#: - medium: 360 to 399 (most phones: 360, 375, 390, 393)
#: - large: 400 to 479 (large phones: 402, 412, 414, 428, 430, 440)
#: - xlarge: 480 and up (tablets, touchscreen laptops, a phone held
#:   sideways)
_UPPER_EDGES: tuple[tuple[ScreenSize, int], ...] = (
    ("small", 360),
    ("medium", 400),
    ("large", 480),
)


def screen_size_bucket(viewport_width: int) -> ScreenSize:
    for bucket, upper_edge in _UPPER_EDGES:
        if viewport_width < upper_edge:
            return bucket
    return "xlarge"

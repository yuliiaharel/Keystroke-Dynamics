"""The opt-in score-sharing checkbox's wording and version
(PARTY_LAUNCH_PLAN.md section 10): "show an unchecked option: 'Share
my scores to help test this'. Explain in one or two lines what is
stored... Record a consent_version on each row, and change it if the
wording changes materially."

CONSENT_LABEL/CONSENT_EXPLANATION are the actual copy the frontend
shows next to the checkbox (game/schemas.py exposes both in PartyView
so the frontend never carries its own, possibly-stale copy);
CONSENT_VERSION is the version stamped onto every row recorded under
it. Bump CONSENT_VERSION in the same change that edits either string
in any way that changes what a player is actually agreeing to -- not
for a pure typo fix.
"""

from __future__ import annotations

CONSENT_VERSION = "1"

CONSENT_LABEL = "Share my scores to help test this"

CONSENT_EXPLANATION = (
    "Stores a few numbers about this result -- pace, how close it came to "
    "the limit, and whether it passed -- never your name, your keystrokes, "
    "or your IP address. Your attempts in this party are grouped under a "
    "random ID that isn't linked to your name."
)

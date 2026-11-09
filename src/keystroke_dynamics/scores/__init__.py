"""Opt-in score collection (docs/plans/done/PARTY_LAUNCH_PLAN.md section 10): a
separate, optional Postgres database for anonymized, consent-gated
attempt scores, written in the background so no request ever waits on
it. Entirely independent of db/ (the account system's database) and
of game/ (which must keep working with no database at all) -- see
config.py's scores_database_url.
"""

from __future__ import annotations

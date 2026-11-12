"""allow the touch line and grip mode in score_attempts

Revision ID: 9d5b3e6a2c81
Revises: 7c2e9a4f1b3d
Create Date: 2026-11-12 12:00:00.000000

Widens two CHECK constraints for touch rooms
(docs/plans/active/MOBILE_PLAN.md Phase 1 section 6): line_id may now
be 'touch', and mode may now be 'grip'. Every value allowed before is
still allowed, so every existing row still satisfies both.

Both changes happen in one ALTER TABLE, so there is never a moment
with either constraint missing. Postgres checks the existing rows
against the new constraints as it adds them, under a lock that blocks
writes for the length of one scan of the table -- well under a second
at this table's size, and a blocked insert only waits in the app's
background score writer.

Needs the table's owner, which the migration role is (DEPLOY.md). No
grant changes: the app role's INSERT and DELETE are on the table, not
on a list of values.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '9d5b3e6a2c81'
down_revision: Union[str, Sequence[str], None] = '7c2e9a4f1b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER TABLE score_attempts
            DROP CONSTRAINT ck_line_id,
            ADD CONSTRAINT ck_line_id
                CHECK (line_id IN ('word', 'sentence', 'long', 'touch')),
            DROP CONSTRAINT ck_mode,
            ADD CONSTRAINT ck_mode
                CHECK (mode IN ('attack', 'self', 'disguise', 'replay', 'grip'))
        """
    )


def downgrade() -> None:
    """Downgrade schema. Fails, changing nothing, if any touch-line or
    grip row exists: the narrower constraints can't hold them, and
    deleting rows is not a migration's decision to make."""
    op.execute(
        """
        ALTER TABLE score_attempts
            DROP CONSTRAINT ck_line_id,
            ADD CONSTRAINT ck_line_id
                CHECK (line_id IN ('word', 'sentence', 'long')),
            DROP CONSTRAINT ck_mode,
            ADD CONSTRAINT ck_mode
                CHECK (mode IN ('attack', 'self', 'disguise', 'replay'))
        """
    )

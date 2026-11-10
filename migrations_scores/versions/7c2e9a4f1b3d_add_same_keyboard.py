"""add same_keyboard to score_attempts

Revision ID: 7c2e9a4f1b3d
Revises: 4148bfbe4bd6
Create Date: 2026-11-09 12:00:00.000000

Nullable with no default, so existing rows keep every value they have
and simply read as "not recorded" -- adding a nullable column doesn't
rewrite the table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2e9a4f1b3d'
down_revision: Union[str, Sequence[str], None] = '4148bfbe4bd6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('score_attempts', sa.Column('same_keyboard', sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('score_attempts', 'same_keyboard')

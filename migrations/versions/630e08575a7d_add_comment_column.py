"""add comment column

Revision ID: 630e08575a7d
Revises: 90508c0dd6f9
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '630e08575a7d'
down_revision: Union[str, None] = '90508c0dd6f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('words', sa.Column('comment', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('words', 'comment')

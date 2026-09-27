"""add related column

Revision ID: c3d8f1a2b4e6
Revises: b7e21c4a9f03
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3d8f1a2b4e6'
down_revision: Union[str, None] = 'b7e21c4a9f03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'words',
        sa.Column('related', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('words', 'related')

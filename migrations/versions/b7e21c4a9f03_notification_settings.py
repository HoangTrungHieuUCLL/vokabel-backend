"""notification settings

Revision ID: b7e21c4a9f03
Revises: a1c93f5be207
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7e21c4a9f03'
down_revision: Union[str, None] = 'a1c93f5be207'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notification_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slots', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        # One row only: the app has one user, and a second row would make
        # "the current settings" ambiguous.
        sa.CheckConstraint('id = 1', name='ck_notification_settings_single_row'),
    )


def downgrade() -> None:
    op.drop_table('notification_settings')

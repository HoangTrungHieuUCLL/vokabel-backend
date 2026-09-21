"""push subscriptions and spotlights

Revision ID: a1c93f5be207
Revises: f5d546f60bc5
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1c93f5be207'
down_revision: Union[str, None] = 'f5d546f60bc5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'push_subscriptions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('p256dh', sa.Text(), nullable=False),
        sa.Column('auth', sa.Text(), nullable=False),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('failure_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint', name='uq_push_subscriptions_endpoint'),
    )

    op.create_table(
        'spotlights',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('slot_date', sa.Date(), nullable=False),
        sa.Column('slot', sa.String(length=5), nullable=False),
        sa.Column('word_id', sa.BigInteger(), nullable=False),
        sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=False),
        sa.Column('pushed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['word_id'], ['words.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slot_date', 'slot', name='uq_spotlights_date_slot'),
    )
    op.create_index('ix_spotlights_scheduled_for', 'spotlights', ['scheduled_for'])
    op.create_index('ix_spotlights_word_id', 'spotlights', ['word_id'])


def downgrade() -> None:
    op.drop_index('ix_spotlights_word_id', table_name='spotlights')
    op.drop_index('ix_spotlights_scheduled_for', table_name='spotlights')
    op.drop_table('spotlights')
    op.drop_table('push_subscriptions')

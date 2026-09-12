"""initial words table

Revision ID: 90508c0dd6f9
Revises:
Create Date: 2026-09-12 21:42:46.339181

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '90508c0dd6f9'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table('words',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('word', sa.Text(), nullable=False),
    sa.Column('search_key', sa.Text(), nullable=False),
    sa.Column('type', sa.Text(), nullable=False),
    sa.Column('meaning', sa.Text(), nullable=False),
    sa.Column('example', sa.Text(), nullable=True),
    sa.Column('attrs', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('tags', sa.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('is_hard', sa.Boolean(), nullable=False),
    sa.Column('hard_since', sa.DateTime(timezone=True), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('interval_days', sa.Float(), nullable=False),
    sa.Column('ease', sa.Float(), nullable=False),
    sa.Column('reps', sa.Integer(), nullable=False),
    sa.Column('lapses', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_index(
        'words_dedup', 'words', ['search_key', 'type'], unique=True,
        postgresql_where=sa.text('deleted_at IS NULL'),
    )
    op.execute(
        "CREATE INDEX words_trgm ON words USING GIN (search_key gin_trgm_ops)"
    )
    op.create_index('words_updated', 'words', ['updated_at'], unique=False)
    op.create_index(
        'words_hard', 'words', ['id'], unique=False,
        postgresql_where=sa.text('is_hard AND deleted_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('words_hard', table_name='words')
    op.drop_index('words_updated', table_name='words')
    op.drop_index('words_trgm', table_name='words')
    op.drop_index('words_dedup', table_name='words')
    op.drop_table('words')

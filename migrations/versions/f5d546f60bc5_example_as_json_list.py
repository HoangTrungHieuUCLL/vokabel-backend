"""example sentences as a JSONB list

Revision ID: f5d546f60bc5
Revises: 630e08575a7d
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f5d546f60bc5'
down_revision: Union[str, None] = '630e08575a7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE words
        ALTER COLUMN example TYPE JSONB USING (
            CASE WHEN example IS NULL OR example = ''
                THEN '[]'::jsonb
                ELSE jsonb_build_array(jsonb_build_object('de', example, 'meaning', ''))
            END
        )
        """
    )
    op.execute("ALTER TABLE words ALTER COLUMN example SET DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE words ALTER COLUMN example SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE words ALTER COLUMN example DROP NOT NULL")
    op.execute("ALTER TABLE words ALTER COLUMN example DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE words
        ALTER COLUMN example TYPE TEXT USING (
            CASE WHEN jsonb_array_length(example) = 0
                THEN NULL
                ELSE example->0->>'de'
            END
        )
        """
    )

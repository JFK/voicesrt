"""add audio_path to jobs

Revision ID: d4f8a2b6c1e9
Revises: 7a2b5d55730d
Create Date: 2026-05-16 04:50:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f8a2b6c1e9"
down_revision: Union[str, None] = "7a2b5d55730d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("audio_path", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "audio_path")

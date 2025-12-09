"""merge heads

Revision ID: fa78a0ace932
Revises: 6_manual_create_verses, 7_create_bible_schema_and_verses
Create Date: 2025-12-07 03:21:34.395700

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa78a0ace932'
down_revision: Union[str, Sequence[str], None] = ('6_manual_create_verses', '7_create_bible_schema_and_verses')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

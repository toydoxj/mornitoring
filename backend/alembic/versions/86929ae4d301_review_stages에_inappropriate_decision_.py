"""review_stages에 inappropriate_decision 컬럼 추가

Revision ID: 86929ae4d301
Revises: 65678b8e44dc
Create Date: 2026-04-17 18:13:48.589542

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '86929ae4d301'
down_revision: Union[str, Sequence[str], None] = '65678b8e44dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    inappropriate_decision = sa.Enum(
        "PENDING",
        "CONFIRMED_SERIOUS",
        "CONFIRMED_SIMPLE",
        "EXCLUDED",
        name="inappropriatedecision",
    )
    inappropriate_decision.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "review_stages",
        sa.Column("inappropriate_decision", inappropriate_decision, nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("review_stages", "inappropriate_decision")
    sa.Enum(name="inappropriatedecision").drop(op.get_bind(), checkfirst=True)

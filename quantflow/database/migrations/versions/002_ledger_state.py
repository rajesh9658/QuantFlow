"""Persist FIFO lots, fees, tax reserves and fill deduplication on recovery."""

import sqlalchemy as sa
from alembic import op

revision = "002_ledger_state"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("portfolio", sa.Column("ledger_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("portfolio") as table:
        table.drop_column("ledger_state")

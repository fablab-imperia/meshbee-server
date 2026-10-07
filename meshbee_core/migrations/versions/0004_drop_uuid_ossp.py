"""Drop the unused uuid-ossp extension.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07

`init.sql` created it from the start, but no column, default or query ever
called it: every key is a SERIAL/BIGSERIAL or a node id.

No CASCADE: if an install has grown something that depends on it, Postgres
refuses with the dependency named, and nothing is dropped with it.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql('DROP EXTENSION IF EXISTS "uuid-ossp"')


def downgrade() -> None:
    op.get_bind().exec_driver_sql('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

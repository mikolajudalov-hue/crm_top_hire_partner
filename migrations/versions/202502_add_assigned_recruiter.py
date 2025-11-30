"""Add assigned_recruiter_id to users

Revision ID: 202502_add_assigned_recruiter
Revises: None
Create Date: 2025-11-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "202502_add_assigned_recruiter"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("assigned_recruiter_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_assigned_recruiter",
        "users",
        "users",
        ["assigned_recruiter_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_assigned_recruiter", "users", type_="foreignkey")
    op.drop_column("users", "assigned_recruiter_id")

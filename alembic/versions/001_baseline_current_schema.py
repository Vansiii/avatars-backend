"""baseline_current_schema

Revision ID: 001
Revises:
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("credits_limit", sa.Integer(), server_default="10"),
        sa.Column("credits_used", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    # --- styles ---
    op.create_table(
        "styles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("base_prompt", sa.Text(), nullable=True),
        sa.Column("preview_url", sa.String(), nullable=True),
        sa.Column("tier_required", sa.String(), server_default="free"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    # --- generation_requests ---
    op.create_table(
        "generation_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("style", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="pending"),
        sa.Column("variations_requested", sa.Integer(), server_default="1"),
        sa.Column("variations_completed", sa.Integer(), server_default="0"),
        sa.Column("width", sa.Integer(), server_default="512"),
        sa.Column("height", sa.Integer(), server_default="512"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- generated_avatars ---
    op.create_table(
        "generated_avatars",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("style", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["request_id"], ["generation_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("generated_avatars")
    op.drop_table("generation_requests")
    op.drop_table("styles")
    op.drop_table("users")

"""Group certificates into admin-ordered categories.

Purely additive: a new table, and one nullable column on `achievements`.
Nothing existing is rewritten, so every current row stays valid and
uncategorised until somebody files it. The downgrade drops both again.

The shape deliberately mirrors `skill_categories`, which already does this
job for skills — a named bucket the admin orders by hand. `display_order`
here orders the categories; the `display_order` already on `achievements`
orders the entries inside one.

Revision ID: 0004_achievement_categories
Revises: 0003_totp_hardening
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_achievement_categories"
down_revision = "0003_totp_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "achievement_categories",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "display_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "is_visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug", name="uq_achievement_categories_slug"),
    )
    op.create_index(
        "ix_achievement_categories_display_order",
        "achievement_categories",
        ["display_order"],
    )

    # Nullable, and SET NULL on delete: removing a category must not take its
    # certificates with it.
    op.add_column(
        "achievements",
        sa.Column("category_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_achievements_category_id",
        "achievements",
        "achievement_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_achievements_category_id", "achievements", ["category_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_achievements_category_id", table_name="achievements")
    op.drop_constraint(
        "fk_achievements_category_id", "achievements", type_="foreignkey"
    )
    op.drop_column("achievements", "category_id")
    op.drop_index(
        "ix_achievement_categories_display_order",
        table_name="achievement_categories",
    )
    op.drop_table("achievement_categories")

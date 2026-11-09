"""Track notification-email delivery on contact messages.

Purely additive: six nullable-or-defaulted columns on `contact_messages` and
one index. Nothing existing is rewritten, so every current row stays valid.

Existing rows are backfilled to `email_delivery_status = 'disabled'` rather
than `'pending'`. They predate the feature, so no notification was ever
attempted for them and none should be — marking them pending would put a pile
of historical messages into the retry queue the first time it is opened.

The index exists because the admin filters on delivery status to find
failures, and that filter would otherwise scan the table.

Revision ID: 0005_contact_email_delivery
Revises: 0004_achievement_categories
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_contact_email_delivery"
down_revision = "0004_achievement_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default so the column can be NOT NULL without a separate
    # backfill pass; the default is dropped afterwards so the application,
    # not the database, decides the value for new rows.
    op.add_column(
        "contact_messages",
        sa.Column(
            "email_delivery_status",
            sa.String(length=16),
            nullable=False,
            server_default="disabled",
        ),
    )
    op.add_column(
        "contact_messages",
        sa.Column("resend_email_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "contact_messages", sa.Column("email_error", sa.Text(), nullable=True)
    )
    op.add_column(
        "contact_messages",
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "contact_messages",
        sa.Column(
            "email_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "contact_messages",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.alter_column("contact_messages", "email_delivery_status", server_default=None)
    op.alter_column("contact_messages", "email_attempts", server_default=None)

    op.create_index(
        "ix_contact_messages_email_delivery_status",
        "contact_messages",
        ["email_delivery_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contact_messages_email_delivery_status",
        table_name="contact_messages",
    )
    for column in (
        "updated_at",
        "email_attempts",
        "email_sent_at",
        "email_error",
        "resend_email_id",
        "email_delivery_status",
    ):
        op.drop_column("contact_messages", column)

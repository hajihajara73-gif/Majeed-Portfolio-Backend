"""Conversation thread for contact messages.

Purely additive: one new table. `contact_messages` is not touched — no column
added, renamed or dropped — so every existing row and every existing query
stays exactly as it was.

A separate table rather than reply columns on the parent, because a
conversation is one-to-many: the visitor writes, the owner replies, the
visitor replies again. Columns on the parent could hold only the first reply
and would have nowhere to put an inbound message.

The RFC 5322 threading headers (message_id, in_reply_to, references) are
stored as sent or received. They are what lets a mail client group the thread
and, once inbound is configured, what lets an incoming reply be matched to
its conversation by something stronger than a subject line.

Revision ID: 0006_email_conversations
Revises: 0005_contact_email_delivery
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_email_conversations"
down_revision = "0005_contact_email_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "contact_message_id",
            postgresql.UUID(as_uuid=True),
            # CASCADE: a thread is meaningless without the enquiry it hangs
            # off, and deleting a message must not orphan its replies.
            sa.ForeignKey("contact_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("from_email", sa.String(length=254), nullable=False),
        sa.Column("to_email", sa.String(length=254), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("resend_email_id", sa.String(length=128), nullable=True),
        sa.Column("message_id", sa.String(length=512), nullable=True),
        sa.Column("in_reply_to", sa.String(length=512), nullable=True),
        # Text, not String: a References header accumulates every Message-ID
        # in the thread and has no useful upper bound.
        sa.Column("references", sa.Text(), nullable=True),
        sa.Column(
            "delivery_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "sent_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "direction in ('inbound','outbound')", name="email_direction_valid"
        ),
    )

    # Defaults dropped so the application, not the database, decides the
    # value for new rows — same convention as 0005.
    op.alter_column("email_messages", "delivery_status", server_default=None)
    op.alter_column("email_messages", "attempts", server_default=None)

    # The timeline query.
    op.create_index(
        "ix_email_messages_contact_created",
        "email_messages",
        ["contact_message_id", "created_at"],
    )
    # Matching an inbound reply to its thread, and the duplicate check that
    # stops one webhook being processed twice.
    op.create_index(
        "ix_email_messages_message_id", "email_messages", ["message_id"]
    )
    op.create_index(
        "ix_email_messages_resend_email_id",
        "email_messages",
        ["resend_email_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_messages_resend_email_id", table_name="email_messages")
    op.drop_index("ix_email_messages_message_id", table_name="email_messages")
    op.drop_index("ix_email_messages_contact_created", table_name="email_messages")
    op.drop_table("email_messages")

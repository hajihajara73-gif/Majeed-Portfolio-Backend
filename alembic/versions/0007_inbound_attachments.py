"""Attachment metadata and authentication results on conversation messages.

Purely additive: two nullable JSON columns on `email_messages`. No existing
column is added to, renamed or dropped, and no other table is touched.

`attachments` holds METADATA only — sanitised filename, declared content
type, byte size and Resend's attachment id. Never the bytes: inbound mail is
attacker-controlled, and putting those bodies in the database would mean
storing untrusted binaries and leaving a download URL within reach of anyone
who could read a row. The admin fetches an attachment on demand through an
authenticated endpoint instead.

`auth_results` holds SPF/DKIM/DMARC as Resend evaluated them, so a reply that
failed authentication is visibly suspect in the timeline. It is never used to
decide which conversation a message belongs to — that is what the RFC
threading headers are for.

It also adds a PARTIAL UNIQUE INDEX closing a real race. The webhook checks
"have I stored this already?" and then inserts, and 0006 gave
`resend_email_id` a plain index, so nothing stopped two concurrent
deliveries of the same email — which is exactly what Resend's retries
produce — from both passing the check and both inserting. The check was
advisory; this makes the database the authority, and `record_inbound` turns
the resulting IntegrityError back into the same "duplicate" outcome.

Scoped to `direction = 'inbound'` deliberately. Outbound rows also carry a
`resend_email_id`, but their duplicate guard is a different mechanism with a
different failure mode, and widening the constraint to cover them would be a
separate decision rather than a fix for this race.

Revision ID: 0007_inbound_attachments
Revises: 0006_email_conversations
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_inbound_attachments"
down_revision = "0006_email_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_messages",
        sa.Column("attachments", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "email_messages",
        sa.Column("auth_results", postgresql.JSONB(), nullable=True),
    )
    # One inbound row per Resend email id. Partial, so outbound rows and rows
    # with no id are unaffected. Verified against live data first: there are
    # no existing inbound duplicates for this to fail on.
    op.create_index(
        "uq_email_messages_inbound_resend_id",
        "email_messages",
        ["resend_email_id"],
        unique=True,
        postgresql_where=sa.text("direction = 'inbound'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_email_messages_inbound_resend_id", table_name="email_messages"
    )
    op.drop_column("email_messages", "auth_results")
    op.drop_column("email_messages", "attachments")

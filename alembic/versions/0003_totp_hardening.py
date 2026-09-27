"""totp replay protection and staged re-enrolment

Two additive, nullable columns on `admin_users`. Nothing is dropped, nothing is
rewritten, and no existing row needs a value — so this is safe to apply to a
live database and safe to reverse.

  * `totp_last_counter`   — the last TOTP time-step this account used, so the
                            same one-time password cannot be accepted twice
                            (RFC 6238 §5.2).
  * `totp_pending_secret` — a secret being enrolled, kept apart from the live
                            one. Re-enrolment used to overwrite `totp_secret`
                            while `totp_enabled` stayed true, which silently
                            broke a working authenticator.

Revision ID: 0003_totp_hardening
Revises: 0002_content_schema
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_totp_hardening"
down_revision = "0002_content_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_users",
        sa.Column("totp_last_counter", sa.Integer(), nullable=True),
    )
    op.add_column(
        "admin_users",
        sa.Column("totp_pending_secret", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    # Reversible, but note the consequence: dropping `totp_last_counter`
    # discards replay state, so a code used just before the downgrade becomes
    # acceptable again for the remainder of its window.
    op.drop_column("admin_users", "totp_pending_secret")
    op.drop_column("admin_users", "totp_last_counter")

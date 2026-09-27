"""
Cryptographic primitives for admin authentication.

Everything that hashes, compares or generates a secret lives here, so the rules
are in one auditable place rather than spread across request handlers.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# Argon2id with deliberately explicit parameters rather than library defaults,
# so a dependency upgrade cannot silently weaken password hashing.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
)

# A precomputed hash of a random value. Verifying against this on a missing
# account costs the same as a real verification, so response timing does not
# reveal whether an email exists.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """
    Verify a password. Passing `None` still performs a full Argon2 verification
    against a dummy hash, so a login attempt for a non-existent account takes
    the same time as one for a real account.
    """
    target = password_hash or _DUMMY_HASH
    try:
        _hasher.verify(target, password)
    except (VerifyMismatchError, InvalidHashError, Exception):  # noqa: BLE001
        return False
    return password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses weaker parameters than current policy."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# --------------------------------------------------------------------------
# Opaque tokens (sessions, recovery codes)
# --------------------------------------------------------------------------


def generate_token(nbytes: int = 32) -> str:
    """A high-entropy, URL-safe token. This is the value the client holds."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """
    What we store. Session tokens are high-entropy random values, so a fast
    SHA-256 is appropriate — there is nothing to brute-force. The point is that
    a database leak does not yield usable live sessions.

    Do NOT use this for passwords; those go through Argon2.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# --------------------------------------------------------------------------
# Recovery codes
# --------------------------------------------------------------------------


def generate_recovery_codes(count: int = 10) -> list[str]:
    """
    Single-use codes for when the authenticator app is lost. Shown to the user
    exactly once; only their hashes are stored.
    """
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(3)}" for _ in range(count)]


# --------------------------------------------------------------------------
# TOTP
# --------------------------------------------------------------------------


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


TOTP_INTERVAL = 30


def verify_totp(secret: str, code: str, *, valid_window: int = 1) -> bool:
    """
    Verify a TOTP code.

    `valid_window=1` accepts the adjacent 30-second steps, which is the standard
    allowance for clock drift between the phone and the server. Anything larger
    materially widens the window for a replayed code.
    """
    if not code or not code.strip().isdigit():
        return False
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=valid_window)


def totp_counter(secret: str, code: str, *, valid_window: int = 1) -> int | None:
    """
    The time-step a valid code belongs to, or None if it is not valid.

    Returned so the caller can store it and refuse the same step twice — the
    replay defence RFC 6238 §5.2 asks for. The step is derived by testing each
    offset in the accepted window rather than assuming "now", because a code
    submitted at the edge of a window legitimately belongs to a neighbour.
    """
    if not code or not code.strip().isdigit():
        return None
    cleaned = code.strip()
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    for offset in range(-valid_window, valid_window + 1):
        at = now + offset * TOTP_INTERVAL
        if totp.verify(cleaned, for_time=at, valid_window=0):
            return at // TOTP_INTERVAL
    return None


# --------------------------------------------------------------------------
# Pending-2FA tokens
# --------------------------------------------------------------------------

_PENDING_SALT = "admin-pending-2fa"


def issue_pending_2fa_token(secret_key: str, admin_id: str) -> str:
    """
    Issued once a password is verified but before 2FA succeeds.

    Signed and timestamped rather than stored, because it is short-lived and
    single-purpose: it authorises exactly one action — completing the second
    factor — and nothing else.
    """
    serializer = URLSafeTimedSerializer(secret_key, salt=_PENDING_SALT)
    return serializer.dumps({"sub": admin_id, "iat": int(time.time())})


def read_pending_2fa_token(
    secret_key: str, token: str, max_age_seconds: int
) -> str | None:
    """Return the admin id, or None if the token is invalid or expired."""
    serializer = URLSafeTimedSerializer(secret_key, salt=_PENDING_SALT)
    try:
        payload = serializer.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    subject = payload.get("sub") if isinstance(payload, dict) else None
    return subject if isinstance(subject, str) else None

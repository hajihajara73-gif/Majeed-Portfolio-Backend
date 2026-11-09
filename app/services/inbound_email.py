"""
Fetching an inbound email from Resend, and making it safe to store.

The `email.received` webhook carries METADATA ONLY — an email id, the
envelope, the subject and attachment descriptions. The body is a separate,
authenticated call. That is why a read-capable key exists: the send-only key
used for sending cannot read the mailbox, and keeping them apart means a
leaked sending key still cannot read anyone's mail.

EVERYTHING THAT ARRIVES HERE IS UNTRUSTED. It came from whoever sent the
email, and anybody can send an email. So:

  * `From` and `Reply-To` are recorded but never used to decide which
    conversation a message joins. Both are trivially forged. Matching uses
    the RFC threading headers, which refer to Message-IDs this system
    minted and stored.
  * No HTML from an inbound message is ever rendered. Only the plain-text
    part reaches the admin, and it is escaped at the boundary like any
    other string.
  * Nothing in an email is executed, followed, or treated as an
    instruction. It is data.
  * Attachments are described, not downloaded, unless something explicitly
    asks for one — and then only within a size ceiling.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Bodies far beyond this are not a message, they are a payload.
TEXT_MAX = 200_000
SUBJECT_MAX = 255
ADDRESS_MAX = 254

# Attachment types the admin may download. Anything executable is absent on
# purpose, and absence is the default: the list is an allowlist, so a type
# nobody considered is refused rather than permitted.
ALLOWED_ATTACHMENT_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "text/plain",
        "text/csv",
        "application/zip",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


@dataclass
class InboundEmail:
    """One received email, already sanitised."""

    email_id: str
    from_email: str
    to_email: str
    subject: str | None
    text_body: str
    html_body: str | None
    message_id: str | None
    in_reply_to: str | None
    references: str | None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    auth_results: dict[str, Any] | None = None


def safe_filename(name: str | None) -> str:
    """
    A filename that cannot escape a directory or hide what it is.

    Path separators, traversal sequences and anything outside a conservative
    character set are removed rather than replaced, and the result is forced
    to a basename. A leading dot is stripped so nothing lands hidden.
    """
    if not name:
        return "attachment"
    # Take the basename on BOTH separators: a Windows-style name arriving at
    # a POSIX host keeps its backslashes and would otherwise survive intact.
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_NAME.sub("_", base).lstrip(".")
    cleaned = cleaned[:120].strip("_") or "attachment"
    # ".." can survive the character filter; it must not survive this.
    return "attachment" if set(cleaned) <= {".", "_"} else cleaned


def _first_address(value: Any) -> str:
    """Resend gives a list for `to` and a string for `from`. Normalise."""
    if isinstance(value, list):
        return str(value[0])[:ADDRESS_MAX] if value else ""
    return str(value or "")[:ADDRESS_MAX]


def _header(headers: dict[str, Any] | None, name: str) -> str | None:
    """Case-insensitive header lookup; mail headers are not case-sensitive."""
    if not headers:
        return None
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted:
            text = str(value).strip()
            return text or None
    return None


def describe_attachments(
    raw: Any, settings: Settings
) -> list[dict[str, Any]]:
    """
    Metadata for each attachment, with a verdict on whether it may be fetched.

    Nothing is downloaded here. Each entry records what the sender claimed
    and whether that claim passes the size and type rules, so the admin can
    see "3 attachments, 1 blocked" without anything untrusted being pulled.
    """
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for item in raw[:20]:  # a sane ceiling on count, as well as size
        if not isinstance(item, dict):
            continue
        content_type = str(item.get("content_type") or "").split(";")[0].strip().lower()
        size = item.get("size")
        size = int(size) if isinstance(size, (int, float)) else None

        too_big = size is not None and size > settings.inbound_attachment_max_bytes
        wrong_type = content_type not in ALLOWED_ATTACHMENT_TYPES
        # An inline image referenced by `cid:` from the HTML body is part of
        # the message, not something the sender attached. Recorded so the
        # timeline can say "1 attachment" rather than "4" for a signature
        # logo repeated in a quoted chain.
        disposition = str(item.get("content_disposition") or "").lower()
        out.append(
            {
                "id": str(item.get("id") or "")[:128] or None,
                "filename": safe_filename(item.get("filename")),
                "content_type": content_type or "application/octet-stream",
                "size": size,
                "inline": disposition == "inline" or bool(item.get("content_id")),
                # Downloadable only if BOTH checks pass. Recorded rather than
                # decided later, so the reason is visible in the admin.
                "downloadable": not (too_big or wrong_type),
                "blocked_reason": (
                    "too large"
                    if too_big
                    else "type not allowed"
                    if wrong_type
                    else None
                ),
            }
        )
    return out


def parse_received(payload: dict[str, Any], settings: Settings) -> InboundEmail:
    """
    Turn Resend's received-email JSON into something safe to store.

    Every field is bounded and coerced. The HTML part is kept only when it
    is genuinely HTML — Resend may return `html_format: data_uri`, and a
    data URI is not markup we want to hand to anything.
    """
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}

    text_body = str(payload.get("text") or "")[:TEXT_MAX]
    html_body = payload.get("html")
    if not isinstance(html_body, str) or not html_body:
        html_body = None
    else:
        # Kept, but capped. `html_format` in the response describes how INLINE
        # IMAGES are encoded inside this markup — `data_uri` means base64 is
        # embedded in it — and is NOT a statement that the body itself is a
        # data URI, so it is not grounds for discarding the body. The fetch
        # asks for `cid` to keep those images out of the string; the cap is
        # what actually bounds the row, because the API reports `data_uri`
        # regardless when a message has no inline images at all.
        html_body = html_body[:TEXT_MAX]

    if not text_body and html_body:
        # No plain part. Strip tags crudely for the timeline rather than
        # show nothing — the stored HTML is never rendered either way.
        text_body = re.sub(r"<[^>]+>", " ", html_body)
        text_body = re.sub(r"\s+", " ", text_body).strip()[:TEXT_MAX]

    subject = payload.get("subject")
    subject = str(subject)[:SUBJECT_MAX] if subject else None

    auth = payload.get("authentication")
    auth_results = auth if isinstance(auth, dict) else None

    return InboundEmail(
        email_id=str(payload.get("id") or "")[:128],
        from_email=_first_address(payload.get("from")),
        to_email=_first_address(payload.get("to")),
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        # Prefer the top-level value, fall back to the header. Resend
        # provides message_id directly; in_reply_to and references only
        # exist in the header map.
        message_id=(
            str(payload.get("message_id"))[:512]
            if payload.get("message_id")
            else _header(headers, "message-id")
        ),
        in_reply_to=(_header(headers, "in-reply-to") or "")[:512] or None,
        references=_header(headers, "references"),
        attachments=describe_attachments(payload.get("attachments"), settings),
        auth_results=auth_results,
    )


def fetch(settings: Settings, email_id: str) -> InboundEmail | None:
    """
    Fetch one received email by id. Returns None rather than raising.

    A webhook that cannot be fulfilled must not take the endpoint down with
    it — Resend would simply retry a 500 forever. The caller decides what to
    tell Resend; this reports failure quietly and without the key.
    """
    if not settings.inbound_read_key:
        logger.warning("inbound fetch skipped: no read key configured")
        return None

    try:
        import resend
    except ImportError:
        logger.warning("inbound fetch skipped: resend is not installed")
        return None

    previous = resend.api_key
    try:
        # The READ key, only for the duration of this call. The sending key
        # is restored afterwards so a read can never widen what sending can
        # do, and a failure here cannot leave the wrong key in place.
        resend.api_key = settings.inbound_read_key
        # `cid` rather than the default `data_uri`: inline images stay as
        # `cid:` references instead of being base64-inlined into the HTML,
        # which keeps a message with a few embedded screenshots from arriving
        # as several megabytes of string we would then store.
        raw = resend.Emails.Receiving.get(email_id, {"html_format": "cid"})
    except Exception as error:  # noqa: BLE001
        # str(error) only: an SDK exception can carry the request it was
        # built from, and that includes the Authorization header.
        logger.warning(
            "inbound fetch failed for %s: %s", email_id, str(error)[:200]
        )
        return None
    finally:
        resend.api_key = previous

    if not isinstance(raw, dict):
        try:
            raw = dict(raw)  # the SDK may return a TypedDict-ish object
        except Exception:  # noqa: BLE001
            logger.warning("inbound fetch returned an unusable payload")
            return None

    return parse_received(raw, settings)


@dataclass
class AttachmentPayload:
    """One attachment's bytes, already checked against the rules."""

    filename: str
    content_type: str
    content: bytes


def _within_cap(response: Any, cap: int) -> bytes | None:
    """
    Read a streamed response, abandoning it the moment it exceeds the cap.

    The declared size is the sender's claim and `Content-Length` is the
    server's; neither is a guarantee of what will actually arrive. So the
    bytes are counted as they come and the connection is dropped on the chunk
    that crosses the line, rather than buffering the whole thing and
    measuring afterwards.
    """
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=65_536):
        if not chunk:
            continue
        total += len(chunk)
        if total > cap:
            logger.warning("attachment exceeded %d bytes mid-download", cap)
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def download_attachment(
    settings: Settings, email_id: str, attachment_id: str
) -> AttachmentPayload | None:
    """
    Fetch one attachment's bytes. Returns None rather than raising.

    THE SIGNED URL NEVER LEAVES THIS PROCESS. Resend hands back a temporary
    download URL; handing that to the browser would publish an unauthenticated
    link to private mail, so the bytes are pulled here and streamed on to the
    authenticated admin instead.

    Both rules are re-checked against Resend's own metadata rather than
    against what was stored at receive time: the stored row says what the
    SENDER claimed, and that is not what should authorise a download.
    """
    if not settings.inbound_read_key:
        logger.warning("attachment download skipped: no read key configured")
        return None

    try:
        import requests
        import resend
    except ImportError:
        logger.warning("attachment download skipped: dependency missing")
        return None

    cap = settings.inbound_attachment_max_bytes
    previous = resend.api_key
    try:
        resend.api_key = settings.inbound_read_key
        details = resend.Emails.Receiving.Attachments.get(email_id, attachment_id)
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "attachment metadata failed for %s/%s: %s",
            email_id,
            attachment_id,
            str(error)[:200],
        )
        return None
    finally:
        resend.api_key = previous

    meta = dict(details) if not isinstance(details, dict) else details
    content_type = str(meta.get("content_type") or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        logger.info("attachment refused: type %r not allowed", content_type[:60])
        return None

    size = meta.get("size")
    if isinstance(size, (int, float)) and size > cap:
        logger.info("attachment refused: %d bytes exceeds the cap", int(size))
        return None

    url = str(meta.get("download_url") or "")
    if not url.startswith("https://"):
        # Plain HTTP would put private mail on the wire in clear text, and
        # anything else is not a URL we were meant to follow.
        logger.warning("attachment refused: download url was not https")
        return None

    try:
        # No Authorization header: the URL is already signed, and attaching
        # the read key to a redirect we do not control would hand it over.
        with requests.get(url, stream=True, timeout=30) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > cap:
                logger.info("attachment refused: declared length exceeds the cap")
                return None
            content = _within_cap(response, cap)
    except Exception as error:  # noqa: BLE001
        # The URL is REDACTED before this reaches the log. A `requests`
        # exception message embeds the URL it failed on, and this one is a
        # signed URL carrying an access token — logging it verbatim would
        # write a working key to private mail into the application log,
        # where it would outlive the short expiry that made it safe.
        logger.warning(
            "attachment download failed: %s",
            str(error).replace(url, "<redacted download url>")[:200],
        )
        return None

    if content is None:
        return None

    return AttachmentPayload(
        filename=safe_filename(meta.get("filename")),
        content_type=content_type,
        content=content,
    )

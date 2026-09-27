"""
Upload validation and local file storage.

The rule this module exists to enforce: **never trust the filename or the
client-supplied Content-Type.** Both are attacker-controlled. What a file *is*
is decided by sniffing its leading bytes and by an explicit allow-list.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from app.models.content import MediaKind

# Allow-list, not a deny-list. A deny-list of "dangerous" extensions is a losing
# game — there is always one more (.phtml, .svgz, .htaccess, .jsp).
ALLOWED: dict[str, tuple[str, str]] = {
    # content_type: (extension, kind)
    "image/jpeg": (".jpg", MediaKind.IMAGE),
    "image/png": (".png", MediaKind.IMAGE),
    "image/webp": (".webp", MediaKind.IMAGE),
    "image/gif": (".gif", MediaKind.IMAGE),
    "image/avif": (".avif", MediaKind.IMAGE),
    "video/mp4": (".mp4", MediaKind.VIDEO),
    "video/webm": (".webm", MediaKind.VIDEO),
    "audio/mpeg": (".mp3", MediaKind.AUDIO),
    "audio/mp4": (".m4a", MediaKind.AUDIO),
    "application/pdf": (".pdf", MediaKind.DOCUMENT),
}

# SVG is deliberately excluded: it is an XML document that can carry <script>,
# so serving one from our own origin is a stored-XSS vector. Ship icons as
# code, not as uploads.

MAX_BYTES: dict[str, int] = {
    MediaKind.IMAGE: 10 * 1024 * 1024,
    MediaKind.VIDEO: 64 * 1024 * 1024,
    MediaKind.AUDIO: 20 * 1024 * 1024,
    MediaKind.DOCUMENT: 25 * 1024 * 1024,
}

# Leading bytes -> content type. Checked against the declared type; a mismatch
# is a rejection, not a correction.
MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"\xff\xf3", "audio/mpeg"),
    (b"\xff\xf2", "audio/mpeg"),
    (b"\x1aE\xdf\xa3", "video/webm"),
]

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class UploadRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StoredFile:
    storage_key: str
    kind: str
    content_type: str
    byte_size: int
    checksum: str
    original_filename: str


def sniff(data: bytes) -> str | None:
    for prefix, content_type in MAGIC:
        if data.startswith(prefix):
            return content_type
    # RIFF container: WEBP sits at offset 8.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # ISO base media (MP4/M4A): 'ftyp' at offset 4.
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand.startswith(b"M4A"):
            return "audio/mp4"
        return "video/mp4"
    return None


def safe_filename(name: str) -> str:
    """
    Strip everything that could escape the storage directory.

    Takes the basename only, so `../../etc/passwd` and
    `C:\\Windows\\system32\\x` both reduce to a leaf name, then removes any
    character outside a conservative set.
    """
    leaf = Path(name.replace("\\", "/")).name
    cleaned = SAFE_NAME.sub("-", leaf).strip("-.") or "file"
    return cleaned[:120]


def validate(filename: str, declared_type: str, data: bytes) -> tuple[str, str]:
    """
    Returns (content_type, kind), or raises UploadRejected.

    Both the declared type and the sniffed type must be allowed AND agree.
    """
    if not data:
        raise UploadRejected("empty_file", "The file is empty.")

    declared = (declared_type or "").split(";")[0].strip().lower()
    if declared not in ALLOWED:
        raise UploadRejected(
            "type_not_allowed",
            f"Files of type '{declared or 'unknown'}' are not accepted.",
        )

    sniffed = sniff(data)
    if sniffed is None:
        raise UploadRejected(
            "unrecognised_content",
            "The file's contents do not match any accepted format.",
        )
    if sniffed != declared:
        # The classic upload attack: a .php or .html payload announced as an
        # image. Correcting silently would store it; rejecting is the answer.
        raise UploadRejected(
            "content_mismatch",
            f"File contents ({sniffed}) do not match the declared type "
            f"({declared}).",
        )

    extension, kind = ALLOWED[declared]
    limit = MAX_BYTES[kind]
    if len(data) > limit:
        raise UploadRejected(
            "too_large",
            f"That file is {len(data) // 1024 // 1024} MB; the limit for "
            f"{kind} is {limit // 1024 // 1024} MB.",
        )
    return declared, kind


def store(
    root: Path, filename: str, data: bytes, content_type: str, kind: str
) -> StoredFile:
    """
    Write the file under a generated name.

    The stored name never comes from the client — a random prefix plus the
    allow-listed extension for the *verified* type. The original name is kept
    as metadata only, for display.
    """
    extension = ALLOWED[content_type][0]
    key_name = f"{secrets.token_hex(16)}{extension}"
    folder = root / "uploads" / kind
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / key_name

    # Belt and braces: the resolved path must still sit inside the root.
    if not destination.resolve().is_relative_to(root.resolve()):
        raise UploadRejected("path_error", "Refusing to write outside storage.")

    destination.write_bytes(data)

    return StoredFile(
        storage_key=f"uploads/{kind}/{key_name}",
        kind=kind,
        content_type=content_type,
        byte_size=len(data),
        checksum=hashlib.sha256(data).hexdigest(),
        original_filename=safe_filename(filename),
    )

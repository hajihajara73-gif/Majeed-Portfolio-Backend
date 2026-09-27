"""
Export a published snapshot into the public site's source tree.

This is the seam the whole architecture is built around:

    Admin  ->  Postgres  ->  publish snapshot  ->  EXPORT  ->  static build  ->  CDN

The public site never opens a database connection. It reads a JSON file that
this command wrote at build time, which is why the site keeps serving perfectly
if Neon is asleep, slow, or gone.

Two things are exported, and the second is easy to forget:

  1. `src/content/snapshot.json` — the content itself.
  2. The media files it references. Uploaded files live in
     `backend/storage/`, which the static site cannot see, so any
     `uploads/...` asset is copied into `public/uploads/...`. Without this the
     JSON would point at images that 404 in production.

Only assets marked public appear in a snapshot, so a withheld file — the DOTE
certificate scan, say — is never referenced and therefore never copied.

Usage:
    python -m app.export                 # export the live published snapshot
    python -m app.export --snapshot ID   # export one specific snapshot
    python -m app.export --from-draft    # build from the CURRENT database state
    python -m app.export --check         # report what would happen, write nothing
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.api.admin.files import PUBLIC_ROOT, STORAGE_ROOT
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.content import PublishSnapshot
from app.services import publish_service

# From configuration, so the export does not depend on the two applications
# sitting in any particular relative position. Both default to the repository
# layout: `backend/` and `frontend/` as siblings.
OUTPUT_FILE = get_settings().snapshot_output_path

# Storage prefixes that need copying, mapped to their source root. `assets/...`
# is absent on purpose: those files already live in `frontend/public/` because
# they shipped with the site.
COPY_ROOTS: dict[str, Path] = {"uploads": STORAGE_ROOT}


class ExportError(Exception):
    """Anything that should stop a build rather than ship wrong content."""


def _iter_assets(node: Any):
    """Every asset object anywhere in the snapshot, at any depth."""
    if isinstance(node, dict):
        if "url" in node and "id" in node and "kind" in node:
            yield node
        for value in node.values():
            yield from _iter_assets(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_assets(value)


def collect_media(snapshot: dict[str, Any]) -> list[str]:
    """Storage keys referenced by the snapshot, deduplicated, in stable order."""
    seen: dict[str, None] = {}
    for asset in _iter_assets(snapshot):
        url = asset.get("url")
        if isinstance(url, str) and url.startswith("/"):
            seen.setdefault(url.lstrip("/"), None)
    return list(seen)


@dataclass
class MediaResult:
    """What happened to the files a snapshot points at."""

    copied: int = 0
    already_present: int = 0
    missing: list[str] = field(default_factory=list)

    @property
    def in_place(self) -> int:
        return self.copied + self.already_present


def copy_media(keys: list[str], *, dry_run: bool = False) -> MediaResult:
    """
    Put every referenced file where the static site expects to find it.

    A missing file is reported rather than raised: the caller decides whether a
    build with a broken image is acceptable, and it is better to say which one
    is broken than to fail with no detail.
    """
    result = MediaResult()

    for key in keys:
        prefix = key.split("/", 1)[0]
        root = COPY_ROOTS.get(prefix)
        if root is None:
            # `assets/...` — shipped with the site, so it is already in
            # public/. Verify rather than assume.
            if (PUBLIC_ROOT / key).is_file():
                result.already_present += 1
            else:
                result.missing.append(key)
            continue

        source = (root / key).resolve()
        # Containment check, same reasoning as the media route: never trust a
        # stored key, even one we wrote.
        if not source.is_relative_to(root.resolve()) or not source.is_file():
            result.missing.append(key)
            continue

        destination = (PUBLIC_ROOT / key).resolve()
        if not destination.is_relative_to(PUBLIC_ROOT.resolve()):
            result.missing.append(key)
            continue

        if dry_run:
            result.copied += 1
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        # copy2 preserves mtime, so an unchanged asset does not look new to a
        # CDN or to git.
        shutil.copy2(source, destination)
        result.copied += 1

    return result


def select_snapshot(
    db: Session, *, snapshot_id: str | None, from_draft: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return `(content, metadata)` for whatever was asked for."""
    if from_draft:
        content = publish_service.build_snapshot(db)
        result = publish_service.validate_snapshot(content)
        return content, {
            "source": "draft",
            "snapshotId": None,
            "checksum": publish_service.checksum(content),
            "publishedAt": None,
            "blocking": result.blocking,
            "warnings": result.warnings,
        }

    if snapshot_id:
        row = db.get(PublishSnapshot, snapshot_id)
        if row is None:
            raise ExportError(f"No snapshot with id {snapshot_id}.")
    else:
        row = publish_service.current_snapshot(db)
        if row is None:
            raise ExportError(
                "Nothing has been published yet.\n"
                "Publish from the admin (or run with --from-draft to export the "
                "current database state for local preview)."
            )

    if row.status != "published":
        raise ExportError(
            f"Snapshot {row.id} has status '{row.status}'. Only a published "
            "snapshot may be exported."
        )

    return dict(row.content), {
        "source": "published",
        "snapshotId": str(row.id),
        "checksum": row.checksum,
        "publishedAt": row.published_at.isoformat() if row.published_at else None,
        "blocking": [],
        "warnings": [],
    }


def export(
    *,
    snapshot_id: str | None = None,
    from_draft: bool = False,
    check: bool = False,
    output: Path = OUTPUT_FILE,
) -> dict[str, Any]:
    with SessionLocal() as db:
        content, meta = select_snapshot(
            db, snapshot_id=snapshot_id, from_draft=from_draft
        )

    keys = collect_media(content)
    media = copy_media(keys, dry_run=check)

    payload = {
        # Metadata first so a diff of this file leads with what changed.
        "_meta": {**meta, "mediaFiles": len(keys)},
        **content,
    }

    if not check:
        output.parent.mkdir(parents=True, exist_ok=True)
        # Trailing newline and indentation so the file diffs like source, not
        # like a blob — this file is committed and reviewed.
        output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    return {
        "meta": meta,
        "output": str(output),
        "media_referenced": len(keys),
        "media_copied": media.copied,
        "media_in_place": media.in_place,
        "media_missing": media.missing,
        "written": not check,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.export",
        description="Export a published content snapshot into the public site.",
    )
    parser.add_argument(
        "--snapshot", help="Export this snapshot id instead of the live one."
    )
    parser.add_argument(
        "--from-draft",
        action="store_true",
        help="Build from the current database state. For local preview only — "
        "the result has not been published and may be invalid.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report what would be exported without writing anything.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    args = parser.parse_args(argv)

    try:
        outcome = export(
            snapshot_id=args.snapshot,
            from_draft=args.from_draft,
            check=args.check,
            output=args.output,
        )
    except ExportError as error:
        print(f"Export failed: {error}", file=sys.stderr)
        return 1

    meta = outcome["meta"]
    verb = "Would export" if args.check else "Exported"
    print(f"{verb} {meta['source']} snapshot {meta['snapshotId'] or '(draft)'}")
    print(f"  checksum      {meta['checksum'][:16]}…")
    print(f"  content       {outcome['output']}")
    print(
        f"  media         {outcome['media_in_place']} of "
        f"{outcome['media_referenced']} referenced files in place "
        f"({outcome['media_copied']} copied)"
    )

    for warning in meta["warnings"]:
        print(f"  warning       {warning}")

    if outcome["media_missing"]:
        print("\nMissing media — these will 404 on the live site:", file=sys.stderr)
        for key in outcome["media_missing"]:
            print(f"  - {key}", file=sys.stderr)
        return 1

    if meta["blocking"]:
        print("\nThis draft would NOT pass publish validation:", file=sys.stderr)
        for problem in meta["blocking"]:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

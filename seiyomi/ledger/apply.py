"""Ledger apply — push ledger read progress to Suwayomi library entries.

For each current library entry in Suwayomi, looks up its normalized title
in the ledger.  If the ledger knows a higher chapter, marks chapters read
up to that point.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from seiyomi.clients.suwayomi import SuwayomiClient
from seiyomi.ledger.db import LedgerDB
from seiyomi.matching.titles import normalize_title_tokens
from seiyomi.operations.read_sync import (
    compute_entry_progress_by_number,
    mark_entry_up_to_number,
)

logger = logging.getLogger("seiyomi.ledger.apply")


def _norm_key(title: str) -> str:
    return " ".join(normalize_title_tokens(title))


def apply_ledger(
    client: SuwayomiClient,
    db: LedgerDB,
    dry_run: bool = False,
    filter_title: str = "",
) -> Dict[str, int]:
    """Push ledger progress to Suwayomi.  Returns summary counters."""
    library = client.get_library_graphql() or client.get_library() or []
    if not library:
        logger.error("Library is empty or could not be fetched.")
        return {"error": 1}

    applied = 0
    skipped_no_ledger = 0
    skipped_current = 0
    rpm = 120

    for entry in library:
        mid = int(entry.get("id") or entry.get("mangaId") or 0)
        title = str(entry.get("title") or entry.get("name") or "").strip()
        if not title or not mid:
            continue
        if filter_title and filter_title.lower() not in title.lower():
            continue

        key = _norm_key(title)
        if not key:
            continue

        ledger_title = db.get_title_by_key(key)
        if not ledger_title:
            skipped_no_ledger += 1
            continue

        progress = db.get_progress(ledger_title.id)
        if not progress or progress.max_chapter <= 0:
            skipped_no_ledger += 1
            continue

        # Check current Suwayomi progress
        try:
            current = compute_entry_progress_by_number(client, mid)
        except Exception:
            current = 0.0

        if current >= progress.max_chapter:
            skipped_current += 1
            continue

        logger.info(
            "  APPLY '%s' (id=%d): ch %.0f -> %.0f%s",
            title, mid, current, progress.max_chapter,
            " (dry-run)" if dry_run else "",
        )

        if not dry_run:
            try:
                mark_entry_up_to_number(client, mid, progress.max_chapter, rpm=rpm, dry_run=False)
            except Exception as exc:
                logger.error("  ERROR applying to id=%d: %s", mid, exc)
        applied += 1

    summary = {
        "library_entries": len(library),
        "applied": applied,
        "skipped_no_ledger": skipped_no_ledger,
        "skipped_current": skipped_current,
    }
    logger.info(
        "Apply complete: applied=%d skipped_no_ledger=%d skipped_already_current=%d",
        summary["applied"], summary["skipped_no_ledger"], summary["skipped_current"],
    )
    return summary

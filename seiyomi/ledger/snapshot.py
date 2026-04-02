"""Ledger snapshot — scan Suwayomi and record read progress in the ledger.

This module queries the Suwayomi server for all library entries (and
optionally orphaned entries that still have read chapters) and upserts the
highest read chapter number per normalized title into the ledger DB.

Supports incremental mode: only entries whose ``latestReadChapter.lastReadAt``
is newer than the previous snapshot are fully scanned.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from seiyomi.clients.suwayomi import SuwayomiClient
from seiyomi.ledger.db import LedgerDB
from seiyomi.matching.titles import normalize_title_tokens
from seiyomi.operations.read_sync import compute_entry_progress_by_number

logger = logging.getLogger("seiyomi.ledger.snapshot")


def _norm_key(title: str) -> str:
    return " ".join(normalize_title_tokens(title))


def _fetch_orphan_manga_ids(client: SuwayomiClient, lib_ids: Set[int]) -> Set[int]:
    """Return manga IDs that have read chapters but are NOT in the library."""
    q = """query {
      chapters(condition: { isRead: true }, orderBy: ID) {
        nodes { mangaId }
      }
    }"""
    resp = client.graphql(q.strip())
    if not resp:
        return set()
    nodes = ((resp.get("data") or {}).get("chapters") or {}).get("nodes") or []
    all_read_ids = {n.get("mangaId") for n in nodes if n.get("mangaId")}
    return all_read_ids - lib_ids


def _fetch_manga_title(client: SuwayomiClient, manga_id: int) -> Optional[Dict[str, Any]]:
    """Fetch minimal info for a single manga via GQL."""
    q = """query($id: Int!) {
      manga(id: $id) { id title sourceId }
    }"""
    resp = client.graphql(q.strip(), variables={"id": manga_id})
    if not resp:
        return None
    return (resp.get("data") or {}).get("manga")


def _fetch_library_with_read_times(client: SuwayomiClient) -> List[Dict[str, Any]]:
    """Fetch library entries with latestReadChapter.lastReadAt for incremental support."""
    q = """query {
      mangas(condition: { inLibrary: true }) {
        nodes {
          id title sourceId
          latestReadChapter { lastReadAt }
        }
      }
    }"""
    resp = client.graphql(q.strip())
    if not resp or not isinstance(resp.get("data"), dict):
        return []
    nodes = (resp["data"].get("mangas") or {}).get("nodes") or []
    return [n for n in nodes if isinstance(n, dict)]


def snapshot(
    client: SuwayomiClient,
    db: LedgerDB,
    include_orphans: bool = True,
    incremental: bool = True,
) -> Dict[str, int]:
    """Scan Suwayomi and update the ledger.  Returns summary counters.

    When *incremental* is True (default), only entries whose
    ``latestReadChapter.lastReadAt`` is newer than the last snapshot are
    fully scanned.  Pass ``incremental=False`` to force a full rescan.
    """
    # Build source name lookup
    sources = client.get_sources() or []
    src_map = {int(s.get("id") or 0): s.get("name", "") for s in sources}

    # Get the cutoff time for incremental mode
    last_snapshot = ""
    if incremental:
        last_snapshot = db.get_last_snapshot_time()

    # 1. Fetch library (with read timestamps for incremental filtering)
    if incremental and last_snapshot:
        library = _fetch_library_with_read_times(client)
    else:
        library = client.get_library_graphql() or client.get_library() or []

    lib_ids = set()
    entries: List[Dict[str, Any]] = []

    skipped_incremental = 0

    for e in library:
        mid = int(e.get("id") or e.get("mangaId") or 0)
        if mid:
            lib_ids.add(mid)
        title = str(e.get("title") or e.get("name") or "").strip()
        if not title:
            continue
        sid = str(e.get("sourceId") or e.get("source_id") or "")
        sname = src_map.get(int(sid) if sid.isdigit() else 0, "")

        # Incremental: skip entries not read since last snapshot
        if incremental and last_snapshot:
            lrc = e.get("latestReadChapter") or {}
            last_read_at = str(lrc.get("lastReadAt") or "")
            if last_read_at and last_read_at <= last_snapshot:
                skipped_incremental += 1
                continue

        entries.append({
            "mid": mid, "title": title, "sourceId": sid,
            "sourceName": sname, "in_library": True,
        })

    if incremental and last_snapshot:
        logger.info("Library entries: %d total, %d changed since last snapshot, %d skipped",
                     len(lib_ids), len(entries), skipped_incremental)
    else:
        logger.info("Library entries: %d (full scan)", len(entries))

    # 2. Optionally fetch orphaned entries
    if include_orphans:
        orphan_ids = _fetch_orphan_manga_ids(client, lib_ids)
        logger.info("Orphaned manga with read chapters: %d", len(orphan_ids))
        for oid in sorted(orphan_ids):
            mdata = _fetch_manga_title(client, oid)
            if not mdata or not mdata.get("title"):
                continue
            title = str(mdata["title"]).strip()
            sid = str(mdata.get("sourceId") or "")
            sname = src_map.get(int(sid) if sid.isdigit() else 0, "")
            entries.append({
                "mid": mdata["id"], "title": title, "sourceId": sid,
                "sourceName": sname, "in_library": False,
            })

    # 3. Compute progress and upsert into ledger
    titles_created = 0
    progress_raised = 0
    entries_linked = 0

    for i, e in enumerate(entries):
        mid = e["mid"]
        title = e["title"]
        key = _norm_key(title)
        if not key:
            continue

        # Compute read progress from Suwayomi chapters
        try:
            max_ch = compute_entry_progress_by_number(client, mid)
        except Exception:
            max_ch = 0.0

        # Upsert title
        existing = db.get_title_by_key(key)
        is_new = existing is None
        title_id = db.upsert_title(key, title)
        if is_new:
            titles_created += 1

        # Record alt title
        db.add_alt_title(title_id, title, source="suwayomi")

        # Link Suwayomi entry
        chapter_count = 0
        try:
            chs = client.get_chapters_graphql(mid)
            chapter_count = len(chs) if chs else 0
        except Exception:
            pass

        db.upsert_suwayomi_entry(
            title_id=title_id,
            suwayomi_id=mid,
            source_id=e["sourceId"],
            source_name=e["sourceName"],
            in_library=e["in_library"],
            chapter_count=chapter_count,
        )
        entries_linked += 1

        # Raise progress (never lower)
        if max_ch > 0:
            if db.raise_progress(title_id, max_ch):
                progress_raised += 1
                logger.debug("  RAISE '%s' -> ch %.1f", title, max_ch)

        if (i + 1) % 100 == 0:
            logger.info("  ... processed %d / %d entries", i + 1, len(entries))

    summary = {
        "entries_scanned": len(entries),
        "titles_created": titles_created,
        "progress_raised": progress_raised,
        "entries_linked": entries_linked,
        "skipped_incremental": skipped_incremental,
    }
    logger.info(
        "Snapshot complete: scanned=%d titles_created=%d progress_raised=%d "
        "entries_linked=%d skipped_unchanged=%d",
        summary["entries_scanned"], summary["titles_created"],
        summary["progress_raised"], summary["entries_linked"],
        summary["skipped_incremental"],
    )

    # Record the snapshot timestamp for next incremental run
    db.set_last_snapshot_time()

    return summary

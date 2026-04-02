"""Cross-source read sync — copy read progress between library entries that share a title.

Typical use-case: after migrating from bato.to to AllManga, backfill read
progress from the old entries to the new ones (or vice versa).
Also recovers progress from removed/orphaned entries still in the DB.

Depends only on SuwayomiClient and read_sync helpers. No MangaDex imports.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from seiyomi.clients.suwayomi import SuwayomiClient
from seiyomi.matching.titles import normalize_title_tokens
from seiyomi.operations.read_sync import (
    compute_entry_progress_by_number,
    mark_entry_up_to_number,
)

logger = logging.getLogger("seiyomi.sync_reads_across")


def _norm_key(title: str) -> str:
    """Lowercased token-joined key for grouping titles."""
    return " ".join(normalize_title_tokens(title))


def _fetch_orphaned_donors(
    client: SuwayomiClient,
    lib_ids: Set[int],
    from_source_ids: Set[int],
    filter_title: str,
) -> List[Dict[str, Any]]:
    """Find manga entries with read chapters that are NOT in the library.

    These are leftovers from previous migrations / removals — the manga
    row was kept by Suwayomi but ``inLibrary`` is false.  Their chapter
    read-state is still in the DB and can be used as a donor.
    """
    # 1. Get all distinct mangaIds that have at least one read chapter
    q = """query {
      chapters(condition: { isRead: true }, orderBy: ID) {
        nodes { mangaId }
      }
    }"""
    resp = client.graphql(q.strip())
    if not resp:
        return []
    nodes = ((resp.get("data") or {}).get("chapters") or {}).get("nodes") or []
    read_manga_ids = {n.get("mangaId") for n in nodes if n.get("mangaId")}

    # 2. Keep only IDs NOT in the current library
    orphan_ids = read_manga_ids - lib_ids
    if not orphan_ids:
        return []

    logger.info(f"Orphaned manga with read chapters (not in library): {len(orphan_ids)}")

    # 3. Fetch title + sourceId for each orphan via GQL
    orphans: List[Dict[str, Any]] = []
    for oid in sorted(orphan_ids):
        mq = """query($id: Int!) {
          manga(id: $id) { id title sourceId }
        }"""
        mresp = client.graphql(mq.strip(), variables={"id": oid})
        if not mresp:
            continue
        mdata = ((mresp.get("data") or {}).get("manga")) or {}
        if not mdata.get("title"):
            continue
        title = str(mdata["title"]).strip()
        sid = int(mdata.get("sourceId") or 0)

        # Apply filters
        if from_source_ids and sid not in from_source_ids:
            continue
        if filter_title and filter_title.lower() not in title.lower():
            continue

        orphans.append({"id": mdata["id"], "title": title, "sourceId": sid, "_orphan": True})

    logger.info(f"Orphaned donors after filtering: {len(orphans)}")
    return orphans


def sync_reads_across_sources(
    client: SuwayomiClient,
    args: Any,
) -> int:
    """Copy read progress from entries of one source to matching entries on other sources.

    When ``--from`` is set, only entries from that source are used as the
    *donor* (source of read progress).  All other library entries with the
    same normalised title receive the progress.

    When ``--from`` is not set, for every group of same-title entries the
    highest read progress among them is propagated to all others.

    With ``--include-removed`` (default when ``--from`` is given), also
    scans manga entries that have been removed from the library but still
    have read chapters in the DB.

    Returns 0 on success.
    """
    dry_run = getattr(args, "dry_run", False)
    from_source = getattr(args, "sync_reads_from", "") or ""
    filter_title = getattr(args, "sync_reads_filter", "") or ""
    # Default include_removed to True when --from is given (most common backfill case)
    include_removed = getattr(args, "sync_reads_include_removed", bool(from_source))
    rpm = 120

    # 1. Fetch full library
    library = client.get_library_graphql() or client.get_library() or []
    if not library:
        logger.error("Library is empty or could not be fetched.")
        return 1
    logger.info(f"Library entries: {len(library)}")

    # 2. Resolve --from source IDs
    from_source_ids: Set[int] = set()
    if from_source:
        sources = client.get_sources() or []
        frags = [f.strip().lower() for f in from_source.split(",") if f.strip()]
        for src in sources:
            sname = (src.get("name") or "").lower()
            sid = int(src.get("id") or 0)
            if any(f in sname for f in frags):
                from_source_ids.add(sid)
        if not from_source_ids:
            logger.error(f"No sources matched '--from {from_source}'.")
            return 1
        # Deduplicate names for display
        matched_names = sorted({s.get("name") for s in sources if int(s.get("id") or 0) in from_source_ids})
        logger.info(f"Donor sources: {', '.join(matched_names)} ({len(from_source_ids)} source IDs)")

    # 3. Build library lookup
    lib_ids = set()
    lib_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for entry in library:
        mid = int(entry.get("id") or entry.get("mangaId") or 0)
        if mid:
            lib_ids.add(mid)
        title = str(entry.get("title") or entry.get("name") or "").strip()
        if not title:
            continue
        if filter_title and filter_title.lower() not in title.lower():
            continue
        key = _norm_key(title)
        if key:
            lib_by_key.setdefault(key, []).append(entry)

    # 4. Optionally include orphaned (removed) manga as donors
    orphan_donors: List[Dict[str, Any]] = []
    if include_removed:
        orphan_donors = _fetch_orphaned_donors(client, lib_ids, from_source_ids, filter_title)
        # Add orphans to the groups (they can only be donors, not recipients)
        for od in orphan_donors:
            key = _norm_key(od["title"])
            if key:
                lib_by_key.setdefault(key, []).append(od)

    # 5. Only keep groups with 2+ entries (otherwise nothing to sync)
    multi = {k: v for k, v in lib_by_key.items() if len(v) >= 2}
    logger.info(f"Title groups with multiple entries: {len(multi)}")

    synced = 0
    skipped = 0

    for key, entries in sorted(multi.items()):
        # Determine donor(s) and recipients
        # Recipients are always current library entries (not orphans)
        if from_source_ids:
            donors = [e for e in entries if int(e.get("sourceId") or e.get("source_id") or 0) in from_source_ids]
            recipients = [e for e in entries
                          if int(e.get("sourceId") or e.get("source_id") or 0) not in from_source_ids
                          and not e.get("_orphan")]
        else:
            donors = entries
            recipients = [e for e in entries if not e.get("_orphan")]

        if not donors or not recipients:
            continue

        # Find the highest read progress among donors
        best_progress = 0.0
        best_donor_id = 0
        donor_title = str(donors[0].get("title") or donors[0].get("name") or "")
        for d in donors:
            did = int(d.get("id") or d.get("mangaId") or 0)
            if not did:
                continue
            try:
                prog = compute_entry_progress_by_number(client, did)
            except Exception:
                prog = 0.0
            orphan_tag = " [removed]" if d.get("_orphan") else ""
            logger.debug(f"  donor '{donor_title}' id={did}{orphan_tag}: read up to ch {prog:.0f}")
            if prog > best_progress:
                best_progress = prog
                best_donor_id = did

        if best_progress <= 0:
            skipped += 1
            logger.debug(f"  SKIP '{donor_title}': no read progress found in any donor")
            continue

        # Apply to all recipients
        for r in recipients:
            rid = int(r.get("id") or r.get("mangaId") or 0)
            if not rid or rid == best_donor_id:
                continue

            # Check if recipient already has equal or higher progress
            try:
                existing = compute_entry_progress_by_number(client, rid)
            except Exception:
                existing = 0.0
            if existing >= best_progress:
                logger.info(
                    f"  SKIP '{donor_title}' (id={rid}): already at ch {existing:.0f} >= {best_progress:.0f}"
                )
                continue

            r_src_id = int(r.get("sourceId") or r.get("source_id") or 0)
            logger.info(
                f"  SYNC '{donor_title}' ch {best_progress:.0f} -> id={rid} (source={r_src_id})"
                + (" (dry-run)" if dry_run else "")
            )

            if not dry_run:
                try:
                    mark_entry_up_to_number(client, rid, best_progress, rpm=rpm, dry_run=False)
                except Exception as exc:
                    logger.error(f"  ERROR syncing id={rid}: {exc}")
            synced += 1

    logger.info(f"Sync-reads-across summary: synced={synced} skipped={skipped}")
    return 0

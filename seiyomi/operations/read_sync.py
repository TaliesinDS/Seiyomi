"""Read-progress sync operations — marks Suwayomi chapters as read.

This module depends ONLY on SuwayomiClient. It must NOT import MangaDexClient.
MangaDex read data is passed in as plain dict/list arguments so that this module
is reusable for any source, not just MangaDex.
"""
from __future__ import annotations

import logging
import math
import re
import time
from typing import Any, Dict, List, Optional, Set

from seiyomi.utils.rate_limiter import RateLimiter

from seiyomi.clients.suwayomi import SuwayomiClient

logger = logging.getLogger("seiyomi.read_sync")

# Regex for matching a MangaDex chapter UUID embedded in a chapter URL/key field
_MD_CHAPTER_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


# ---------------------------------------------------------------------------
# Low-level Suwayomi helpers (no MangaDex dependency)
# ---------------------------------------------------------------------------

def fetch_suwayomi_chapters(client: SuwayomiClient, manga_internal_id: int) -> List[Dict[str, Any]]:
    """Fetch chapter list for a manga from Suwayomi."""
    try:
        js = client.request("GET", f"/api/v1/manga/{manga_internal_id}/chapters").json()
        for key in ("chapters", "chapterList", "data"):
            if key in js and isinstance(js[key], list):
                return js[key]
        return []
    except Exception:
        return []


def extract_chapter_uuid_from_item(item: Dict[str, Any]) -> Optional[str]:
    """Extract a MangaDex chapter UUID from a Suwayomi chapter dict (URL/key fields)."""
    for field in ("url", "key", "chapterUrl", "sourceUrl"):
        v = item.get(field)
        if not v:
            continue
        m = _MD_CHAPTER_UUID_RE.search(str(v))
        if m:
            return m.group(0)
    return None


def mark_chapter_read(client: SuwayomiClient, chapter_internal_id: int) -> bool:
    """Mark a single chapter as read via Suwayomi (REST then GraphQL fallback).

    Returns True when a write-like endpoint confirmed success (200/204).
    """
    paths_to_try = [
        ("POST", f"/api/v1/chapter/{chapter_internal_id}/read", None),
        ("POST", f"/api/v1/chapters/{chapter_internal_id}/read", None),
        ("PATCH", f"/api/v1/chapter/{chapter_internal_id}", {"read": True}),
        ("PATCH", f"/api/v1/chapters/{chapter_internal_id}", {"read": True}),
        ("PUT", f"/api/v1/chapter/{chapter_internal_id}/read", None),
        ("PUT", f"/api/v1/chapters/{chapter_internal_id}/read", None),
        ("POST", "/api/v1/chapter/read", {"ids": [chapter_internal_id], "read": True}),
        ("POST", "/api/v1/chapters/read", {"ids": [chapter_internal_id], "read": True}),
        ("POST", "/api/v1/chapter/batch/read", {"ids": [chapter_internal_id], "read": True}),
        ("GET", f"/api/v1/chapter/read?id={chapter_internal_id}", None),
        ("POST", f"/api/v1/chapter/read?id={chapter_internal_id}", None),
        ("GET", f"/api/v1/chapter/{chapter_internal_id}/read", None),
    ]
    for method, path, body in paths_to_try:
        try:
            kwargs: Dict[str, Any] = {}
            if body is not None:
                kwargs["json"] = body
            r = client.request(method, path, **kwargs)
            code = r.status_code
            logger.debug(f"[read-debug] mark attempt {method} {path} -> {code}")
            if method in ("POST", "PATCH", "PUT") and code in (200, 204):
                return True
            if method == "GET" and code == 204:
                return True
        except Exception:
            continue
    # GraphQL fallback
    try:
        logger.debug(f"[read-debug] graphql attempt: updateChapters ids=[{chapter_internal_id}] isRead=true")
        mut_uc = """
        mutation UpdateChapters($ids: [Int!]!, $patch: UpdateChapterPatchInput!) {
          updateChapters(input: { ids: $ids, patch: $patch }) {
            chapters { nodes { id isRead } }
          }
        }
        """
        d_uc = client.graphql(
            mut_uc,
            {"ids": [int(chapter_internal_id)], "patch": {"isRead": True, "lastPageRead": 0}},
        )
        if d_uc and isinstance(d_uc, dict) and (d_uc.get("data") or {}).get("updateChapters"):
            logger.debug(f"[read-debug] graphql updateChapters ok for {chapter_internal_id}")
            return True

        logger.debug(f"[read-debug] graphql attempt: updateChapter id={chapter_internal_id} isRead=true")
        mut_uc1 = """
        mutation UpdateChapter($id: Int!, $patch: UpdateChapterPatchInput!) {
          updateChapter(input: { id: $id, patch: $patch }) {
            chapter { id isRead }
          }
        }
        """
        d_uc1 = client.graphql(
            mut_uc1,
            {"id": int(chapter_internal_id), "patch": {"isRead": True, "lastPageRead": 0}},
        )
        if d_uc1 and isinstance(d_uc1, dict) and (d_uc1.get("data") or {}).get("updateChapter"):
            logger.debug(f"[read-debug] graphql updateChapter ok for {chapter_internal_id}")
            return True
    except Exception:
        logger.debug(f"[read-debug] graphql error for {chapter_internal_id}")
    return False


# ---------------------------------------------------------------------------
# Chapter-number helpers (cross-source, no MangaDex dependency)
# ---------------------------------------------------------------------------

def _parse_chapter_number(item: Dict[str, Any]) -> Optional[float]:
    for k in (
        "chapterNumber", "chapter", "number",
        "realChapterNumber", "chapter_index", "chapterIndex",
        "num", "no", "chap", "chNumber", "chNum",
        "numberSort", "sort",
    ):
        v = item.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            m = re.search(r"(\d+(?:\.\d+)?)", v)
            if m:
                try:
                    return float(m.group(1))
                except Exception:
                    pass
    for k in ("name", "title"):
        v = item.get(k)
        if isinstance(v, str):
            m = re.search(r"(\d+(?:\.\d+)?)", v)
            if m:
                try:
                    return float(m.group(1))
                except Exception:
                    pass
    return None


def _build_fraction_map(numbers: List[float]) -> Dict[int, Set[int]]:
    m: Dict[int, Set[int]] = {}
    for n in numbers:
        b = int(math.floor(n + 1e-9))
        f = int(round((n - b) * 10)) if n - b > 0 else 0
        m.setdefault(b, set()).add(f)
    return m


def _is_fraction_canonical(n: float, frac_map: Dict[int, Set[int]]) -> bool:
    b = int(math.floor(n + 1e-9))
    f = int(round((n - b) * 10)) if n - b > 0 else 0
    fr = frac_map.get(b, set())
    if f == 0:
        return True
    if 1 <= f <= 4:
        return True
    if f == 5:
        return any(x in fr for x in (1, 2, 3, 4)) or any(x >= 6 for x in fr)
    return True


def compute_entry_progress_by_number(client: SuwayomiClient, manga_internal_id: int) -> float:
    """Return the highest canonical chapter number that has been read in Suwayomi."""
    items = fetch_suwayomi_chapters(client, manga_internal_id) or []
    nums = [n for n in (_parse_chapter_number(it) for it in items) if n is not None]
    frac_map = _build_fraction_map(nums)
    read_nums: List[float] = []
    for it in items:
        if not (it.get("read") or it.get("isRead")):
            continue
        n = _parse_chapter_number(it)
        if n is None:
            continue
        if _is_fraction_canonical(n, frac_map):
            read_nums.append(n)
    return max(read_nums) if read_nums else 0.0


def mark_entry_up_to_number(
    client: SuwayomiClient,
    manga_internal_id: int,
    up_to: float,
    rpm: int,
    dry_run: bool = False,
) -> None:
    """Mark all canonical chapters <= up_to as read for one manga."""
    items = fetch_suwayomi_chapters(client, manga_internal_id) or []
    nums = [n for n in (_parse_chapter_number(it) for it in items) if n is not None]
    frac_map = _build_fraction_map(nums)
    limiter = RateLimiter(rpm=rpm)
    applied = 0
    attempted_ids: List[int] = []
    for it in items:
        n = _parse_chapter_number(it)
        if n is None:
            continue
        if not _is_fraction_canonical(n, frac_map):
            continue
        if n <= up_to and not (it.get("read") or it.get("isRead")):
            cid = it.get("id") or it.get("chapterId") or it.get("_id")
            if isinstance(cid, str) and cid.isdigit():
                cid = int(cid)
            if not isinstance(cid, int):
                continue
            if dry_run:
                logger.info(f"[DRY] Mark read by number <= {up_to}: chapter {n} (id={cid})")
            else:
                limiter.wait()
                try:
                    ok = mark_chapter_read(client, cid)
                    if ok:
                        applied += 1
                        logger.info(f"Mark read: chapter {n} (id={cid})")
                    attempted_ids.append(cid)
                except Exception:
                    pass
    if not dry_run:
        logger.info(f"Mark summary: applied {applied} chapters on entry {manga_internal_id} up to {up_to}")
        if attempted_ids:
            try:
                v_items = fetch_suwayomi_chapters(client, manga_internal_id) or []
                id_set = set(attempted_ids)
                read_count = sum(
                    1 for vit in v_items
                    if (vit.get("id") or vit.get("chapterId") or vit.get("_id")) in id_set
                    and (vit.get("read") or vit.get("isRead"))
                )
                logger.info(f"Verify summary: {read_count}/{len(attempted_ids)} marked as read now")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# UUID-based chapter sync (MangaDex read UUIDs matched against Suwayomi chapters)
# ---------------------------------------------------------------------------

def sync_read_chapters_by_uuid(
    client: SuwayomiClient,
    manga_internal_id: int,
    md_read_uuids: List[str],
    dry_run: bool,
    rpm: int,
    show_progress: bool = True,
    prefix: str = "",
    missing_report_path: Optional["Any"] = None,
    manga_md_id: str = "",
    fetch_title_fn: Optional[Any] = None,
) -> None:
    """Sync read chapters using MangaDex chapter UUIDs.

    Args:
        client: Suwayomi client (the only dependency on Suwayomi).
        manga_internal_id: Suwayomi internal manga ID.
        md_read_uuids: List of MangaDex chapter UUIDs the user has read.
        dry_run: If True, log actions without making writes.
        rpm: Rate-limit in requests per minute.
        show_progress: Whether to log progress.
        prefix: Log line prefix string.
        missing_report_path: Optional Path to append CSV missing-chapter rows.
        manga_md_id: MangaDex UUID string for reporting (not used for API calls).
        fetch_title_fn: Optional callable(md_id) -> str for report titles.
    """
    import csv as _csv

    su_chapters = fetch_suwayomi_chapters(client, manga_internal_id)
    if not su_chapters:
        if show_progress:
            logger.warning(f"{prefix}WARN no chapters loaded yet for {manga_md_id}")
        if missing_report_path:
            try:
                title = fetch_title_fn(manga_md_id) if fetch_title_fn else ""
                with missing_report_path.open("a", newline="", encoding="utf-8") as f:
                    _csv.writer(f).writerow([title, manga_md_id, 0, 0, "unknown"])
            except Exception:
                pass
        return

    uuid_to_internal: Dict[str, int] = {}
    for ch in su_chapters:
        cid = ch.get("id") or ch.get("chapterId") or ch.get("chapter_id")
        try:
            cid_int = int(cid or 0)
        except Exception:
            continue
        uuid = extract_chapter_uuid_from_item(ch)
        if uuid:
            uuid_to_internal[uuid.lower()] = cid_int

    limiter = RateLimiter(rpm=rpm)
    marked = 0
    missing = 0
    for uuid in md_read_uuids:
        internal = uuid_to_internal.get(uuid.lower())
        if not internal:
            missing += 1
            continue
        if dry_run:
            marked += 1
            continue
        limiter.wait()
        ok = mark_chapter_read(client, internal)
        if ok:
            marked += 1

    if show_progress:
        logger.info(
            f"{prefix}Chapters sync {manga_md_id}: "
            f"markable={len(md_read_uuids)} marked={marked} missing={missing}"
        )
    if missing_report_path and missing > 0:
        try:
            title = fetch_title_fn(manga_md_id) if fetch_title_fn else ""
            with missing_report_path.open("a", newline="", encoding="utf-8") as f:
                _csv.writer(f).writerow([title, manga_md_id, len(md_read_uuids), marked, missing])
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Backward-compat underscore aliases (used by monolith)
# ---------------------------------------------------------------------------
_compute_entry_progress_by_number = compute_entry_progress_by_number
_mark_entry_up_to_number = mark_entry_up_to_number
_parse_chapter_number_from_item = _parse_chapter_number
_build_fraction_map = _build_fraction_map
_is_fraction_canonical = _is_fraction_canonical

"""Library prune operations — remove duplicate or non-preferred-language entries.

Depends ONLY on SuwayomiClient. No MangaDex imports.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Set, Tuple

from seiyomi.clients.suwayomi import SuwayomiClient

logger = logging.getLogger("seiyomi.prune")


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", "", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return " ".join(s.split())


def prune_zero_duplicates(client: SuwayomiClient, args: Any) -> int:
    """Remove library duplicates (same title, one has zero chapters).

    Returns an exit code: 0 on success, 5 if library fetch failed.
    """
    library = client.get_library()
    if not library:
        logger.error("Could not fetch library or library is empty.")
        return 5

    groups: Dict[str, list] = {}
    for e in library:
        title = str(e.get("title") or e.get("name") or "").strip()
        if args.prune_filter_title and args.prune_filter_title.lower() not in title.lower():
            continue
        nid = _norm(title)
        groups.setdefault(nid, []).append(e)

    removed = 0
    kept = 0
    threshold = max(0, int(args.prune_threshold_chapters))
    for nid, items in groups.items():
        with_counts = []
        for e in items:
            mid = e.get("id") or e.get("mangaId") or e.get("manga_id")
            try:
                mid_int = int(mid)
            except Exception:
                continue
            try:
                cnt = client.get_manga_chapters_count(mid_int)
            except Exception:
                cnt = 0
            with_counts.append((mid_int, cnt, e))
        keepers = [t for t in with_counts if (t[1] or 0) >= threshold]
        if not keepers:
            kept += len(with_counts)
            continue
        max_cnt = max(t[1] or 0 for t in keepers)
        keep_set = {t[0] for t in keepers if (t[1] or 0) == max_cnt}
        for mid_int, cnt, e in with_counts:
            title = str(e.get("title") or e.get("name") or "").strip()
            if mid_int in keep_set:
                kept += 1
                if not args.no_progress:
                    logger.info(f"KEEP '{title}' (chapters={cnt})")
            else:
                if args.dry_run:
                    removed += 1
                    if not args.no_progress:
                        logger.info(f"PRUNE (dry-run) '{title}' (chapters={cnt})")
                else:
                    ok = client.remove_from_library(mid_int)
                    removed += 1 if ok else 0
                    if not args.no_progress:
                        logger.info(f"PRUNE '{title}' (chapters={cnt}) -> {'OK' if ok else 'FAIL'}")
    logger.info(f"Prune summary: kept={kept} removed={removed}")
    return 0


def prune_nonpreferred_langs(client: SuwayomiClient, args: Any) -> int:
    """Remove library entries whose chapters are not in preferred languages,
    when a preferred-language entry for the same title exists.

    Returns an exit code: 0–6.
    """
    if not args.preferred_langs:
        logger.info("--prune-nonpreferred-langs requires --preferred-langs")
        return 2

    pref_langs = {
        s.strip().lower().replace("_", "-")
        for s in args.preferred_langs.split(",")
        if s.strip()
    }

    library = client.get_library()
    if not library:
        logger.error("Could not fetch library or library is empty.")
        return 5

    groups: Dict[str, list] = {}
    for e in library:
        title = str(e.get("title") or e.get("name") or "").strip()
        if args.prune_filter_title and args.prune_filter_title.lower() not in title.lower():
            continue
        nid = _norm(title)
        groups.setdefault(nid, []).append(e)

    removed = 0
    kept = 0
    min_pref = max(1, int(args.prune_lang_threshold))

    for nid, items in groups.items():
        scored: List[Tuple[int, int, int, Dict[str, Any]]] = []
        for e in items:
            mid = e.get("id") or e.get("mangaId") or e.get("manga_id")
            try:
                mid_int = int(mid)
            except Exception:
                continue
            try:
                pref_count = client.get_manga_chapters_count_by_lang(mid_int, pref_langs, canonical=False)
            except Exception:
                pref_count = 0
            try:
                total_count = client.get_manga_chapters_count(mid_int)
            except Exception:
                total_count = 0
            scored.append((pref_count, total_count, mid_int, e))

        keep_set: Set[int] = set()
        best_pref = max((p for (p, _, _, _) in scored), default=0)
        if best_pref >= min_pref:
            keep_set = {mid for (p, _, mid, _) in scored if p == best_pref}
        else:
            if args.prune_lang_fallback_keep_most and scored:
                max_total = max((t for (_, t, _, _) in scored), default=0)
                keep_set = {mid for (_, t, mid, _) in scored if t == max_total}
            else:
                keep_set = {mid for (_, _, mid, _) in scored}

        for pref_count, total_count, mid_int, e in scored:
            title = str(e.get("title") or e.get("name") or "").strip()
            if mid_int in keep_set:
                kept += 1
                if not args.no_progress:
                    logger.info(f"KEEP '{title}' (pref={pref_count}, total={total_count})")
            else:
                if args.dry_run:
                    removed += 1
                    if not args.no_progress:
                        logger.info(f"PRUNE (dry-run) '{title}' (pref={pref_count}, total={total_count})")
                else:
                    ok = client.remove_from_library(mid_int)
                    removed += 1 if ok else 0
                    if not args.no_progress:
                        logger.info(
                            f"PRUNE '{title}' (pref={pref_count}, total={total_count}) -> "
                            f"{'OK' if ok else 'FAIL'}"
                        )
    logger.info(f"Prune by language summary: kept={kept} removed={removed}")
    return 0

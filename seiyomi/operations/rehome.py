"""Rehome/migration operation — move a library entry to a better source.

Depends on SuwayomiClient. No MangaDex imports.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from seiyomi.clients.suwayomi import SuwayomiClient
from seiyomi.matching.titles import is_title_match

logger = logging.getLogger("seiyomi.rehome")


def rehome_entry(
    client: SuwayomiClient,
    manga_id: int,
    title: str,
    rehome_conf: Dict[str, Any],
    show_progress: bool = True,
    prefix: str = "",
) -> bool:
    """Search alternative sources and add the best match to the library.

    If ``rehome_conf['remove_md']`` is True and the alternative was added
    successfully, the original entry is removed from the library.

    Returns True if an alternative was successfully added.
    """
    pref = [s.strip().lower() for s in (rehome_conf.get("sources") or []) if s.strip()]
    all_sources = client.get_sources()

    exclude_frags = [f for f in (rehome_conf.get("exclude_frags") or []) if f]
    if exclude_frags:
        all_sources = [
            s for s in all_sources
            if not any(f in (s.get("name") or s.get("apkName") or "").lower() for f in exclude_frags)
        ]

    def _score(src: Dict[str, Any]) -> int:
        nm = (src.get("name") or src.get("apkName") or "").lower()
        for i, frag in enumerate(pref):
            if frag and frag in nm:
                return i
        return 9999

    threshold = float(rehome_conf.get("title_threshold") or 0.6)
    strict = bool(rehome_conf.get("title_strict") or False)

    for src in sorted(all_sources, key=_score):
        nm = (src.get("name") or src.get("apkName") or "").lower()
        if "mangadex" in nm:
            continue
        if pref and all(f not in nm for f in pref):
            if show_progress:
                logger.info(f"{prefix}REHOME skip {src.get('name')!r} (outside preferred list)")
            continue
        try:
            rid = int(src.get("id"))
        except Exception:
            continue
        try:
            search = client.search_source(rid, title, page=1)
        except Exception:
            continue
        items = SuwayomiClient.normalize_search_items(search)
        if not items:
            continue

        def _cand_title(it: Dict[str, Any]) -> str:
            return str(it.get("title") or it.get("name") or it.get("label") or "")

        filtered = [it for it in items if is_title_match(title, _cand_title(it), threshold=threshold, strict_exact=strict)]
        if not filtered:
            if show_progress:
                logger.info(f"{prefix}REHOME skip '{src.get('name')}' (no title match >= {threshold}{' strict' if strict else ''})")
            continue

        alt_id: Optional[int] = None
        if rehome_conf.get("best_source"):
            best_count = -1
            limit = int(rehome_conf.get("best_candidates") or 5)
            for cand in filtered[: max(1, limit)]:
                cid = SuwayomiClient.extract_manga_id(cand)
                if cid is None:
                    continue
                cnt = 0
                try:
                    if rehome_conf.get("canonical"):
                        cnt = client.get_manga_chapters_canonical_count(cid)
                    else:
                        cnt = client.get_manga_chapters_count(cid)
                except Exception:
                    cnt = 0
                if cnt >= int(rehome_conf.get("min_chapters_per_alt") or 0) and cnt > best_count:
                    best_count = cnt
                    alt_id = cid
        else:
            alt_id = SuwayomiClient.extract_manga_id(filtered[0])

        if alt_id is None and int(rehome_conf.get("min_chapters_per_alt") or 0) <= 0 and filtered:
            alt_id = SuwayomiClient.extract_manga_id(filtered[0])
        if alt_id is None:
            continue

        added_alt = client.add_to_library(alt_id)
        if show_progress:
            msg = f"{prefix}REHOME via '{src.get('name')}'"
            if rehome_conf.get("best_source"):
                msg += " (best-source)"
            logger.info(f"{msg} -> {'OK' if added_alt else 'FAIL'}")
        if added_alt and rehome_conf.get("remove_md"):
            try:
                rm_ok = client.remove_from_library(manga_id)
                if show_progress:
                    logger.info(f"{prefix}REMOVE original entry -> {'OK' if rm_ok else 'FAIL'}")
            except Exception:
                pass
        # Stop after first successful (or attempted) source
        return bool(added_alt)

    return False

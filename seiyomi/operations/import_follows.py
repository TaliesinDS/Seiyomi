"""MangaDex follows import operation.

Adds MangaDex manga IDs to the Suwayomi library, with optional:
- category assignment from reading status
- chapter read-sync
- rehoming to alternative sources
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from seiyomi.clients.suwayomi import SuwayomiClient

logger = logging.getLogger("seiyomi.import_follows")


def import_ids(
    client: SuwayomiClient,
    ids: List[str],
    dry_run: bool = False,
    use_title_fallback: bool = True,
    show_progress: bool = True,
    throttle: float = 0.0,
    category_id: Optional[int] = None,
    reading_statuses: Optional[Dict[str, str]] = None,
    status_category_map: Optional[Dict[str, int]] = None,
    status_default_category: Optional[int] = None,
    session_token: Optional[str] = None,
    chapter_sync_conf: Optional[Dict[str, Any]] = None,
    status_map_debug: bool = False,
    assume_missing_status: Optional[str] = None,
    lists_membership: Optional[Dict[str, List[str]]] = None,
    lists_category_map: Optional[Dict[str, int]] = None,
    lists_ignore_set: Optional[set] = None,
    rehome_conf: Optional[Dict[str, Any]] = None,
) -> Tuple[int, int, List[Tuple[str, str]], List[Tuple[str, int]]]:
    # Lazy imports to avoid circular dependencies at module load time
    from import_mangadex_bookmarks_to_suwayomi_refactored import (  # noqa: F401
        find_mangadex_source_id,
        search_by_mangadex_id,
        search_by_title,
        fetch_title_from_mangadex,
        sync_read_chapters_for_manga,
    )
    from seiyomi.operations.rehome import rehome_entry as _rehome_entry

    client._auth()
    sources = client.get_sources()
    source_id = find_mangadex_source_id(sources)
    if not source_id:
        raise SystemExit(
            "Could not find MangaDex source. Ensure the MangaDex extension is installed and enabled in Suwayomi."
        )

    added = 0
    failed = 0
    failures: List[Tuple[str, str]] = []
    added_entries: List[Tuple[str, int]] = []

    total = len(ids)
    for idx, md in enumerate(ids, 1):
        prefix = f"[{idx}/{total}] " if show_progress else ""
        try:
            manga_id = search_by_mangadex_id(client, source_id, md)
            fetched_title: Optional[str] = None
            if manga_id is None and use_title_fallback:
                fetched_title = fetch_title_from_mangadex(md)
                if fetched_title:
                    manga_id = search_by_title(client, source_id, fetched_title)
            if manga_id is None:
                failures.append(
                    (md, "not found (uuid + title fallback failed)" if use_title_fallback else "not found")
                )
                failed += 1
                if show_progress:
                    logger.error(f"{prefix}FAIL {md} {('- ' + fetched_title) if fetched_title else ''}".rstrip())
                continue
            if dry_run:
                if status_map_debug:
                    display = None
                    target_cat = None
                    via = ""
                    if lists_membership and lists_category_map:
                        names = [
                            n for n in (lists_membership.get(md) or [])
                            if not (lists_ignore_set and n in lists_ignore_set)
                        ]
                        for nm in names:
                            if nm in lists_category_map:
                                display = f"List:{nm}"
                                target_cat = lists_category_map[nm]
                                via = "list-map"
                                break
                    if target_cat is None and status_category_map:
                        raw_status = (reading_statuses.get(md, "") if reading_statuses else "")
                        eff_status = (raw_status or assume_missing_status or "").lower()
                        display = (
                            raw_status
                            or (assume_missing_status and f"(assumed {assume_missing_status})")
                            or "(none)"
                        )
                        if eff_status:
                            target_cat = status_category_map.get(eff_status)
                            via = "map"
                            if target_cat is None and status_default_category is not None:
                                target_cat = status_default_category
                                via = "default"
                            if (
                                target_cat is None
                                and raw_status == ""
                                and assume_missing_status
                                and status_category_map.get(assume_missing_status.lower())
                            ):
                                target_cat = status_category_map.get(assume_missing_status.lower())
                                via = "assumed"
                        else:
                            if status_default_category is not None:
                                target_cat = status_default_category
                                via = "default"
                    if show_progress:
                        if target_cat is not None:
                            logger.info(f"{prefix}STATUS {display or '(none)'} -> cat {target_cat} ({via}) (dry-run)")
                        else:
                            logger.info(f"{prefix}STATUS {(display or '(none)')} -> no mapping (dry-run)")
                added += 1
                added_entries.append((md, manga_id))
                if show_progress:
                    logger.info(f"{prefix}OK (dry-run) {md}")
                continue
            ok = client.add_to_library(manga_id)
            if ok:
                cat_result = True
                if category_id is not None:
                    cat_result = client.add_manga_to_category(manga_id, category_id)
                applied = False
                if lists_membership and lists_category_map:
                    names = [
                        n for n in (lists_membership.get(md) or [])
                        if not (lists_ignore_set and n in lists_ignore_set)
                    ]
                    for nm in names:
                        if nm in lists_category_map:
                            try:
                                cat_ok = client.add_manga_to_category(manga_id, lists_category_map[nm])
                                applied = True
                                if status_map_debug and show_progress:
                                    logger.info(
                                        f"{prefix}STATUS List:{nm} -> cat {lists_category_map[nm]} "
                                        f"{'OK' if cat_ok else 'FAIL'}"
                                    )
                            except Exception as sm_e:
                                if status_map_debug and show_progress:
                                    logger.error(f"{prefix}STATUS List:{nm} ERROR {sm_e}")
                            break
                if (
                    (not applied)
                    and (reading_statuses or assume_missing_status or status_default_category is not None)
                    and status_category_map
                ):
                    raw_status = (reading_statuses.get(md, "") if reading_statuses else "")
                    eff_status = (raw_status or assume_missing_status or "").lower()
                    if eff_status:
                        target_cat = status_category_map.get(eff_status)
                        resolved_via = "map"
                        if target_cat is None and status_default_category is not None:
                            target_cat = status_default_category
                            resolved_via = "default"
                        if (
                            target_cat is None
                            and raw_status == ""
                            and assume_missing_status
                            and status_category_map.get(assume_missing_status.lower())
                        ):
                            target_cat = status_category_map.get(assume_missing_status.lower())
                            resolved_via = "assumed"
                        if target_cat is not None:
                            try:
                                cat_ok = client.add_manga_to_category(manga_id, target_cat)
                                if status_map_debug and show_progress:
                                    display_status = raw_status or f"(assumed {assume_missing_status})"
                                    logger.info(
                                        f"{prefix}STATUS {display_status} -> cat {target_cat} "
                                        f"({resolved_via}) {'OK' if cat_ok else 'FAIL'}"
                                    )
                            except Exception as sm_e:
                                if status_map_debug and show_progress:
                                    logger.error(f"{prefix}STATUS {eff_status} -> cat {target_cat} ERROR {sm_e}")
                        else:
                            if status_map_debug and show_progress:
                                display_status = raw_status or "(none)"
                                logger.info(f"{prefix}STATUS {display_status} -> no mapping applied")
                    else:
                        if status_default_category is not None:
                            try:
                                cat_ok = client.add_manga_to_category(manga_id, status_default_category)
                                if status_map_debug and show_progress:
                                    logger.info(
                                        f"{prefix}STATUS (none) -> cat {status_default_category} "
                                        f"(default) {'OK' if cat_ok else 'FAIL'}"
                                    )
                            except Exception as sm_e:
                                if status_map_debug and show_progress:
                                    logger.error(
                                        f"{prefix}STATUS (none) -> cat {status_default_category} ERROR {sm_e}"
                                    )
                if chapter_sync_conf and chapter_sync_conf.get("enabled") and session_token:
                    delay = chapter_sync_conf.get("delay") or 0
                    if delay > 0:
                        time.sleep(delay)
                    try:
                        sync_read_chapters_for_manga(
                            client=client,
                            session_token=session_token,
                            manga_md_id=md,
                            manga_internal_id=manga_id,
                            dry_run=chapter_sync_conf.get("dry_run", False),
                            rpm=chapter_sync_conf.get("rpm", 300),
                            show_progress=show_progress,
                            prefix=prefix,
                        )
                    except Exception as ce:
                        if show_progress:
                            logger.warning(f"{prefix}WARN chapters {md}: {ce}")
                if rehome_conf and rehome_conf.get("enabled"):
                    try:
                        min_ch = int(rehome_conf.get("skip_if_ge", 1))
                    except Exception:
                        min_ch = 1
                    have = client.get_manga_chapters_count(manga_id)
                    if have < min_ch:
                        title = fetched_title or fetch_title_from_mangadex(md) or ""
                        if not title:
                            det = client.get_manga_details(manga_id)
                            title = str(det.get("title") or det.get("name") or "")
                        if title:
                            _rehome_entry(
                                client=client,
                                manga_id=manga_id,
                                title=title,
                                rehome_conf=rehome_conf,
                                show_progress=show_progress,
                                prefix=prefix,
                            )
                added += 1
                added_entries.append((md, manga_id))
                if show_progress:
                    if category_id is not None:
                        logger.info(f"{prefix}OK added {md} (category {'ok' if cat_result else 'fail'})")
                    else:
                        logger.info(f"{prefix}OK added {md}")
            else:
                failed += 1
                status = getattr(client, "last_status", None)
                failures.append((md, f"add_to_library status {status if status is not None else 'unknown'}"))
                if show_progress:
                    logger.error(f"{prefix}FAIL add {md} (status {status if status is not None else 'unknown'})")
        except Exception as e:
            failed += 1
            failures.append((md, str(e)))
            if show_progress:
                logger.error(f"{prefix}ERROR {md}: {e}")
        if throttle > 0:
            time.sleep(throttle)
    return added, failed, failures, added_entries

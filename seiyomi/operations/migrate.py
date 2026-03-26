"""Library migration operation — find alternative sources for low-chapter-count entries.

Depends on SuwayomiClient. No MangaDex imports.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from seiyomi.clients.suwayomi import SuwayomiClient
from seiyomi.utils.checkpoint import Checkpoint

logger = logging.getLogger("seiyomi.migrate")


def migrate_library(client: SuwayomiClient, args: Any) -> int:
    """Migrate library entries to better sources.

    Iterates the library, finds entries with fewer than --migrate-threshold-chapters
    chapters, searches alternative sources, and optionally adds the best alternative.

    Returns an exit code: 0 on success, 5 if library fetch failed, 6 if any entries
    could not be migrated.
    """
    client._auth()
    setattr(client, "debug_library", bool(args.debug_library))
    library = client.get_library()
    if not library:
        logger.debug("Could not fetch library or library is empty. Try --debug-library to see endpoint attempts.")
        return 5
    if not args.no_progress:
        logger.info(f"Library entries discovered: {len(library)}")

    # Resolve category include/exclude filters
    include_cat_tokens = [
        s.strip()
        for s in (args.migrate_include_categories.split(",") if args.migrate_include_categories else [])
        if s.strip()
    ]
    exclude_cat_tokens = [
        s.strip()
        for s in (args.migrate_exclude_categories.split(",") if args.migrate_exclude_categories else [])
        if s.strip()
    ]
    cat_name_by_id: Dict[int, str] = {}
    cat_id_by_name: Dict[str, int] = {}
    membership: Dict[int, Set[int]] = {}
    include_cat_ids: Set[int] = set()
    exclude_cat_ids: Set[int] = set()

    if include_cat_tokens or exclude_cat_tokens:
        try:
            cats_res = client.graphql("query { categories { nodes { id name } edges { node { id name } } } }")
        except Exception:
            cats_res = None
        cat_ids: List[int] = []
        if isinstance(cats_res, dict) and isinstance(cats_res.get("data"), dict):
            root = cats_res["data"].get("categories") or {}
            nodes = []
            if isinstance(root, dict):
                nodes += [n for n in (root.get("nodes") or []) if isinstance(n, dict)]
                nodes += [
                    e.get("node")
                    for e in (root.get("edges") or [])
                    if isinstance(e, dict) and isinstance(e.get("node"), dict)
                ]
            for n in nodes:
                try:
                    cid = int(n.get("id"))
                    nm = str(n.get("name") or "")
                    cat_ids.append(cid)
                    cat_name_by_id[cid] = nm
                    if nm:
                        cat_id_by_name[nm.lower()] = cid
                except Exception:
                    pass
        for cid in cat_ids:
            arg_shapes = [("page", "size"), ("page", "limit"), ("pageNum", "pageSize"), ("offset", "limit")]
            page = 1
            empty_pages = 0
            while page <= 200:
                if arg_shapes[0][0] == "offset":
                    gql_vars = {"cid": int(cid), "offset": (page - 1) * 200, "limit": 200}
                    q = "query($cid:Int,$offset:Int,$limit:Int){ category(id:$cid){ mangas(offset:$offset, limit:$limit){ nodes { id } edges { node { id } } } } }"
                elif arg_shapes[0][0] == "pageNum":
                    gql_vars = {"cid": int(cid), "pageNum": page, "pageSize": 200}
                    q = "query($cid:Int,$pageNum:Int,$pageSize:Int){ category(id:$cid){ mangas(pageNum:$pageNum, pageSize:$pageSize){ nodes { id } edges { node { id } } } } }"
                else:
                    gql_vars = {"cid": int(cid), "page": page, "size": 200}
                    q = "query($cid:Int,$page:Int,$size:Int){ category(id:$cid){ mangas(page:$page, size:$size){ nodes { id } edges { node { id } } } } }"
                res = client.graphql(q, variables=gql_vars)
                ids_this_page: List[int] = []
                try:
                    nodes_data = (((res or {}).get("data") or {}).get("category") or {}).get("mangas") or {}
                    raw: List[Any] = []
                    if isinstance(nodes_data, dict):
                        raw += [n for n in (nodes_data.get("nodes") or []) if isinstance(n, dict)]
                        raw += [
                            e.get("node")
                            for e in (nodes_data.get("edges") or [])
                            if isinstance(e, dict) and isinstance(e.get("node"), dict)
                        ]
                    for it in raw:
                        try:
                            ids_this_page.append(int(it.get("id")))
                        except Exception:
                            pass
                except Exception:
                    pass
                if not ids_this_page:
                    empty_pages += 1
                    if empty_pages >= 2:
                        break
                else:
                    empty_pages = 0
                    membership.setdefault(int(cid), set()).update(ids_this_page)
                page += 1

        def tokens_to_ids(tokens: List[str]) -> Set[int]:
            out: Set[int] = set()
            for t in tokens:
                tl = t.strip().lower()
                if not tl:
                    continue
                if tl.isdigit():
                    out.add(int(tl))
                elif tl in cat_id_by_name:
                    out.add(cat_id_by_name[tl])
            return out

        include_cat_ids = tokens_to_ids(include_cat_tokens)
        exclude_cat_ids = tokens_to_ids(exclude_cat_tokens)

    lib_ids: Set[int] = set()
    for _e in library:
        try:
            lib_ids.add(int(_e.get("id") or _e.get("mangaId") or _e.get("manga_id") or 0))
        except Exception:
            pass

    pref_str = args.migrate_sources or args.rehoming_sources or ""
    pref = [s.strip().lower() for s in pref_str.split(",") if s.strip()]
    sources = client.get_sources()

    exclude_frags = [
        s.strip().lower()
        for s in (args.exclude_sources.split(",") if args.exclude_sources else [])
        if s.strip()
    ]
    if exclude_frags:
        def not_excluded(src: Dict[str, Any]) -> bool:
            nm = (src.get("name") or src.get("apkName") or "").lower()
            return all(frag not in nm for frag in exclude_frags)
        sources = [s for s in sources if not_excluded(s)]

    def score_source(src: Dict[str, Any]) -> int:
        nm = (src.get("name") or src.get("apkName") or "").lower()
        for i, frag in enumerate(pref):
            if frag and frag in nm:
                return i
        return 9999

    if args.migrate_preferred_only and pref:
        sources = [
            s for s in sources
            if any(f in (s.get("name") or s.get("apkName") or "").lower() for f in pref)
        ]
    sorted_sources = sorted(sources, key=score_source)

    def site_key(src: Dict[str, Any]) -> str:
        nm = (src.get("name") or src.get("apkName") or "").lower()
        return re.sub(r"[^a-z]+", "", nm)[:32]

    def title_variants(full: str) -> List[str]:
        result: List[str] = []

        def add(s: str) -> None:
            s = " ".join(s.split())
            if s and s not in result:
                result.append(s)

        add(full)
        m = re.split(r"\s*[~:\-\u2013\u2014]\s*", full)
        if m:
            add(m[0])
        add(re.sub(r"[\(\[\{].*?[\)\]\}]", "", full))
        add(re.sub(r"[^0-9A-Za-z\s]", "", full))
        if len(full) > 64:
            add(full[:64])
        return result[:4]

    migrated = 0
    skipped = 0
    failed = 0
    threshold = max(0, args.migrate_threshold_chapters)
    filter_sub = (args.migrate_filter_title or "").strip().lower()
    pref_langs: Set[str] = set()
    if args.preferred_langs:
        pref_langs = {
            s.strip().lower().replace("_", "-")
            for s in args.preferred_langs.split(",")
            if s.strip()
        }

    # Resumable checkpoint: load when --resume is set
    _resume = getattr(args, "resume", False)
    cp = Checkpoint("migrate")
    if _resume:
        cp.load()
    elif cp.path.exists():
        logger.info(
            "[checkpoint] A previous migrate checkpoint exists "
            f"({cp.path}). Use --resume to continue from where it left off, "
            "or delete the file to start fresh."
        )

    for idx, entry in enumerate(library, 1):
        mid = entry.get("id") or entry.get("mangaId") or entry.get("manga_id")
        try:
            mid_int = int(mid or 0)
        except Exception:
            continue

        # Skip already-completed entries when resuming
        if _resume and cp.done(mid_int):
            skipped += 1
            continue

        if include_cat_tokens or exclude_cat_tokens:
            cats_for = membership.get(mid_int, set())
            if include_cat_tokens and not (cats_for & include_cat_ids):
                if args.debug_library and not args.no_progress:
                    logger.info(f"[{idx}] SKIP by include-categories")
                continue
            if exclude_cat_tokens and (cats_for & exclude_cat_ids):
                if args.debug_library and not args.no_progress:
                    logger.info(f"[{idx}] SKIP by exclude-categories")
                continue

        title = str(entry.get("title") or entry.get("name") or "").strip()
        ch_count = client.get_manga_chapters_count(mid_int)
        if ch_count >= threshold:
            skipped += 1
            if not args.no_progress:
                reason = f">={threshold} chapters" if ch_count is not None else "unknown chapter count"
                logger.info(f"[{idx}] SKIP '{title or mid_int}' ({reason})")
            continue
        if not title:
            det = client.get_manga_details(mid_int)
            title = str(det.get("title") or det.get("name") or "").strip()
        if not title:
            failed += 1
            if not args.no_progress:
                logger.info(f"[{idx}] MIGRATE skip (no title)")
            continue
        if not args.no_progress:
            logger.info(f"[{idx}] MIGRATE '{title}' (chapters={ch_count})")
        if filter_sub and filter_sub not in (title or "").lower():
            if args.debug_library and not args.no_progress:
                logger.info(f"[{idx}]   filter-title skip (no match)")
            continue

        added_any = False
        start_ts = time.time()
        per_site_counts: Dict[str, int] = {}
        cap_announced: Dict[str, bool] = {}
        global_best: Optional[Tuple[int, int, Dict[str, Any]]] = None
        global_raw_max: Optional[Tuple[int, int, Dict[str, Any]]] = None
        prefer_frags = [
            s.strip().lower()
            for s in (args.prefer_sources.split(",") if args.prefer_sources else [])
            if s.strip()
        ]

        for src in sorted_sources:
            nm = (src.get("name") or src.get("apkName") or "").lower()
            try:
                sid = int(src.get("id") or 0)
            except Exception:
                continue
            skey = site_key(src)
            cnt = per_site_counts.get(skey, 0)
            if args.migrate_max_sources_per_site and cnt >= max(1, int(args.migrate_max_sources_per_site)):
                if args.debug_library and not args.no_progress and not cap_announced.get(skey):
                    logger.info(f"[{idx}]   skip remaining '{nm}' sources (cap {args.migrate_max_sources_per_site})")
                    cap_announced[skey] = True
                continue
            if args.migrate_timeout and (time.time() - start_ts) > args.migrate_timeout:
                if not args.no_progress:
                    logger.info(f"[{idx}] MIGRATE timeout after {args.migrate_timeout:.0f}s; giving up on this title")
                break

            got_items: List[Dict[str, Any]] = []
            for qtitle in title_variants(title):
                try:
                    if args.debug_library and not args.no_progress:
                        logger.info(f"[{idx}]   search '{qtitle}' in source id={sid} ({nm})")
                    res = client.search_source(sid, qtitle, page=1)
                except Exception as e:
                    if args.debug_library and not args.no_progress:
                        logger.error(f"[{idx}]   search error on source id={sid}: {e}")
                    res = None
                items = SuwayomiClient.normalize_search_items(res)
                if items:
                    got_items = items
                    break
                if args.migrate_try_second_page:
                    try:
                        res2 = client.search_source(sid, qtitle, page=2)
                    except Exception:
                        res2 = None
                    items2 = SuwayomiClient.normalize_search_items(res2)
                    if items2:
                        got_items = items2
                        break
            if not got_items:
                if args.debug_library and not args.no_progress:
                    logger.info(f"[{idx}]   no results")
                per_site_counts[skey] = cnt + 1
                continue

            alt_id = None
            if args.best_source:
                best_count = -1
                raw_score: int = 0
                limit = max(1, int(args.best_source_candidates))
                for cand in got_items[:limit]:
                    cid = SuwayomiClient.extract_manga_id(cand)
                    if cid is None:
                        continue
                    ccount = 0
                    try:
                        if pref_langs:
                            if args.best_source_canonical:
                                ccount = client.get_manga_chapters_count_by_lang(cid, pref_langs, canonical=True)
                            else:
                                ccount = client.get_manga_chapters_count_by_lang(cid, pref_langs, canonical=False)
                            if ccount == 0 and args.lang_fallback:
                                ccount = (
                                    client.get_manga_chapters_canonical_count(cid)
                                    if args.best_source_canonical
                                    else client.get_manga_chapters_count(cid)
                                )
                        else:
                            ccount = (
                                client.get_manga_chapters_canonical_count(cid)
                                if args.best_source_canonical
                                else client.get_manga_chapters_count(cid)
                            )
                        if prefer_frags and any(f in nm for f in prefer_frags):
                            ccount += int(args.prefer_boost)
                        try:
                            raw_score = (
                                client.get_manga_chapters_canonical_count(cid)
                                if args.best_source_canonical
                                else client.get_manga_chapters_count(cid)
                            )
                        except Exception:
                            raw_score = 0
                    except Exception:
                        ccount = 0
                        raw_score = 0
                    if args.debug_library and not args.no_progress:
                        ctitle = str(cand.get("title") or cand.get("name") or "")
                        logger.info(f"[{idx}]     cand id={cid} site='{nm}' score={ccount} title='{ctitle[:60]}'")
                    if ccount >= max(0, int(args.min_chapters_per_alt)) and ccount > best_count:
                        best_count = ccount
                        alt_id = cid
                    if args.best_source_global and (global_raw_max is None or raw_score > global_raw_max[0]):
                        global_raw_max = (raw_score, cid, src)
                if args.best_source_global and alt_id is not None:
                    score_val = best_count
                    if global_best is None or score_val > global_best[0]:
                        global_best = (score_val, alt_id, src)
                    per_site_counts[skey] = cnt + 1
                    continue
            else:
                alt_id = SuwayomiClient.extract_manga_id(got_items[0])

            if not args.best_source_global and alt_id is None and int(args.min_chapters_per_alt) <= 0 and got_items:
                alt_id = SuwayomiClient.extract_manga_id(got_items[0])
            if args.best_source_global:
                per_site_counts[skey] = cnt + 1
                continue
            if alt_id is None:
                if args.debug_library and not args.no_progress:
                    logger.info(f"[{idx}]   unexpected search payload shape")
                per_site_counts[skey] = cnt + 1
                continue

            # ── Interactive pick ───────────────────────────────────────────
            if getattr(args, "interactive", False) and got_items:
                limit = max(1, min(int(args.best_source_candidates), len(got_items)))
                cands = got_items[:limit]
                print(f"\n[{idx}] '{title}' — {len(cands)} result(s) in '{nm}':")
                for ci, cand in enumerate(cands, 1):
                    cid_c = SuwayomiClient.extract_manga_id(cand)
                    ctitle = str(cand.get("title") or cand.get("name") or "?")
                    try:
                        ch_c = client.get_manga_chapters_count(cid_c) if cid_c else 0
                    except Exception:
                        ch_c = 0
                    star = " *" if cid_c == alt_id else ""
                    print(f"  {ci}. {ctitle} ({ch_c} ch) [id={cid_c}]{star}")
                _interactive_choice = None
                while _interactive_choice is None:
                    try:
                        _raw = input(f"  Choose [1-{len(cands)} / s=skip / a=auto / q=quit]: ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        _raw = "q"
                    if _raw == "q":
                        return 0  # user quit cleanly
                    elif _raw == "s":
                        _interactive_choice = "skip"
                    elif _raw in ("a", ""):
                        _interactive_choice = "auto"
                    elif _raw.isdigit() and 1 <= int(_raw) <= len(cands):
                        _interactive_choice = int(_raw) - 1
                    else:
                        print(f"  Enter 1–{len(cands)}, 's', 'a', or 'q'")
                if _interactive_choice == "skip":
                    per_site_counts[skey] = cnt + 1
                    continue
                elif isinstance(_interactive_choice, int):
                    alt_id = SuwayomiClient.extract_manga_id(cands[_interactive_choice])
                # else "auto" — keep existing alt_id

            if alt_id is None:
                per_site_counts[skey] = cnt + 1
                continue

            if not args.dry_run and args.migrate_remove_if_duplicate and alt_id and alt_id in lib_ids and alt_id != mid_int:
                try:
                    alt_ch = client.get_manga_chapters_count(alt_id)
                except Exception:
                    alt_ch = None
                if (alt_ch or 0) > 0:
                    try:
                        rm_ok = client.remove_from_library(mid_int)
                    except Exception:
                        rm_ok = False
                    if not args.no_progress:
                        logger.info(f"[{idx}] DUPLICATE already in library with chapters; REMOVE original -> {'OK' if rm_ok else 'FAIL'}")
                    if rm_ok:
                        migrated += 1
                        added_any = True
                        break

            if args.dry_run:
                added_any = True
                if not args.no_progress:
                    logger.info(f"[{idx}] MIGRATE '{title}' via '{src.get('name')}' -> OK (dry-run)")
            else:
                try:
                    added_any = client.add_to_library(alt_id)
                except Exception as e:
                    if args.debug_library and not args.no_progress:
                        logger.error(f"[{idx}]   add_to_library error for id={alt_id}: {e}")
                    added_any = False
                if not args.no_progress:
                    logger.info(f"[{idx}] MIGRATE '{title}' via '{src.get('name')}' -> {'OK' if added_any else 'FAIL'}")

            per_site_counts[skey] = cnt + 1
            if added_any and args.migrate_remove and not args.dry_run:
                try:
                    rm_ok = client.remove_from_library(mid_int)
                    if not args.no_progress:
                        logger.info(f"[{idx}] REMOVE original -> {'OK' if rm_ok else 'FAIL'}")
                except Exception:
                    pass
            if added_any:
                migrated += 1
                if not args.dry_run:
                    cp.mark_done(mid_int)
                break

        # Global-best: add the single winner after scanning all sources
        if not added_any and args.best_source_global and global_best is not None:
            best_score, best_alt_id, src_best = global_best
            if not args.dry_run and args.migrate_remove_if_duplicate and best_alt_id and best_alt_id in lib_ids and best_alt_id != mid_int:
                try:
                    best_ch = client.get_manga_chapters_count(best_alt_id)
                except Exception:
                    best_ch = None
                if (best_ch or 0) > 0:
                    try:
                        rm_ok = client.remove_from_library(mid_int)
                    except Exception:
                        rm_ok = False
                    if not args.no_progress:
                        logger.info(f"[{idx}] DUPLICATE already in library with chapters; REMOVE original -> {'OK' if rm_ok else 'FAIL'}")
                    if rm_ok:
                        migrated += 1
                        added_any = True

            if added_any:
                pass
            elif args.dry_run:
                added_any = True
                if not args.no_progress:
                    logger.info(f"[{idx}] MIGRATE '{title}' via '{src_best.get('name')}' (global-best) -> OK (dry-run)")
            else:
                try:
                    added_any = client.add_to_library(best_alt_id)
                except Exception as e:
                    if args.debug_library and not args.no_progress:
                        logger.error(f"[{idx}]   add_to_library error for id={best_alt_id}: {e}")
                    added_any = False
                if not args.no_progress:
                    logger.info(
                        f"[{idx}] MIGRATE '{title}' via '{src_best.get('name')}' (global-best) -> "
                        f"{'OK' if added_any else 'FAIL'}"
                    )

            if added_any and args.migrate_remove and not args.dry_run:
                try:
                    rm_ok = client.remove_from_library(mid_int)
                    if not args.no_progress:
                        logger.info(f"[{idx}] REMOVE original -> {'OK' if rm_ok else 'FAIL'}")
                except Exception:
                    pass

            if added_any:
                migrated += 1
                if not args.dry_run:
                    cp.mark_done(mid_int)
                if args.migrate_keep_both and global_raw_max is not None:
                    raw_count, raw_alt_id, raw_src = global_raw_max
                    if raw_alt_id and raw_alt_id != best_alt_id:
                        if args.keep_both_min_preferred > 0:
                            try:
                                pref_cnt_second = (
                                    client.get_manga_chapters_count_by_lang(
                                        raw_alt_id, pref_langs, canonical=args.best_source_canonical
                                    )
                                    if pref_langs
                                    else 0
                                )
                            except Exception:
                                pref_cnt_second = 0
                            if pref_cnt_second < int(args.keep_both_min_preferred):
                                if args.debug_library and not args.no_progress:
                                    logger.info(
                                        f"[{idx}]   skip raw-max keep (preferred-lang chapters "
                                        f"{pref_cnt_second} < {args.keep_both_min_preferred})"
                                    )
                                continue
                        if args.dry_run:
                            if not args.no_progress:
                                logger.info(f"[{idx}] ALSO KEEP '{title}' via '{raw_src.get('name')}' (raw-max) -> OK (dry-run)")
                        else:
                            try:
                                ok2 = client.add_to_library(raw_alt_id)
                            except Exception as e:
                                if args.debug_library and not args.no_progress:
                                    logger.error(f"[{idx}]   add_to_library error for id={raw_alt_id}: {e}")
                                ok2 = False
                            if not args.no_progress:
                                logger.info(f"[{idx}] ALSO KEEP '{title}' via '{raw_src.get('name')}' (raw-max) -> {'OK' if ok2 else 'FAIL'}")

    logger.info(f"Migrate summary: migrated={migrated} skipped={skipped} failed={failed}")
    # Clear checkpoint on clean completion (no failures means we're done)
    if failed == 0 and not args.dry_run:
        cp.clear()
    return 0 if failed == 0 else 6

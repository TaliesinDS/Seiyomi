"""Library migration operation — find alternative sources for low-chapter-count entries.

Depends on SuwayomiClient. No MangaDex imports.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from typing import Any, Dict, List, Optional, Set, Tuple

from seiyomi.clients.suwayomi import SuwayomiClient
from seiyomi.matching.titles import is_title_match
from seiyomi.utils.checkpoint import Checkpoint

logger = logging.getLogger("seiyomi.migrate")

_FATAL_HTTP_CODES = {400, 403, 404, 405, 410, 500, 502, 503}


def _is_fatal_http_error(exc: BaseException) -> bool:
    """Return True if the exception is an HTTP error with a non-retryable status."""
    try:
        from requests.exceptions import HTTPError
        if isinstance(exc, HTTPError) and exc.response is not None:
            return exc.response.status_code in _FATAL_HTTP_CODES
    except Exception:
        pass
    return False


def _parallel_search_sources(
    client: SuwayomiClient,
    title_variants_list: List[str],
    sources: List[Dict[str, Any]],
    try_second_page: bool,
    workers: int,
    timeout: float,
    early_stop: int = 5,
    dead_sources: Optional[Set[int]] = None,
) -> Dict[int, List[Dict[str, Any]]]:
    """Search multiple sources for a title in parallel.

    Each worker thread has *timeout* seconds to finish all its search
    attempts for one source.  A shared ``threading.Event`` is set once
    *early_stop* **unique sites** (by name) have returned results,
    signalling remaining threads to bail out instead of starting new
    HTTP requests.

    *dead_sources* is a shared set of source IDs that have failed
    consistently across titles.  Sources in this set are skipped, and
    newly-failing sources are added to it.

    Returns ``{source_id: search_result_items}`` for sources that had hits.
    """
    if dead_sources is None:
        dead_sources = set()
    cancel = threading.Event()
    # Build a sid → site-name lookup for unique-site early-stop
    _sid_to_site: Dict[int, str] = {}
    for src in sources:
        sid = int(src.get("id") or 0)
        nm = re.sub(r"[^a-z]+", "", (src.get("name") or "").lower())[:32]
        _sid_to_site[sid] = nm

    def _search_one(src: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]], bool]:
        """Returns (source_id, items, failed)."""
        sid = int(src.get("id") or 0)
        if sid in dead_sources:
            return (sid, [], False)
        failed = True  # assume failure until a non-error response
        for qtitle in title_variants_list:
            if cancel.is_set():
                return (sid, [], False)  # cancelled, not a source fault
            try:
                res = client.search_source(sid, qtitle, page=1)
                failed = False  # got a response
            except Exception as exc:
                if _is_fatal_http_error(exc):
                    return (sid, [], True)
                res = None
                continue
            items = SuwayomiClient.normalize_search_items(res)
            if items:
                return (sid, items, False)
            if try_second_page:
                if cancel.is_set():
                    return (sid, [], False)
                try:
                    res2 = client.search_source(sid, qtitle, page=2)
                except Exception as exc:
                    if _is_fatal_http_error(exc):
                        return (sid, [], True)
                    res2 = None
                items2 = SuwayomiClient.normalize_search_items(res2)
                if items2:
                    return (sid, items2, False)
        return (sid, [], failed)

    cache: Dict[int, List[Dict[str, Any]]] = {}
    # Track unique site names that returned results (not raw source count)
    _sites_with_hits: Set[str] = set()
    # Use a generous wall-clock limit for the whole batch.
    batch_deadline = max(timeout * 3, 90.0)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_search_one, src): src for src in sources}
        try:
            for future in as_completed(futures, timeout=batch_deadline):
                try:
                    sid, items, src_failed = future.result()
                    if src_failed:
                        dead_sources.add(sid)
                    if items:
                        cache[sid] = items
                        site = _sid_to_site.get(sid, "")
                        _sites_with_hits.add(site)
                        if early_stop and len(_sites_with_hits) >= early_stop and not cancel.is_set():
                            cancel.set()
                            logger.debug(
                                "Early stop: %d unique sites returned results, "
                                "signalling remaining threads to finish",
                                len(_sites_with_hits),
                            )
                except Exception:
                    pass
        except (TimeoutError, FuturesTimeoutError):
            logger.info("Parallel search batch timed out; using %d results gathered so far", len(cache))
            cancel.set()
    return cache


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

    # Comick.dev pre-filter + scoring
    comick = None
    rejects = None
    if getattr(args, "comick_prefilter", False):
        from seiyomi.clients.comick import ComickClient
        from seiyomi.utils.rejects import RejectsBin
        comick = ComickClient()
        rejects = RejectsBin(getattr(args, "rejects_file", "rejects.csv"))
        if not args.no_progress:
            logger.info(f"Comick pre-filter enabled (rejects -> {rejects.path})")

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

    pref_langs: Set[str] = set()
    if args.preferred_langs:
        pref_langs = {
            s.strip().lower().replace("_", "-")
            for s in args.preferred_langs.split(",")
            if s.strip()
        }

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

    # Filter to preferred-language sources (en + all by default, or --lang values + all)
    _source_langs = {"all"}  # always keep multi-language sources
    if pref_langs:
        _source_langs |= pref_langs
    else:
        _source_langs.add("en")
    sources = [
        s for s in sources
        if (s.get("lang") or "all").lower() in _source_langs
    ]

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

    def _resort_sources() -> List[Dict[str, Any]]:
        """Re-sort sources, boosting those that have won in this session."""
        if not source_wins:
            return sorted_sources
        # Two-level sort: first by win count (descending), then original pref order.
        return sorted(
            sorted_sources,
            key=lambda src: (-source_wins.get(int(src.get("id") or 0), 0), score_source(src)),
        )

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
    # Session-level set of source IDs that consistently fail — skip them
    # for subsequent titles to avoid wasting time on dead sources.
    dead_sources: Set[int] = set()
    # Session-level win tracker: source_id → number of times it was picked
    # as the winning source.  Used to prioritize proven sources first.
    source_wins: Dict[int, int] = {}
    threshold = max(0, args.migrate_threshold_chapters)
    filter_sub = (args.migrate_filter_title or "").strip().lower()

    # --from: filter entries by their current source
    from_source_frag = (getattr(args, "migrate_from_source", "") or "").strip().lower()
    from_source_ids: Set[int] = set()
    if from_source_frag:
        # When --from is used, raise threshold to effectively unlimited
        # so ALL entries from that source are considered, not just low-chapter ones
        if args.migrate_threshold_chapters <= 1:
            threshold = 999_999
        matched_names: Set[str] = set()
        for src in client.get_sources():
            src_name = (src.get("name") or src.get("apkName") or "").lower()
            try:
                src_id = int(src.get("id") or 0)
            except Exception:
                continue
            if from_source_frag in src_name:
                from_source_ids.add(src_id)
                matched_names.add(src.get("name") or src_name)
        if not from_source_ids:
            logger.warning(f"--from '{from_source_frag}' did not match any installed source.")
            return 0
        if not args.no_progress:
            names = ", ".join(sorted(matched_names))
            logger.info(f"--from matched {len(from_source_ids)} source(s): {names}")

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

        # --from: skip entries not belonging to the specified source
        if from_source_ids:
            entry_src = entry.get("sourceId") or entry.get("source_id")
            try:
                entry_src_int = int(entry_src or 0)
            except Exception:
                entry_src_int = 0
            if entry_src_int not in from_source_ids:
                continue

        title = str(entry.get("title") or entry.get("name") or "").strip()

        # Skip chapter count fetch when --from is used (source is likely dead)
        if from_source_ids:
            ch_count = 0
        else:
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

        # ── Comick pre-filter ──────────────────────────────────────────────
        comick_canonical: Optional[float] = None
        if comick is not None:
            cmatch = comick.best_match(title, threshold=args.migrate_title_threshold)
            if cmatch is None:
                if rejects is not None:
                    rejects.log(mid_int, title, "no_comick_match")
                if not args.no_progress:
                    logger.info(f"[{idx}]   Comick: no match — logged to rejects bin")
                # Don't skip — still search Suwayomi sources, but no canonical ref
            else:
                comick_canonical = cmatch.get("last_chapter")
                if not args.no_progress:
                    logger.info(
                        f"[{idx}]   Comick: '{cmatch['title']}' "
                        f"(ch={comick_canonical}, sim={cmatch['similarity']:.2f})"
                    )

        added_any = False
        start_ts = time.time()
        per_site_counts: Dict[str, int] = {}
        cap_announced: Dict[str, bool] = {}
        global_best: Optional[Tuple[int, int, Dict[str, Any], str]] = None
        global_raw_max: Optional[Tuple[int, int, Dict[str, Any]]] = None
        prefer_frags = [
            s.strip().lower()
            for s in (args.prefer_sources.split(",") if args.prefer_sources else [])
            if s.strip()
        ]

        # Re-sort sources based on session win history
        _active_sources = _resort_sources()

        # Pre-filter sources for per-site caps (needed for parallel search)
        workers = max(1, int(getattr(args, "migrate_workers", 1) or 1))
        search_cache: Optional[Dict[int, List[Dict[str, Any]]]] = None
        if workers > 1:
            cap = max(1, int(args.migrate_max_sources_per_site)) if args.migrate_max_sources_per_site else 999
            pre_counts: Dict[str, int] = {}
            capped_sources: List[Dict[str, Any]] = []
            for src in _active_sources:
                sk = site_key(src)
                c = pre_counts.get(sk, 0)
                if c < cap:
                    capped_sources.append(src)
                    pre_counts[sk] = c + 1
            if not args.no_progress:
                logger.info(f"[{idx}] Searching {len(capped_sources)} sources in parallel (workers={workers})...")
            search_cache = _parallel_search_sources(
                client, title_variants(title), capped_sources,
                try_second_page=args.migrate_try_second_page,
                workers=workers,
                timeout=args.migrate_timeout,
                dead_sources=dead_sources,
                # Scale early stop to source count: with fewer sources
                # (e.g. after EN-only filtering) we can afford to wait
                # for all of them.  Only kick in when we have many sources.
                early_stop=max(10, len(capped_sources) // 3),
            )
            if not args.no_progress:
                logger.info(f"[{idx}] Found results in {len(search_cache)} source(s)")

        for src in _active_sources:
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
            # Per-title wall-clock timeout only applies to sequential search
            # (workers=1).  Parallel search handles its own timeouts.
            if search_cache is None and args.migrate_timeout and (time.time() - start_ts) > args.migrate_timeout:
                if not args.no_progress:
                    logger.info(f"[{idx}] MIGRATE timeout after {args.migrate_timeout:.0f}s; giving up on this title")
                break

            got_items: List[Dict[str, Any]] = []
            if search_cache is not None:
                # Use pre-fetched parallel results
                got_items = search_cache.get(sid, [])
            else:
                # Sequential search (workers=1)
                for qtitle in title_variants(title):
                    try:
                        if args.debug_library and not args.no_progress:
                            logger.info(f"[{idx}]   search '{qtitle}' in source id={sid} ({nm})")
                        res = client.search_source(sid, qtitle, page=1)
                    except Exception as e:
                        if args.debug_library and not args.no_progress:
                            logger.error(f"[{idx}]   search error on source id={sid}: {e}")
                        if _is_fatal_http_error(e):
                            break  # source is broken, skip remaining variants
                        res = None
                    items = SuwayomiClient.normalize_search_items(res)
                    if items:
                        got_items = items
                        break
                    if args.migrate_try_second_page:
                        try:
                            res2 = client.search_source(sid, qtitle, page=2)
                        except Exception as e2:
                            if _is_fatal_http_error(e2):
                                break
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

            # Filter candidates by title similarity — drop "latest uploads"
            # garbage that sources return when they have no real matches.
            def _cand_title(it: Dict[str, Any]) -> str:
                return str(it.get("title") or it.get("name") or it.get("label") or "")

            got_items = [
                it for it in got_items
                if is_title_match(
                    title, _cand_title(it),
                    threshold=args.migrate_title_threshold,
                    strict_exact=args.migrate_title_strict,
                )
            ]
            if not got_items:
                if args.debug_library and not args.no_progress:
                    logger.info(f"[{idx}]   no title-matched results in '{nm}'")
                per_site_counts[skey] = cnt + 1
                continue

            alt_id = None
            alt_title = ""
            early_accepted = False
            if args.best_source:
                best_count = -1
                raw_score: int = 0
                limit = max(1, int(args.best_source_candidates))
                for cand in got_items[:limit]:
                    cid = SuwayomiClient.extract_manga_id(cand)
                    if cid is None:
                        continue
                    # Trigger Suwayomi to fetch the chapter list from the
                    # remote source. This populates the DB *and* returns the
                    # count in a single round-trip, so use it directly.
                    fetched_count = 0
                    try:
                        fetched_count = client.fetch_chapter_count(cid)
                    except Exception:
                        pass
                    ccount = 0
                    canon = 0
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
                        # If the DB-based count is still 0, trust the fetch
                        # mutation's direct count instead.
                        if ccount == 0 and fetched_count > 0:
                            ccount = fetched_count
                        # Always get canonical count for Comick comparison
                        try:
                            canon = client.get_manga_chapters_canonical_count(cid)
                        except Exception:
                            canon = ccount
                        if canon == 0 and fetched_count > 0:
                            canon = fetched_count
                        if prefer_frags and any(f in nm for f in prefer_frags):
                            ccount += int(args.prefer_boost)
                        try:
                            raw_score = (
                                client.get_manga_chapters_canonical_count(cid)
                                if args.best_source_canonical
                                else client.get_manga_chapters_count(cid)
                            )
                            if raw_score == 0 and fetched_count > 0:
                                raw_score = fetched_count
                        except Exception:
                            raw_score = fetched_count
                    except Exception:
                        ccount = 0
                        canon = 0
                        raw_score = 0
                    if args.debug_library and not args.no_progress:
                        ctitle = str(cand.get("title") or cand.get("name") or "")
                        logger.info(f"[{idx}]     cand id={cid} site='{nm}' score={ccount} canonical={canon} title='{ctitle[:60]}'")
                    # ── Comick sanity check ─────────────────────────────────
                    # Use the *canonical* count (de-duped by integer chapter
                    # number) against Comick — this catches false matches even
                    # when the raw count looks plausible due to sub-chapters.
                    if comick_canonical is not None and comick_canonical > 0:
                        comick_int = int(comick_canonical)
                        if canon > comick_int + 2:
                            # Canonical count exceeds Comick by more than 2 —
                            # allow up to 3× for genuine chapter renumbering /
                            # multi-season sources, otherwise reject.
                            if canon > comick_int * 3 + 2:
                                if not args.no_progress:
                                    ctitle = str(cand.get("title") or cand.get("name") or "")
                                    logger.info(
                                        f"[{idx}]     REJECTED cand id={cid} "
                                        f"canonical={canon} vs Comick {comick_int} — false match"
                                    )
                                continue
                            else:
                                if not args.no_progress:
                                    ctitle = str(cand.get("title") or cand.get("name") or "")
                                    logger.info(
                                        f"[{idx}]     ACCEPTED cand id={cid} has {ccount} ch "
                                        f"(canonical {canon}) vs Comick {comick_int} "
                                        f"— {ccount - canon} sub-chapters"
                                    )
                        elif canon >= comick_int - 2:
                            # Canonical count is close to Comick — perfect match.
                            # Early-accept: no need to evaluate more candidates.
                            if not args.no_progress:
                                logger.info(
                                    f"[{idx}]     MATCH cand id={cid} "
                                    f"canonical={canon} ≈ Comick {comick_int} — early accept"
                                )
                            alt_id = cid
                            alt_title = str(cand.get("title") or cand.get("name") or "")
                            best_count = ccount
                            if args.best_source_global:
                                if global_best is None or ccount > global_best[0]:
                                    global_best = (ccount, cid, src, alt_title)
                                if global_raw_max is None or raw_score > global_raw_max[0]:
                                    global_raw_max = (raw_score, cid, src)
                            early_accepted = True
                            break
                    if ccount >= max(0, int(args.min_chapters_per_alt)) and ccount > best_count:
                        best_count = ccount
                        alt_id = cid
                        alt_title = str(cand.get("title") or cand.get("name") or "")
                    if args.best_source_global and (global_raw_max is None or raw_score > global_raw_max[0]):
                        global_raw_max = (raw_score, cid, src)
                if early_accepted:
                    # Skip remaining sources — we have a confirmed match
                    break
                if args.best_source_global and alt_id is not None:
                    score_val = best_count
                    if global_best is None or score_val > global_best[0]:
                        global_best = (score_val, alt_id, src, alt_title)
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
                    logger.info(f"[{idx}] MIGRATE '{title}' -> '{alt_title}' via '{src.get('name')}' ({best_count} ch) -> OK (dry-run)")
            else:
                try:
                    added_any = client.add_to_library(alt_id)
                except Exception as e:
                    if args.debug_library and not args.no_progress:
                        logger.error(f"[{idx}]   add_to_library error for id={alt_id}: {e}")
                    added_any = False
                if not args.no_progress:
                    logger.info(f"[{idx}] MIGRATE '{title}' -> '{alt_title}' via '{src.get('name')}' ({best_count} ch) -> {'OK' if added_any else 'FAIL'}")

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
                # Track the winning source for adaptive ordering
                try:
                    _win_sid = int(src.get("id") or 0)
                    if _win_sid:
                        source_wins[_win_sid] = source_wins.get(_win_sid, 0) + 1
                except Exception:
                    pass
                if not args.dry_run:
                    cp.mark_done(mid_int)
                break

        # Global-best: add the single winner after scanning all sources
        if not added_any and args.best_source_global and global_best is not None:
            best_score, best_alt_id, src_best, best_alt_title = global_best
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
                    logger.info(f"[{idx}] MIGRATE '{title}' -> '{best_alt_title}' via '{src_best.get('name')}' ({best_score} ch, global-best) -> OK (dry-run)")
            else:
                try:
                    added_any = client.add_to_library(best_alt_id)
                except Exception as e:
                    if args.debug_library and not args.no_progress:
                        logger.error(f"[{idx}]   add_to_library error for id={best_alt_id}: {e}")
                    added_any = False
                if not args.no_progress:
                    logger.info(
                        f"[{idx}] MIGRATE '{title}' -> '{best_alt_title}' via '{src_best.get('name')}' ({best_score} ch, global-best) -> "
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
                # Track the winning source for adaptive ordering
                try:
                    _win_sid = int(src_best.get("id") or 0)
                    if _win_sid:
                        source_wins[_win_sid] = source_wins.get(_win_sid, 0) + 1
                except Exception:
                    pass
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
                                logger.info(f"[{idx}] ALSO KEEP '{title}' via '{raw_src.get('name')}' ({raw_count} ch, raw-max) -> OK (dry-run)")
                        else:
                            try:
                                ok2 = client.add_to_library(raw_alt_id)
                            except Exception as e:
                                if args.debug_library and not args.no_progress:
                                    logger.error(f"[{idx}]   add_to_library error for id={raw_alt_id}: {e}")
                                ok2 = False
                            if not args.no_progress:
                                logger.info(f"[{idx}] ALSO KEEP '{title}' via '{raw_src.get('name')}' ({raw_count} ch, raw-max) -> {'OK' if ok2 else 'FAIL'}")

        # Log to rejects bin when no migration happened
        if not added_any and rejects is not None:
            rejects.log(
                mid_int, title, "no_source_match",
                comick_chapters=comick_canonical,
            )

    if rejects is not None:
        rejects.close()
        if not args.no_progress:
            logger.info(f"Rejects written to {rejects.path}")
    logger.info(f"Migrate summary: migrated={migrated} skipped={skipped} failed={failed}")
    # Clear checkpoint on clean completion (no failures means we're done)
    if failed == 0 and not args.dry_run:
        cp.clear()
    return 0 if failed == 0 else 6

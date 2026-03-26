from __future__ import annotations

import re
import sys
import json
import csv
import argparse
import os
import getpass
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Dict, Any, Set
import math
from urllib.parse import urlparse

try:
    import pandas as pd  # Optional, only used for xlsx/csv convenience
except Exception:
    pd = None

import requests
import logging

# Ensure console printing never crashes on non-ASCII titles (common on Windows)
try:
    sys.stdout.reconfigure(errors="replace", line_buffering=True, write_through=True)  # type: ignore[attr-defined]
except Exception:
    try:
        sys.stdout.flush()
    except Exception:
        pass
try:
    sys.stderr.reconfigure(errors="replace", line_buffering=True, write_through=True)  # type: ignore[attr-defined]
except Exception:
    try:
        sys.stderr.flush()
    except Exception:
        pass

# MangaDex API base (public)
MANGADEX_API = "https://api.mangadex.org"

# Global chapter sync config (set in main from CLI flags)
CHAPTER_SYNC_CONF: Dict[str, Any] = {}
# Global debug flag for read sync
READ_SYNC_DEBUG: bool = False
MISSING_REPORT_PATH: Optional[Path] = None

logger = logging.getLogger("seiyomi")

# Utility early so helper functions can use it
def truncate_text(t: str, limit: int = 200) -> str:
    t = (t or "").replace('\n', ' ')[:limit]
    return t + ("..." if len(t) == limit else "")

# --- Title matching helpers (extracted to seiyomi.matching.titles) ---
from seiyomi.matching.titles import (
    _normalize_title_tokens,
    _title_similarity,
    _is_title_match,
    _STOPWORDS,
)  # noqa: F401


# --- CSV parsing (extracted to seiyomi.importers.csv_import) ---
from seiyomi.importers.csv_import import (  # noqa: F401
    CsvItem,
    CSV_KIND_COMICK,
    CSV_KIND_MANGANATO,
    CSV_KIND_AUTO,
    _normalize_last_read,
    _normalize_chapter_hint,
    _parse_chapter_hint_to_float,
    _split_synonyms,
    detect_csv_kind,
    parse_comick_csv,
    parse_manganato_csv,
    load_csv_items,
    parse_csv_column_map,
)


def _extract_md_titles(entry: Dict[str, Any]) -> List[str]:
    titles: List[str] = []
    attrs = entry.get('attributes') if isinstance(entry, dict) else None
    if isinstance(attrs, dict):
        title_map = attrs.get('title')
        if isinstance(title_map, dict):
            for val in title_map.values():
                if isinstance(val, str) and val:
                    titles.append(val)
        alt_titles = attrs.get('altTitles')
        if isinstance(alt_titles, list):
            for alt in alt_titles:
                if isinstance(alt, dict):
                    for val in alt.values():
                        if isinstance(val, str) and val:
                            titles.append(val)
        if isinstance(attrs.get('originalLanguage'), str):
            orig_title = attrs.get('originalLanguageTitle')
            if isinstance(orig_title, str) and orig_title:
                titles.append(orig_title)
    name = entry.get('name') if isinstance(entry, dict) else None
    if isinstance(name, str) and name:
        titles.append(name)
    return titles


# --- MangaDex helpers (extracted to seiyomi.clients.mangadex) ---
from seiyomi.clients.mangadex import (  # noqa: E402, F401
    MANGADEX_API,
    login_mangadex,
    login_mangadex_verbose,
    fetch_all_follows,
    fetch_all_follows_adv,
    fetch_reading_statuses,
    fetch_single_status,
    fetch_all_statuses,
    fetch_mangadex_read_chapters,
    fetch_title_from_mangadex,
    fetch_user_lists,
    fetch_manga_ids_in_list,
    _search_mangadex_titles,
)


# stub — monolith callers that used _search_mangadex_titles also locally call find_mangadex_match_for_item;
# keep this function here (it depends on CsvItem which hasn't moved yet)
def _search_mangadex_titles_local(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    # just forward to the extracted version
    return _search_mangadex_titles(query, limit)  # noqa: F811


def find_mangadex_match_for_item(item: CsvItem, threshold: float = 0.6, strict_exact: bool = False) -> Optional[Tuple[str, str, float]]:
    queries: List[str] = []
    if item.title:
        queries.append(item.title)
    for syn in item.synonyms:
        if syn and syn not in queries:
            queries.append(syn)
    seen: Set[str] = set()
    best: Optional[Tuple[str, str, float]] = None
    for query in queries:
        slug = query.strip()
        if not slug:
            continue
        norm = slug.lower()
        if norm in seen:
            continue
        seen.add(norm)
        candidates = _search_mangadex_titles(slug)
        for cand in candidates:
            md_id = cand.get('id')
            if not isinstance(md_id, str):
                continue
            for cand_title in _extract_md_titles(cand):
                if not cand_title:
                    continue
                if strict_exact:
                    if not _is_title_match(slug, cand_title, threshold=threshold, strict_exact=True):
                        continue
                    score = 1.0 if _normalize_title_tokens(slug) == _normalize_title_tokens(cand_title) else threshold
                else:
                    score = _title_similarity(slug, cand_title)
                    if score < threshold:
                        continue
                if best is None or score > best[2]:
                    best = (md_id, cand_title, score)
        if best and best[2] >= 0.92:
            break
    return best


def _gather_titles_from_library_entry(entry: Dict[str, Any]) -> List[str]:
    titles: List[str] = []
    for key in ("title", "name"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            titles.append(val)
    manga_info = entry.get('manga')
    if isinstance(manga_info, dict):
        for key in ("title", "name"):
            val = manga_info.get(key)
            if isinstance(val, str) and val.strip():
                titles.append(val)
    info = entry.get('info')
    if isinstance(info, dict):
        for key in ("title", "name"):
            val = info.get(key)
            if isinstance(val, str) and val.strip():
                titles.append(val)
    return titles


def _register_library_title(
    mapper: Dict[str, int],
    internal_id: int,
    title: str,
    norms_map: Optional[Dict[int, Set[str]]] = None,
    title_map: Optional[Dict[int, str]] = None,
) -> None:
    norm = " ".join(_normalize_title_tokens(title))
    if norm and norm not in mapper:
        mapper[norm] = internal_id
    if norm and norms_map is not None:
        norms_map.setdefault(internal_id, set()).add(norm)
    if title_map is not None and title and title.strip():
        title_map.setdefault(internal_id, title.strip())


def _build_library_lookup(entries: List[Dict[str, Any]]) -> Tuple[Dict[str, int], Dict[int, Set[str]], Dict[int, str]]:
    lookup: Dict[str, int] = {}
    norms_by_id: Dict[int, Set[str]] = {}
    title_by_id: Dict[int, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get('id') or entry.get('mangaId') or entry.get('manga_id')
        try:
            internal_id = int(raw_id)
        except Exception:
            continue
        for title in _gather_titles_from_library_entry(entry):
            _register_library_title(lookup, internal_id, title, norms_by_id, title_by_id)
    return lookup, norms_by_id, title_by_id


def _slug_source(src: Dict[str, Any]) -> str:
    base = (src.get('name') or src.get('apkName') or src.get('pkgName') or src.get('className') or "").lower()
    return re.sub(r"[^a-z0-9]+", "", base)


def _csv_item_source_hints(item: CsvItem) -> List[str]:
    hints: List[str] = []
    if item.source:
        hints.append(item.source.lower())
    for key, value in item.external_ids.items():
        if key:
            hints.append(str(key).lower())
        if value:
            val_lower = str(value).lower()
            try:
                parsed = urlparse(value)
                if parsed.netloc:
                    hints.append(parsed.netloc)
            except Exception:
                pass
            for token in re.findall(r"[a-z0-9]+", val_lower):
                if token in {"https", "http", "www", "com", "net", "org", "m", "app"}:
                    continue
                hints.append(token)
    cleaned: List[str] = []
    for hint in hints:
        slug = re.sub(r"[^a-z0-9]+", "", hint)
        if slug and slug not in cleaned:
            cleaned.append(slug)
    return cleaned


def _select_candidate_sources(sources: List[Dict[str, Any]], item: CsvItem) -> List[Dict[str, Any]]:
    if not sources:
        return []
    hints = _csv_item_source_hints(item)
    if not hints:
        return sources
    primary: List[Dict[str, Any]] = []
    for src in sources:
        slug = _slug_source(src)
        if not slug:
            continue
        if any(hint in slug for hint in hints):
            primary.append(src)
    return primary or sources


def _score_source_candidate(item: CsvItem, candidate: Dict[str, Any], match_title: str) -> float:
    score = _title_similarity(item.title, match_title)
    for syn in item.synonyms:
        score = max(score, _title_similarity(syn, match_title))
    meta = " ".join(str(candidate.get(k, "")) for k in ("url", "link", "key", "sourceUrl", "source_url"))
    meta = meta.lower()
    for ext in item.external_ids.values():
        if not ext:
            continue
        ext_norm = re.sub(r"[^a-z0-9]+", "", str(ext).lower())
        if ext_norm and ext_norm in re.sub(r"[^a-z0-9]+", "", meta):
            score += 0.4
    return min(score, 1.0)


def _find_best_source_candidate(
    client: SuwayomiClient,
    sources: List[Dict[str, Any]],
    item: CsvItem,
    show_progress: bool,
    prefix: str,
    title_threshold: float,
    title_strict: bool,
) -> Optional[Tuple[int, Dict[str, Any], str, float]]:
    best: Optional[Tuple[int, Dict[str, Any], str, float]] = None
    title_variants: List[str] = []

    def _add_variant(text: str) -> None:
        text = (text or "").strip()
        if text and text not in title_variants:
            title_variants.append(text)

    _add_variant(item.title)
    for syn in item.synonyms:
        _add_variant(syn)
    if item.title:
        base = re.sub(r"[\(\[\{].*?[\)\]\}]", "", item.title)
        base = re.sub(r"[^0-9A-Za-z\s]", " ", base)
        _add_variant(base)

    for src in sources:
        sid = src.get('id')
        try:
            source_id = int(sid)
        except Exception:
            continue
        for query in title_variants:
            try:
                resp = client.search_source(source_id, query, page=1)
            except Exception as exc:
                if show_progress:
                    logger.warning(f"{prefix}WARN search {src.get('name') or sid}: {exc}")
                continue
            items = SuwayomiClient.normalize_search_items(resp)
            for cand in items:
                manga_id = SuwayomiClient.extract_manga_id(cand)
                if manga_id is None:
                    continue
                cand_title = str(cand.get('title') or cand.get('name') or "")
                if not cand_title:
                    continue
                compare_texts = [item.title] + [syn for syn in item.synonyms if syn]
                if item.title:
                    normalized_base = re.sub(r"[\(\[\{].*?[\)\]\}]", "", item.title)
                    normalized_base = re.sub(r"[^0-9A-Za-z\s]", " ", normalized_base).strip()
                    if normalized_base and normalized_base not in compare_texts:
                        compare_texts.append(normalized_base)
                sims = [_title_similarity(txt, cand_title) for txt in compare_texts if txt]
                best_sim = max(sims) if sims else 0.0
                passes = False
                if title_strict:
                    for txt in compare_texts:
                        if txt and _is_title_match(txt, cand_title, threshold=max(0.0, min(1.0, title_threshold)), strict_exact=True):
                            passes = True
                            break
                else:
                    passes = best_sim >= max(0.0, min(1.0, title_threshold))
                if not passes:
                    continue
                score = _score_source_candidate(item, cand, cand_title)
                if best is None or score > best[3]:
                    best = (int(manga_id), src, cand_title, score)
            if best and best[3] >= 0.95:
                return best
    return best


def _apply_status_category_direct(
    client: SuwayomiClient,
    internal_id: int,
    status_value: Optional[str],
    status_category_map: Dict[str, int],
    status_default_category: Optional[int],
    status_map_debug: bool,
    prefix: str,
    show_progress: bool,
    dry_run: bool,
) -> None:
    status_norm = (status_value or "").strip().lower()
    target_cat: Optional[int] = None
    via = ''
    if status_norm and status_category_map:
        target_cat = status_category_map.get(status_norm)
        via = 'map'
    if target_cat is None and status_default_category is not None:
        target_cat = status_default_category
        via = 'default'
    if target_cat is None:
        if status_map_debug and show_progress:
            display = status_value or '(none)'
            logger.info(f"{prefix}STATUS {display} -> no mapping applied")
        return
    if dry_run:
        if status_map_debug and show_progress:
            display = status_value or '(none)'
            logger.info(f"{prefix}STATUS {display} -> cat {target_cat} ({via}) (dry-run)")
        return
    try:
        ok = client.add_manga_to_category(internal_id, target_cat)
        if status_map_debug and show_progress:
            display = status_value or '(none)'
            logger.error(f"{prefix}STATUS {display} -> cat {target_cat} ({via}) {'OK' if ok else 'FAIL'}")
    except Exception as exc:
        if status_map_debug and show_progress:
            display = status_value or '(none)'
            logger.error(f"{prefix}STATUS {display} -> cat {target_cat} ERROR {exc}")


def process_csv_direct_items(
    client: SuwayomiClient,
    items: List[CsvItem],
    *,
    dry_run: bool,
    prefer_existing: bool,
    no_add_library: bool,
    status_category_map: Dict[str, int],
    status_default_category: Optional[int],
    status_map_debug: bool,
    show_progress: bool,
    apply_read_progress: bool,
    chapter_sync_conf: Optional[Dict[str, Any]],
    title_threshold: float,
    title_strict: bool,
) -> Tuple[List[Tuple[CsvItem, int, str]], List[Tuple[CsvItem, int, str]], List[Tuple[CsvItem, str]], int, int]:
    if not items:
        return [], [], [], 0, 0

    if show_progress:
        logger.info(f"[CSV] Preparing library snapshot for {len(items)} CSV items...")
    try:
        library_entries = client.get_library_graphql() or client.get_library() or []
    except Exception:
        library_entries = []
    if show_progress:
        logger.info(f"[CSV] Library snapshot loaded ({len(library_entries)} entries).")
    lookup, norms_by_id, title_by_id = _build_library_lookup(library_entries)
    if show_progress:
        logger.info("[CSV] Fetching configured sources from Suwayomi...")
    try:
        sources = client.get_sources()
    except Exception:
        sources = []
    if show_progress:
        logger.info(f"[CSV] Source list ready ({len(sources)} entries).")

    added: List[Tuple[CsvItem, int, str]] = []
    matched_existing: List[Tuple[CsvItem, int, str]] = []
    failures: List[Tuple[CsvItem, str]] = []
    progress_applied = 0
    progress_skipped = 0
    rpm = 300
    delay = 0.0
    only_if_ahead = False
    if chapter_sync_conf:
        rpm = int(chapter_sync_conf.get('rpm', rpm))
        delay = float(chapter_sync_conf.get('delay', delay) or 0.0)
        only_if_ahead = bool(chapter_sync_conf.get('only_if_ahead'))

    total = len(items)

    def _apply_cross_source_progress(
        primary_id: int,
        target: float,
        shared_norms: Set[str],
        prefix: str,
    ) -> None:
        nonlocal progress_applied, progress_skipped
        if not chapter_sync_conf or not chapter_sync_conf.get('across_sources'):
            return
        if not shared_norms:
            return
        seen_targets: Set[int] = set()
        for other_id, other_norms in norms_by_id.items():
            if other_id == primary_id:
                continue
            if other_id in seen_targets:
                continue
            if not other_norms or not shared_norms.intersection(other_norms):
                continue
            seen_targets.add(other_id)
            label = title_by_id.get(other_id, f"id={other_id}")
            if dry_run:
                if show_progress:
                    logger.info(f"{prefix}(dry-run) would also mark '{label}' (id={other_id}) up to chapter {target} [cross-source]")
                continue
            if only_if_ahead:
                current = _compute_entry_progress_by_number(client, other_id)
                if current is not None and current >= target:
                    progress_skipped += 1
                    if show_progress:
                        logger.info(f"{prefix}SKIP cross-source '{label}' (id={other_id}) already at {current}")
                    continue
            try:
                _mark_entry_up_to_number(client, other_id, target, rpm, dry_run=False)
                progress_applied += 1
                if show_progress:
                    logger.info(f"{prefix}Cross-source marked '{label}' (id={other_id}) up to chapter {target}")
            except Exception as exc:
                progress_skipped += 1
                if show_progress:
                    logger.warning(f"{prefix}WARN cross-source read-progress failed for '{label}' (id={other_id}): {exc}")

    if show_progress and not items:
        logger.info("[CSV] No CSV rows to process after filtering.")
    for idx, item in enumerate(items, 1):
        prefix = f"[CSV {idx}/{total}] " if show_progress else ""
        norm_candidates: List[str] = []
        for label in [item.title] + list(item.synonyms):
            norm = " ".join(_normalize_title_tokens(label))
            if norm and norm not in norm_candidates:
                norm_candidates.append(norm)
        norm_set: Set[str] = set(norm_candidates)
        internal_id = None
        for norm in norm_candidates:
            internal_id = lookup.get(norm)
            if internal_id is not None:
                break
        if internal_id is not None:
            _register_library_title(lookup, internal_id, item.title, norms_by_id, title_by_id)
            for syn in item.synonyms:
                _register_library_title(lookup, internal_id, syn, norms_by_id, title_by_id)
            matched_existing.append((item, internal_id, 'existing'))
            _apply_status_category_direct(
                client=client,
                internal_id=internal_id,
                status_value=item.status,
                status_category_map=status_category_map,
                status_default_category=status_default_category,
                status_map_debug=status_map_debug,
                prefix=prefix,
                show_progress=show_progress,
                dry_run=dry_run,
            )
            if apply_read_progress and item.last_read_chapter:
                target = _parse_chapter_hint_to_float(item.last_read_chapter)
                if target is not None:
                    if dry_run:
                        progress_applied += 1
                        if show_progress:
                            logger.info(f"{prefix}(dry-run) would mark up to chapter {target}")
                        _apply_cross_source_progress(internal_id, target, norm_set, prefix)
                    else:
                        if delay > 0:
                            time.sleep(delay)
                        if only_if_ahead:
                            current = _compute_entry_progress_by_number(client, internal_id)
                            if current is not None and current >= target:
                                progress_skipped += 1
                                continue
                        try:
                            _mark_entry_up_to_number(client, internal_id, target, rpm, dry_run=False)
                            progress_applied += 1
                            _apply_cross_source_progress(internal_id, target, norm_set, prefix)
                        except Exception as exc:
                            progress_skipped += 1
                            if show_progress:
                                logger.warning(f"{prefix}WARN read-progress failed: {exc}")
            continue
        if prefer_existing:
            failures.append((item, "no existing entry"))
            if show_progress:
                logger.info(f"{prefix}SKIP '{item.title}' (prefer-existing)")
            continue
        if no_add_library:
            failures.append((item, "--no-add-library"))
            if show_progress:
                logger.info(f"{prefix}SKIP '{item.title}' (--no-add-library)")
            continue
        if show_progress:
            logger.info(f"{prefix}Resolving '{item.title}' against Suwayomi sources...")
        candidate_sources = _select_candidate_sources(sources, item)
        best = _find_best_source_candidate(
            client,
            candidate_sources,
            item,
            show_progress,
            prefix,
            title_threshold,
            title_strict,
        )
        if not best:
            failures.append((item, "no source candidate"))
            if show_progress:
                logger.error(f"{prefix}FAIL '{item.title}' (no source match)")
            continue
        manga_id, src, cand_title, score = best
        label = str(src.get('name') or src.get('apkName') or src.get('pkgName') or 'source')
        if dry_run:
            added.append((item, manga_id, label))
            if show_progress:
                logger.info(f"{prefix}(dry-run) would add '{item.title}' via {label} -> '{cand_title}' score {score:.2f}")
            if apply_read_progress and item.last_read_chapter:
                target = _parse_chapter_hint_to_float(item.last_read_chapter)
                if target is not None:
                    _apply_cross_source_progress(manga_id, target, norm_set, prefix)
            continue
        ok = False
        try:
            ok = client.add_to_library(manga_id)
        except Exception as exc:
            failures.append((item, f"add failed: {exc}"))
            if show_progress:
                logger.error(f"{prefix}FAIL add '{item.title}': {exc}")
            continue
        if not ok:
            failures.append((item, "add returned false"))
            if show_progress:
                logger.error(f"{prefix}FAIL add '{item.title}' (returned False)")
            continue
        added.append((item, manga_id, label))
        # update lookup for subsequent matches in this run
        _register_library_title(lookup, manga_id, cand_title, norms_by_id, title_by_id)
        _register_library_title(lookup, manga_id, item.title, norms_by_id, title_by_id)
        for syn in item.synonyms:
            _register_library_title(lookup, manga_id, syn, norms_by_id, title_by_id)
        _apply_status_category_direct(
            client=client,
            internal_id=manga_id,
            status_value=item.status,
            status_category_map=status_category_map,
            status_default_category=status_default_category,
            status_map_debug=status_map_debug,
            prefix=prefix,
            show_progress=show_progress,
            dry_run=dry_run,
        )
        if apply_read_progress and item.last_read_chapter:
            target = _parse_chapter_hint_to_float(item.last_read_chapter)
            if target is not None:
                if delay > 0:
                    time.sleep(delay)
                try:
                    _mark_entry_up_to_number(client, manga_id, target, rpm, dry_run=False)
                    progress_applied += 1
                    _apply_cross_source_progress(manga_id, target, norm_set, prefix)
                except Exception as exc:
                    progress_skipped += 1
                    if show_progress:
                        logger.warning(f"{prefix}WARN read-progress failed: {exc}")
    return added, matched_existing, failures, progress_applied, progress_skipped

# --- Helpers: detect MangaDex IDs/URLs ---
MD_ID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
MD_URL_RE = re.compile(r"https?://(www\.)?mangadex\.org/title/([0-9a-fA-F-]{36})(?:/|$)")


def extract_mangadex_ids(text: str) -> List[str]:
    ids = []
    for url_match in MD_URL_RE.finditer(text):
        ids.append(url_match.group(2))
    for id_match in MD_ID_RE.finditer(text):
        ids.append(id_match.group(0))
    # de-dup preserving order
    seen = set()
    uniq: List[str] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


# --- Input parsing ---

def read_any(path: Path) -> List[str]:
    suffix = path.suffix.lower()
    data: List[str] = []
    if suffix in {".txt", ".log", ".md", ".html", ".htm"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        data = extract_mangadex_ids(text)
    elif suffix in {".json"}:
        obj = json.loads(path.read_text(encoding="utf-8"))
        def walk(o: Any):
            if isinstance(o, str):
                for i in extract_mangadex_ids(o):
                    yield i
            elif isinstance(o, dict):
                for v in o.values():
                    yield from walk(v)
            elif isinstance(o, list):
                for v in o:
                    yield from walk(v)
        data = list(dict.fromkeys(walk(obj)))
    elif suffix in {".csv"}:
        # try simple pass-through first
        with path.open(newline='', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            buf: List[str] = []
            for row in reader:
                for cell in row:
                    buf.extend(extract_mangadex_ids(str(cell)))
        # unique preserve order
        data = list(dict.fromkeys(buf))
    elif suffix in {".xlsx", ".xls"}:
        if pd is None:
            raise SystemExit("pandas/openpyxl are required for Excel files. Install with: python -m pip install pandas openpyxl")
        buf: List[str] = []
        # Read all sheets
        xls = pd.read_excel(path, sheet_name=None, dtype=str)
        for _, df in xls.items():
            for val in df.astype(str).to_numpy().flatten():
                buf.extend(extract_mangadex_ids(str(val)))
        data = list(dict.fromkeys(buf))
    else:
        # Fallback: treat as text
        text = path.read_text(encoding="utf-8", errors="ignore")
        data = extract_mangadex_ids(text)
    return data


# --- Suwayomi client (imported from package) ---
from seiyomi.clients.suwayomi import SuwayomiClient  # noqa: E402


# --- Import logic ---
# --- Import logic ---

def find_mangadex_source_id(sources: List[Dict[str, Any]]) -> Optional[int]:
    for s in sources:
        name = (s.get("name") or "").lower()
        apk = (s.get("apkName") or "").lower()
        # Mangadex source typically has name like "MangaDex" and package containing "mangadex"
        if "mangadex" in name or "mangadex" in apk:
            return int(s["id"]) if "id" in s else None
    return None


def search_by_mangadex_id(client: SuwayomiClient, source_id: int, md_id: str) -> Optional[int]:
    """Attempt direct UUID search in source. Returns manga_id or None."""
    try:
        resp = client.search_source(source_id, md_id, page=1)
    except Exception:
        return None
    items = resp.get("mangaList") or resp.get("mangaListData") or resp.get("manga_list") or []
    for it in items:
        url = str(it.get("url", ""))
        if md_id in url:
            return int(it.get("id"))
    for it in items:
        if str(it.get("key", "")) == md_id:
            return int(it.get("id"))
    return None


def search_by_title(client: SuwayomiClient, source_id: int, title: str) -> Optional[int]:
    """Search source by title text and attempt fuzzy containment match."""
    if not title:
        return None
    try:
        resp = client.search_source(source_id, title, page=1)
    except Exception:
        return None
    items = resp.get("mangaList") or resp.get("mangaListData") or resp.get("manga_list") or []
    # Prefer exact/normalized equality first
    exact_norm = " ".join(_normalize_title_tokens(title))
    exact_id: Optional[int] = None
    for it in items:
        cand = str(it.get("title") or it.get("name") or "")
        if not cand:
            continue
        if " ".join(_normalize_title_tokens(cand)) == exact_norm:
            try:
                return int(it.get("id"))
            except Exception:
                continue
    # Otherwise, pick the best similarity above threshold
    best_id: Optional[int] = None
    best_score = 0.0
    for it in items:
        cand = str(it.get("title") or it.get("name") or "")
        if not cand:
            continue
        try:
            score = _title_similarity(title, cand)
        except Exception:
            score = 0.0
        if score > best_score:
            best_score = score
            try:
                best_id = int(it.get("id"))
            except Exception:
                best_id = None
    # Require a reasonable similarity to avoid random top lists
    return best_id if best_score >= 0.6 else None


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
    from seiyomi.operations.import_follows import import_ids as _import_ids
    return _import_ids(
        client=client,
        ids=ids,
        dry_run=dry_run,
        use_title_fallback=use_title_fallback,
        show_progress=show_progress,
        throttle=throttle,
        category_id=category_id,
        reading_statuses=reading_statuses,
        status_category_map=status_category_map,
        status_default_category=status_default_category,
        session_token=session_token,
        chapter_sync_conf=chapter_sync_conf,
        status_map_debug=status_map_debug,
        assume_missing_status=assume_missing_status,
        lists_membership=lists_membership,
        lists_category_map=lists_category_map,
        lists_ignore_set=lists_ignore_set,
        rehome_conf=rehome_conf,
    )

# ---------------- MangaDex follows helpers now in seiyomi.clients.mangadex ---------------- #
# (imported near the top of this file — see after _extract_md_titles)


# --- Read-sync helpers (Suwayomi-side, extracted to seiyomi.operations.read_sync) ---
from seiyomi.operations.read_sync import (  # noqa: E402, F401
    fetch_suwayomi_chapters,
    extract_chapter_uuid_from_item,
    mark_chapter_read,
    sync_read_chapters_by_uuid,
)

MD_CHAPTER_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def sync_read_chapters_for_manga(
    client: "SuwayomiClient",
    session_token: str,
    manga_md_id: str,
    manga_internal_id: int,
    dry_run: bool,
    rpm: int,
    show_progress: bool,
    prefix: str,
) -> None:
    """Backward-compat wrapper: fetches MangaDex read-UUIDs then delegates to sync_read_chapters_by_uuid."""
    md_read = fetch_mangadex_read_chapters(session_token, manga_md_id)
    if not md_read:
        return
    sync_read_chapters_by_uuid(
        client=client,
        manga_internal_id=manga_internal_id,
        md_read_uuids=md_read,
        dry_run=dry_run,
        rpm=rpm,
        show_progress=show_progress,
        prefix=prefix,
        missing_report_path=MISSING_REPORT_PATH,
        manga_md_id=manga_md_id,
        fetch_title_fn=fetch_title_from_mangadex,
    )


# --- Cross-source read sync helpers (by chapter number) ---
from seiyomi.operations.read_sync import (  # noqa: E402, F401
    _parse_chapter_number_from_item,
    _build_fraction_map,
    _is_fraction_canonical,
    compute_entry_progress_by_number as _compute_entry_progress_by_number,
    mark_entry_up_to_number as _mark_entry_up_to_number,
)


def _norm_title_for_match(title: str) -> str:
    return " ".join(_normalize_title_tokens(title or ""))


def _compute_md_progress_by_numbers(session_token: str, manga_md_id: str) -> Optional[float]:
    uuids = fetch_mangadex_read_chapters(session_token, manga_md_id)
    if not uuids:
        return None
    nums: List[float] = []
    for u in uuids:
        try:
            r = requests.get(f"{MANGADEX_API}/chapter/{u}", timeout=12)
            if r.status_code != 200:
                continue
            ch = (r.json() or {}).get("data", {}).get("attributes", {})
            s = str(ch.get("chapter") or "").strip()
            if not s:
                continue
            m = re.search(r"(\d+(?:\.\d+)?)", s)
            if not m:
                continue
            nums.append(float(m.group(1)))
        except Exception:
            continue
    if not nums:
        return None
    frac_map = _build_fraction_map(nums)
    canon = [n for n in nums if _is_fraction_canonical(n, frac_map)]
    return max(canon) if canon else None

def sync_cross_source_read_for_md(
    client: SuwayomiClient,
    manga_md_id: str,
    session_token: str,
    rpm: int,
    dry_run: bool = False,
    only_if_ahead: bool = False,
    title_threshold: float = 0.6,
    title_strict: bool = False,
) -> None:
    # Resolve title from MangaDex to find same-title entries
    title = fetch_title_from_mangadex(manga_md_id) or ""
    if not title:
        return
    norm = _norm_title_for_match(title)
    md_max = _compute_md_progress_by_numbers(session_token, manga_md_id)
    if md_max is None:
        return
    lib = client.get_library_graphql() or client.get_library() or []
    for it in lib:
        mid = it.get("id") or (it.get("manga") or {}).get("id") or it.get("mangaId")
        t = it.get("title") or it.get("name") or ((it.get("manga") or {}).get("title") or (it.get("manga") or {}).get("name"))
        if not (mid and t):
            continue
        try:
            mid_int = int(mid)
        except Exception:
            continue
        # Use fuzzy/containment-aware title matching to link entries across sources
        if not _is_title_match(str(t), title, threshold=max(0.0, min(1.0, float(title_threshold))), strict_exact=bool(title_strict)):
            if READ_SYNC_DEBUG:
                try:
                    logger.debug(f"[read-debug] cross-source skip: '{truncate_text(str(t),80)}' not match '{truncate_text(title,80)}' (thr={title_threshold}{' strict' if title_strict else ''})")
                except Exception:
                    pass
            continue
        cur = _compute_entry_progress_by_number(client, mid_int)
        if only_if_ahead and not (md_max > cur):
            if READ_SYNC_DEBUG:
                try:
                    logger.debug(f"[read-debug] cross-source skip id={mid_int}: md_max={md_max} <= current={cur}")
                except Exception:
                    pass
            continue
        if READ_SYNC_DEBUG:
            try:
                logger.debug(f"[read-debug] cross-source apply id={mid_int}: md_max={md_max}, current={cur}")
            except Exception:
                pass
        _mark_entry_up_to_number(client, mid_int, md_max, rpm, dry_run=dry_run)

def compute_md_missing_stats(client: SuwayomiClient, session_token: str, md_id: str) -> Optional[Dict[str, Any]]:
    """Compute markable/marked/missing for a MangaDex ID against the MangaDex source entry in Suwayomi.
    Returns dict with title, md_id, markable, marked, missing; or None if unresolved.
    """
    try:
        title = fetch_title_from_mangadex(md_id) or md_id
        # Find MangaDex source internal id
        srcs = client.get_sources()
        md_source_id = find_mangadex_source_id(srcs)
        if not md_source_id:
            return None
        # Resolve manga internal id in Suwayomi for this MD id
        internal_id = search_by_mangadex_id(client, md_source_id, md_id)
        if internal_id is None:
            # Fallback by title search
            if title:
                internal_id = search_by_title(client, md_source_id, title)
        if internal_id is None:
            return None
        # Fetch chapters in Suwayomi and build UUID map
        su_chapters = fetch_suwayomi_chapters(client, internal_id) or []
        uuid_to_item: Dict[str, Dict[str, Any]] = {}
        for it in su_chapters:
            u = extract_chapter_uuid_from_item(it)
            if u:
                uuid_to_item[u] = it
        if not uuid_to_item:
            # no chapters loaded yet
            return {
                'title': title,
                'md_id': md_id,
                'markable': 0,
                'marked': 0,
                'missing': 'unknown',
            }
        md_read = fetch_mangadex_read_chapters(session_token, md_id) or []
        markable = 0
        marked = 0
        for u in md_read:
            it = uuid_to_item.get(u)
            if it is not None:
                markable += 1
                if it.get('read') or it.get('isRead'):
                    marked += 1
        missing = max(0, len(md_read) - markable)
        return {
            'title': title,
            'md_id': md_id,
            'markable': markable,
            'marked': marked,
            'missing': missing,
        }
    except Exception:
        return None


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Suwayomi library manager — import, migrate, clean up.")
    p.add_argument("input_file", type=Path, nargs="?", help="Optional path to bookmarks file (txt/csv/xlsx/json/html). Omit when using --from-follows only.")
    p.add_argument("--from-csv", dest="csv_files", action="append", type=Path, help="Path to a CSV export (Comick/Manganato). Repeat to import multiple files.")
    p.add_argument("--csv-kind", choices=[CSV_KIND_AUTO, CSV_KIND_COMICK, CSV_KIND_MANGANATO], default=CSV_KIND_AUTO, help="Force CSV schema detection for --from-csv (default: auto detect).")
    p.add_argument("--csv-col-map", action="append", help="Override CSV column names (key=value, comma-separated). Repeatable.")
    p.add_argument("--csv-status-to-category", help="Map CSV status values to category IDs (e.g. reading=5,completed=9).")
    p.add_argument("--csv-title-threshold", type=float, default=0.6, help="Similarity threshold (0..1) when matching CSV rows to MangaDex titles (default 0.6).")
    p.add_argument("--csv-title-strict", action="store_true", help="Require near-exact normalized title matches for CSV rows (disables fuzzy-only matches).")
    # --csv-via-mangadex: opt-in MangaDex resolution (direct-to-Suwayomi is the default).
    # --csv-no-mangadex is kept as a hidden backward-compat alias (was the old inverted flag).
    p.add_argument("--csv-via-mangadex", action="store_true",
                   help="Resolve CSV rows via MangaDex title lookup before importing (default: direct Suwayomi import).")
    p.add_argument("--csv-no-mangadex", dest="csv_via_mangadex", action="store_false",
                   help=argparse.SUPPRESS)
    p.add_argument("--csv-apply-read-progress", action="store_true", help="Record last read chapter hints from CSV rows for later read-sync attempts.")
    p.add_argument("--csv-prefer-existing", action=argparse.BooleanOptionalAction, default=False, help="Skip CSV rows when a matching title already exists in Suwayomi (default: off). Use --csv-prefer-existing to enable or --no-csv-prefer-existing to disable explicitly.")
    p.add_argument("--base-url", required=True, help="Suwayomi base URL, e.g. http://localhost:4567")
    p.add_argument("--auth-mode", choices=["auto", "basic", "simple", "bearer"], default="auto")
    p.add_argument("--username", help="Username for BASIC or SIMPLE login (if applicable)")
    p.add_argument("--password", help="Password for BASIC or SIMPLE login (if applicable)")
    p.add_argument("--token", help="Bearer token for UI_LOGIN mode (Settings -> API Tokens)")
    p.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")
    p.add_argument("--verbose", "-v", action="store_true", default=False,
                    help="Show debug-level output.")
    p.add_argument("--dry-run", action="store_true", help="Do not modify library, just simulate")
    p.add_argument("--no-title-fallback", action="store_true", help="Disable title lookup fallback via MangaDex API when direct UUID search fails")
    p.add_argument("--no-progress", action="store_true", help="Disable per-item progress output")
    p.add_argument("--throttle", type=float, default=0.0, help="Sleep seconds between items (avoid rate limits)")
    p.add_argument("--category-id", type=int, help="Optional Suwayomi category id to assign each added manga")
    # Follows fetch options
    p.add_argument("--from-follows", action="store_true", help="Fetch followed manga from MangaDex for the authenticated user and include them")
    p.add_argument("--follows-json", type=Path, help="Write fetched follows (id + title) to this JSON file")
    p.add_argument("--md-username", help="MangaDex username (or set MANGADEX_USERNAME env)")
    p.add_argument("--md-password", help="MangaDex password (or set MANGADEX_PASSWORD env). If omitted and needed, you'll be prompted.")
    p.add_argument("--md-client-id", help="MangaDex client id (optional; or env MANGADEX_CLIENT_ID)")
    p.add_argument("--md-client-secret", help="MangaDex client secret (optional; or env MANGADEX_CLIENT_SECRET)")
    p.add_argument("--md-2fa", help="MangaDex 2FA/OTP code if your account has 2FA enabled")
    p.add_argument("--debug-login", action="store_true", help="Print diagnostic details if MangaDex login fails (redacts password)")
    p.add_argument("--debug-follows", action="store_true", help="Verbose pagination diagnostics for follows fetch")
    p.add_argument("--max-follows", type=int, help="Optional cap on number of follows to fetch (diagnostics/testing)")
    p.add_argument("--md-login-only", action="store_true", help="Login to MangaDex to obtain a session for read-sync, without fetching/merging follows")
    # Reading status & chapters sync
    p.add_argument("--import-reading-status", action="store_true", help="Fetch MangaDex reading statuses and map to categories")
    p.add_argument("--status-category-map", help="Comma list mapping status=categoryId (e.g. completed=5,reading=2,on_hold=7,dropped=8,plan_to_read=9,re_reading=10)")
    p.add_argument("--status-default-category", type=int, help="Fallback category id if a status has no explicit mapping")
    p.add_argument("--import-read-chapters", action="store_true", help="Fetch MangaDex read chapter UUIDs and mark them read in Suwayomi")
    p.add_argument("--debug-read-sync", action="store_true", help="Verbose diagnostics for read sync: UUID lookup, title resolution, progress, and cross-source matches")
    p.add_argument("--read-chapters-dry-run", action="store_true", help="Simulate chapter read marking only")
    p.add_argument("--read-sync-delay", type=float, default=0.0, help="Seconds to wait after adding a manga before syncing read chapters (allow chapters to populate)")
    p.add_argument("--max-read-requests-per-minute", type=int, default=300, help="Throttle for chapter read mark requests")
    p.add_argument("--read-sync-number-fallback", action="store_true", help="When MangaDex UUIDs don't match, mark chapters by chapter number on any same-title source")
    p.add_argument("--cross-source-title-threshold", type=float, default=0.6, help="Similarity threshold (0..1) when matching titles across sources for number-based read sync (default 0.6)")
    p.add_argument("--cross-source-title-strict", action="store_true", help="Require normalized exact/containment match for cross-source title match (disables fuzzy-only matches)")
    p.add_argument("--suwayomi-manga-id", type=int, help="Force read-sync onto this Suwayomi internal manga id (bypass UUID/title lookup)")
    p.add_argument("--read-sync-only-if-ahead", action="store_true", help="Only apply read marks when MangaDex has progressed further than the target entry")
    p.add_argument("--read-sync-across-sources", action=argparse.BooleanOptionalAction, default=False, help="Also apply read marks to same-title entries under other sources (by chapter number). Use this flag to enable cross-source sync; add --no-read-sync-across-sources to force it off explicitly")
    p.add_argument("--list-categories", action="store_true", help="List Suwayomi categories (id + name) and exit")
    p.add_argument("--list-library-titles", action="store_true", help="List Suwayomi library entries with internal IDs and exit")
    p.add_argument("--filter-title", help="Optional substring filter for --list-library-titles (case-insensitive)")
    p.add_argument("--status-map-debug", action="store_true", help="Verbose output for status->category mapping decisions")
    p.add_argument("--assume-missing-status", help="If a manga has no MangaDex status, assume this status (e.g. reading)")
    p.add_argument("--print-status-summary", action="store_true", help="Print summary of fetched statuses and mapping coverage")
    p.add_argument("--debug-status", action="store_true", help="Print raw status dict sample after fetch")
    p.add_argument("--status-endpoint-raw", action="store_true", help="Dump full raw JSON from /manga/status (and per-manga fallback) for diagnostics")
    p.add_argument("--status-fallback-single", action="store_true", help="If bulk status returns empty, fetch each via /manga/{id}/status")
    p.add_argument("--status-fallback-throttle", type=float, default=0.3, help="Sleep seconds between single status fallback calls (default 0.3)")
    p.add_argument("--ignore-statuses", help="Comma-separated list of status values to ignore for category mapping (e.g. reading)")
    p.add_argument("--verify-id", action="append", dest="verify_ids", help="Repeatable. Verify this MangaDex UUID is in the final import set (after follows merge). Can be specified multiple times.")
    p.add_argument("--export-statuses", type=Path, help="Write the final fetched statuses mapping (after filters) to this JSON file")
    p.add_argument("--include-library-statuses", action="store_true", help="Include ALL manga that have a MangaDex library reading status (merge into processing set)")
    p.add_argument("--library-statuses-only", action="store_true", help="Process ONLY manga that have a MangaDex library reading status (ignore follows and file)")
    # Rehoming/migration options
    p.add_argument("--rehoming-enabled", action="store_true", help="Attempt to add an alternative source entry when MangaDex has no chapters")
    p.add_argument("--rehoming-sources", help="Comma-separated list of source name fragments in priority order (e.g. 'mangasee,comick')")
    p.add_argument("--rehoming-skip-if-chapters-ge", type=int, default=1, help="Skip rehoming if MangaDex already has at least this many chapters (default 1)")
    p.add_argument("--rehoming-remove-source", action="store_true",
                   help="After successful rehome, remove the original source entry from library")
    p.add_argument("--rehoming-remove-mangadex", dest="rehoming_remove_source", action="store_true",
                   help=argparse.SUPPRESS)  # backward-compat alias
    p.add_argument("--migrate-title-threshold", type=float, default=0.6, help="Similarity threshold (0..1) for matching titles when selecting migrate/rehoming candidates (default 0.6)")
    p.add_argument("--migrate-title-strict", action="store_true", help="Require normalized exact/containment title match when selecting candidates (disables fuzzy-only matches)")
    # Migrate existing library without MangaDex data
    p.add_argument("--migrate-library", action="store_true", help="Scan current Suwayomi library and add an alternative source for entries under a chapter threshold")
    p.add_argument("--migrate-threshold-chapters", type=int, default=1, help="Only migrate entries with fewer than this many chapters (default 1)")
    p.add_argument("--migrate-sources", help="Preferred alternative sources (comma-separated fragments). If omitted, uses --rehoming-sources")
    p.add_argument("--exclude-sources", default="comick,hitomi", help="Comma-separated source name fragments to always exclude (default: 'comick,hitomi')")
    p.add_argument("--migrate-remove", action=argparse.BooleanOptionalAction, default=False, help="Remove the original library entry after a successful migration (default: disabled; pass --migrate-remove to enable removal)")
    p.add_argument("--migrate-remove-if-duplicate", action="store_true", help="If the selected alternative already exists in the library and has >0 chapters, remove the original zero/low-chapter entry instead of adding a duplicate")
    p.add_argument("--debug-library", action="store_true", help="Verbose diagnostics for library and chapter listing endpoints during migration")
    p.add_argument("--request-timeout", type=float, default=12.0, help="Default HTTP request timeout in seconds (default 12)")
    p.add_argument("--migrate-timeout", type=float, default=20.0, help="Max seconds to spend trying sources for a single migration item (default 20)")
    p.add_argument("--migrate-max-sources-per-site", type=int, default=3, help="Limit attempts per site name (e.g. 'mangapark') to this many different source IDs (default 3)")
    p.add_argument("--migrate-try-second-page", action="store_true", help="Try page 2 if page 1 had no results (slower)")
    p.add_argument("--migrate-filter-title", help="Only process library entries whose title contains this substring (case-insensitive)")
    p.add_argument("--migrate-preferred-only", action="store_true", help="When set and --migrate-sources provided, restrict search to only those sources (by name fragments)")
    p.add_argument("--preferred-langs", help="Comma-separated language codes to prefer when counting chapters (e.g. 'en,en-us,id'). If set, candidates are scored by chapters in these languages")
    p.add_argument("--lang-fallback", action="store_true", help="If no chapters match preferred languages for a candidate, allow non-preferred counts as fallback")
    # Source preference (quality bias)
    p.add_argument("--prefer-sources", help="Comma-separated source name fragments to bias as higher-quality (e.g. 'asura,flame,genz,utoons')")
    p.add_argument("--prefer-boost", type=int, default=3, help="Add this many points to the candidate score when its source matches --prefer-sources (default 3)")
    p.add_argument("--migrate-keep-both", action="store_true", help="When using global best, also add the raw max-chapters candidate if different from the preferred boosted winner (helps keep quality + completeness)")
    p.add_argument("--keep-both-min-preferred", type=int, default=1, help="Minimum preferred-language chapters required on the second candidate to keep it as well (set 0 to allow non-preferred) (default 1)")
    p.add_argument("--migrate-include-categories", help="Comma-separated category IDs or names; only entries in at least one of these categories will be migrated")
    p.add_argument("--migrate-exclude-categories", help="Comma-separated category IDs or names; entries in any of these categories will be skipped")
    # Best source selection
    p.add_argument("--best-source", action="store_true", help="Evaluate a few candidate sources and pick the one with the most chapters (opt-in)")
    p.add_argument("--best-source-candidates", type=int, default=5, help="Max number of candidate manga entries to score per title when --best-source is enabled (default 5)")
    p.add_argument("--min-chapters-per-alt", type=int, default=0, help="Require chosen alternative to have at least this many chapters; if not, try next candidate/result (default 0)")
    p.add_argument("--best-source-canonical", action="store_true", help="Score by unique canonical chapter numbers (collapse 1.1/1.2 to 1)")
    p.add_argument("--best-source-global", action="store_true", help="When set, consider all preferred sources and pick the single best candidate overall instead of stopping at the first site that qualifies")
    # Custom lists support
    p.add_argument("--import-lists", action="store_true", help="Fetch MangaDex custom lists and map list names to categories")
    p.add_argument("--list-lists", action="store_true", help="List your MangaDex custom lists (id + name) and exit")
    p.add_argument("--lists-category-map", help="Comma list mapping ListName=categoryId (e.g. Dropped=7,On Hold=5,Plan to Read=8,Completed=9,Reading=4)")
    p.add_argument("--lists-ignore", help="Comma-separated list names to ignore when importing lists (e.g. Reading)")
    p.add_argument("--debug-lists", action="store_true", help="Verbose output for custom lists fetching and mapping decisions")
    # Reports
    p.add_argument("--missing-report", type=Path, help="Write a CSV of titles where read-chapter sync found missing chapters (title, md_id, markable, marked, missing)")
    p.add_argument("--no-add-library", action="store_true", help="Do not add missing titles to Suwayomi; only run reporting and (if enabled) cross-source read sync against existing library entries")

    # Prune-only mode (hard prune duplicates without searching)
    p.add_argument("--prune-zero-duplicates", action="store_true", help="Remove zero/low-chapter entries when another entry with the same title already exists with >= --prune-threshold-chapters chapters (no searching)")
    p.add_argument("--prune-threshold-chapters", type=int, default=1, help="Threshold for considering an entry 'kept'. Entries with chapters < this value are pruned if a matching-title entry has >= this value (default 1, i.e., keep entries with >=1 chapter)")
    p.add_argument("--prune-filter-title", help="Only consider titles containing this substring (case-insensitive) during prune")
    p.add_argument("--prune-nonpreferred-langs", action="store_true", help="Remove entries whose chapters don't match --preferred-langs when another same-title entry has chapters in the preferred language(s)")
    p.add_argument("--prune-lang-threshold", type=int, default=1, help="Minimum number of preferred-language chapters required to consider an entry a keeper (default 1)")
    p.add_argument("--prune-lang-fallback-keep-most", action="store_true", help="If no entries have preferred-language chapters in a title group, keep only the entry with the highest total chapter count and prune the rest")

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(message)s",
    )

    try:
        csv_col_map = parse_csv_column_map(getattr(args, 'csv_col_map', None))
    except ValueError as e:
        logger.error(f"CSV column map error: {e}")
        return 2

    csv_items: List[CsvItem] = []
    csv_total_rows = 0
    csv_status_map: Dict[str, str] = {}
    csv_progress_map: Dict[str, str] = {}
    csv_resolution_failures: List[Tuple[CsvItem, str]] = []
    csv_resolved_source: Dict[str, CsvItem] = {}
    csv_direct_items: List[CsvItem] = []
    if getattr(args, 'csv_files', None):
        for csv_path in args.csv_files:
            try:
                kind, parsed = load_csv_items(csv_path, args.csv_kind, csv_col_map)
            except FileNotFoundError as fnf:
                logger.error(f"CSV error: {fnf}")
                return 2
            except Exception as exc:
                logger.error(f"Failed to parse CSV '{csv_path}': {exc}")
                return 2
            csv_total_rows += len(parsed)
            for item in parsed:
                if not item.source or item.source == "unknown":
                    item.source = kind
            csv_items.extend(parsed)

    # Enable early debug traces as soon as possible
    try:
        global READ_SYNC_DEBUG
        READ_SYNC_DEBUG = bool(getattr(args, 'debug_read_sync', False))
    except Exception:
        READ_SYNC_DEBUG = False
    if READ_SYNC_DEBUG:
        try:
            logger.debug(f"[read-debug] start; base_url={args.base_url}file={str(args.input_file or '')}from_follows={bool(args.from_follows)}")
        except Exception:
            pass

    # Ensure session_token always defined to avoid UnboundLocalError when using --import-reading-status without --from-follows
    session_token: Optional[str] = None

    ids: List[str] = []
    if args.input_file:
        ids = read_any(args.input_file)
        if READ_SYNC_DEBUG:
            try:
                logger.debug(f"[read-debug] ids from file: {len(ids)}")
            except Exception:
                pass

    # --- MangaDex follows fetch ---
    follows_meta: List[Dict[str, Any]] = []
    if args.from_follows:
        md_user = args.md_username or os.environ.get("MANGADEX_USERNAME")
        md_pass = args.md_password or os.environ.get("MANGADEX_PASSWORD")
        if not md_user:
            logger.info("MangaDex username required for --from-follows (flag --md-username or env MANGADEX_USERNAME)")
            return 2
        if not md_pass:
            md_pass = getpass.getpass("MangaDex password: ")
        session_token, login_err = login_mangadex_verbose(
            username=md_user,
            password=md_pass,
            two_factor=args.md_2fa,
            client_id=args.md_client_id or os.environ.get("MANGADEX_CLIENT_ID"),
            client_secret=args.md_client_secret or os.environ.get("MANGADEX_CLIENT_SECRET"),
            debug=args.debug_login,
        )
        if not session_token:
            logger.error("Failed to authenticate with MangaDex." + (f" Reason: {login_err}" if login_err else ""))
            return 3
        follows_meta = fetch_all_follows_adv(
            session_token=session_token,
            debug=args.debug_follows,
            max_follows=args.max_follows,
        )
        if READ_SYNC_DEBUG:
            try:
                logger.debug(f"[read-debug] follows fetched: {len(follows_meta)} (max={args.max_follows})")
            except Exception:
                pass
        follow_ids = [m["id"] for m in follows_meta]
        # Merge with file IDs preserving order preference: file first, then new
        seen = set(ids)
        for fid in follow_ids:
            if fid not in seen:
                ids.append(fid)
                seen.add(fid)
        if args.follows_json:
            try:
                args.follows_json.write_text(json.dumps(follows_meta, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning(f"Warning: failed to write follows JSON: {e}")
    elif args.md_login_only:
        # Login to MangaDex to obtain a session token without merging follows
        md_user = args.md_username or os.environ.get("MANGADEX_USERNAME")
        md_pass = args.md_password or os.environ.get("MANGADEX_PASSWORD")
        if not md_user or not md_pass:
            logger.info("--md-login-only requires --md-username and --md-password (or env MANGADEX_USERNAME/MANGADEX_PASSWORD)")
            return 2
        session_token, login_err = login_mangadex_verbose(
            username=md_user,
            password=md_pass,
            two_factor=args.md_2fa,
            client_id=args.md_client_id or os.environ.get("MANGADEX_CLIENT_ID"),
            client_secret=args.md_client_secret or os.environ.get("MANGADEX_CLIENT_SECRET"),
            debug=args.debug_login,
        )
        if not session_token:
            logger.error("Failed to authenticate with MangaDex." + (f" Reason: {login_err}" if login_err else ""))
            return 3

    if csv_items:
        # Without --csv-via-mangadex, go direct to Suwayomi (no MangaDex API call)
        if not getattr(args, 'csv_via_mangadex', False):
            csv_direct_items.extend(csv_items)
        else:
            seen_ids: Set[str] = set(ids)
            threshold = max(0.0, min(1.0, float(getattr(args, 'csv_title_threshold', 0.6))))
            for item in csv_items:
                match = find_mangadex_match_for_item(item, threshold=threshold, strict_exact=bool(args.csv_title_strict))
                if match is None:
                    csv_resolution_failures.append((item, "no match above threshold"))
                    continue
                md_id, matched_title, score = match
                csv_resolved_source[md_id] = item
                if item.status:
                    csv_status_map[md_id] = item.status.lower()
                if args.csv_apply_read_progress and item.last_read_chapter:
                    csv_progress_map[md_id] = item.last_read_chapter
                if md_id not in seen_ids:
                    ids.append(md_id)
                    seen_ids.add(md_id)
                if READ_SYNC_DEBUG:
                    try:
                        logger.debug(f"[csv-debug] matched '{item.title}' -> {md_id} ({matched_title}) score={score:.2f}")
                    except Exception:
                        pass

    # Optionally merge or replace with all-statuses library set
    library_statuses_all: Dict[str, str] = {}
    if (args.include_library_statuses or args.library_statuses_only):
        # Ensure we have a session
        if not session_token:
            md_user = args.md_username or os.environ.get("MANGADEX_USERNAME")
            md_pass = args.md_password or os.environ.get("MANGADEX_PASSWORD")
            if md_user and md_pass:
                session_token, _ = login_mangadex_verbose(username=md_user, password=md_pass, two_factor=args.md_2fa)
            else:
                logger.info("--include-library-statuses/--library-statuses-only requires MangaDex credentials (use --md-username/--md-password)")
                return 2
        library_statuses_all = fetch_all_statuses(session_token) if session_token else {}
        lib_ids = list(library_statuses_all.keys())
        if args.library_statuses_only:
            ids = lib_ids
        else:
            seen = set(ids)
            for mid in lib_ids:
                if mid not in seen:
                    ids.append(mid)
                    seen.add(mid)

    if READ_SYNC_DEBUG:
        try:
            logger.debug(f"[read-debug] merged ids total: {len(ids)}")
        except Exception:
            pass
    # Determine if any operation has work to do
    _suwayomi_only_mode = (
        args.list_categories
        or args.migrate_library
        or getattr(args, 'prune_zero_duplicates', False)
        or getattr(args, 'prune_nonpreferred_langs', False)
        or getattr(args, 'list_library_titles', False)
    )
    if not ids and not csv_direct_items and not _suwayomi_only_mode:
        logger.info(
            "Nothing to import. Provide an input file, use --from-follows, or pass a "
            "Suwayomi-only operation flag such as --migrate-library or --list-library-titles."
        )
        return 1

    # Optional presence verification of specific IDs
    if args.verify_ids:
        logger.info("ID presence verification (after merge):")
        id_set = set(ids)
        for vid in args.verify_ids:
            if vid in id_set:
                logger.info(f"  {vid} : PRESENT")
            else:
                logger.info(f"  {vid} : MISSING (not in file nor follows)" )

    # --- Reading status + Lists mapping (optional) ---
    status_map: Dict[str, int] = {}
    if args.status_category_map:
        for part in args.status_category_map.split(','):
            part = part.strip()
            if not part:
                continue
            if '=' not in part:
                logger.warning(f"Warning: ignoring malformed status map entry '{part}'")
                continue
            k, v = part.split('=', 1)
            try:
                status_map[k.strip().lower()] = int(v)
            except ValueError:
                logger.warning(f"Warning: invalid category id in map entry '{part}'")
    csv_status_category_map: Dict[str, int] = {}
    if args.csv_status_to_category:
        for part in args.csv_status_to_category.split(','):
            part = part.strip()
            if not part:
                continue
            if '=' not in part:
                logger.warning(f"Warning: ignoring malformed csv-status entry '{part}'")
                continue
            k, v = part.split('=', 1)
            try:
                csv_status_category_map[k.strip().lower()] = int(v)
            except ValueError:
                logger.warning(f"Warning: invalid csv-status category id in entry '{part}'")
    if csv_status_category_map:
        status_map.update(csv_status_category_map)
    reading_statuses: Dict[str, str] = {}
    lists_membership: Dict[str, List[str]] = {}
    lists_category_map: Dict[str, int] = {}
    lists_ignore_set: set = set()
    status_fetch_note = ""
    if args.import_reading_status:
        # We can reuse session_token from follows, or login solely for status fetch.
        if not session_token:
            # Attempt standalone login if credentials provided and from-follows not used.
            md_user = args.md_username or os.environ.get("MANGADEX_USERNAME")
            md_pass = args.md_password or os.environ.get("MANGADEX_PASSWORD")
            if md_user and md_pass:
                session_token, login_err = login_mangadex_verbose(username=md_user, password=md_pass, two_factor=args.md_2fa)
                if not session_token:
                    logger.error("Failed MangaDex login for status fetch." + (f" Reason: {login_err}" if login_err else ""))
                    status_fetch_note = "login failed"
            else:
                logger.info("No session (need --from-follows or MangaDex credentials) to fetch statuses.")
                status_fetch_note = "no credentials"
        if session_token:
            # If raw dump requested, capture raw JSON pages by temporarily wrapping fetch_reading_statuses batching
            if args.status_endpoint_raw:
                logger.info(f"[status-raw] Fetching statuses for{len(ids)}ids")
            # Prefer using the pre-fetched all-statuses map when available
            if library_statuses_all:
                reading_statuses = {k: v for k, v in library_statuses_all.items() if k in set(ids)}
            else:
                reading_statuses = fetch_reading_statuses(session_token, ids)
            if not reading_statuses:
                status_fetch_note = "0 statuses fetched"
                if args.debug_status:
                    logger.debug("[debug-status] No statuses returned. If you just set one on MangaDex, wait a few seconds or toggle it again.")
                if args.status_endpoint_raw and ids:
                    # Try single-item fallback endpoint described in docs: GET /manga/{id}/status
                    test_id = ids[0]
                    try:
                        import requests as _rq
                        r2 = _rq.get(f"{MANGADEX_API}/manga/{test_id}/status", headers={"Authorization": f"Bearer {session_token}"}, timeout=15)
                        logger.info(f"[status-raw] Single /manga/{{id}}/status HTTP {r2.status_code}")
                        try:
                            logger.info(f"[status-raw] Body:{truncate_text(r2.text, 400)}")
                        except Exception:
                            pass
                    except Exception as se:
                        logger.error(f"[status-raw] Single status fetch error: {se}")
                # Automatic or explicit fallback to single fetch per id
                if args.status_fallback_single or (not reading_statuses and args.import_reading_status):
                    if args.debug_status:
                        logger.debug(f"[debug-status] Starting single-status fallback for {len(ids)} ids")
                    fetched_any = False
                    for mid in ids:
                        st = fetch_single_status(session_token, mid)
                        if st:
                            reading_statuses[mid] = st
                            fetched_any = True
                        time.sleep(max(0.0, args.status_fallback_throttle))
                    if args.debug_status:
                        logger.debug(f"[debug-status] Single-status fallback {'found some' if fetched_any else 'found none'}.")
                    if reading_statuses and status_fetch_note.startswith('0 statuses'):
                        status_fetch_note = f"{len(reading_statuses)} statuses fetched (fallback)"
            else:
                status_fetch_note = f"{len(reading_statuses)} statuses fetched"

            # If bulk returned some, still fill in any missing IDs when fallback is requested
            if args.status_fallback_single and ids:
                missing_ids = [mid for mid in ids if mid not in reading_statuses]
                if missing_ids:
                    if args.debug_status:
                        logger.debug(f"[debug-status] Fallback for missing {len(missing_ids)} ids after bulk")
                    filled = 0
                    for mid in missing_ids:
                        st = fetch_single_status(session_token, mid)
                        if st:
                            reading_statuses[mid] = st
                            filled += 1
                        time.sleep(max(0.0, args.status_fallback_throttle))
                    if args.debug_status:
                        logger.debug(f"[debug-status] Fallback filled {filled} additional statuses")
            if args.debug_status:
                sample_items = list(reading_statuses.items())[:10]
                logger.debug("[debug-status] Sample:")
                for k,v in sample_items:
                    logger.info(f"  {k}: {v}")
                if len(reading_statuses) > 10:
                    logger.info(f"  ... {len(reading_statuses)-10} more")
            if args.status_endpoint_raw and reading_statuses:
                # Dump full mapping (may be large) truncated
                try:
                    js_dump = json.dumps(reading_statuses)
                    logger.info(f"[status-raw] Full statuses JSON (truncated 800 chars): {js_dump[:800] + ('...' if len(js_dump) > 800 else '')}")
                except Exception as je:
                    logger.error(f"[status-raw] Could not dump statuses JSON: {je}")

            # Print raw summary before ignore if requested
            if args.print_status_summary and reading_statuses:
                raw_counts: Dict[str, int] = {}
                for s in reading_statuses.values():
                    raw_counts[s] = raw_counts.get(s, 0) + 1
                logger.info(f"Raw status summary: {', '.join(f'{k}={v}' for k,v in sorted(raw_counts.items()))}")

            # Filter out ignored statuses from mapping phase (still appear in raw summary before removal)
            if args.ignore_statuses:
                ignore_set = {s.strip().lower() for s in args.ignore_statuses.split(',') if s.strip()}
                if ignore_set:
                    removed = 0
                    for k in list(reading_statuses.keys()):
                        if reading_statuses[k] in ignore_set:
                            del reading_statuses[k]
                            removed += 1
                    if args.debug_status:
                        logger.debug(f"[debug-status] Removed {removed} entries due to ignore-statuses filter {sorted(ignore_set)}")

    if csv_status_map:
        for mid, st in csv_status_map.items():
            if st:
                reading_statuses[mid] = st.lower()

    # Optionally export the final statuses used for mapping (after ignore filters)
    if args.export_statuses:
        try:
            args.export_statuses.write_text(json.dumps(reading_statuses, indent=2), encoding="utf-8")
            logger.info(f"Wrote {len(reading_statuses)} statuses to {args.export_statuses}")
        except Exception as e:
            logger.warning(f"Warning: failed to write --export-statuses: {e}")

    # Parse lists mapping
    if args.lists_category_map:
        for part in args.lists_category_map.split(','):
            part = part.strip()
            if not part:
                continue
            if '=' not in part:
                logger.warning(f"Warning: ignoring malformed lists map entry '{part}'")
                continue
            k, v = part.split('=', 1)
            try:
                lists_category_map[k.strip()] = int(v)
            except ValueError:
                logger.warning(f"Warning: invalid category id in lists map entry '{part}'")
    if args.lists_ignore:
        lists_ignore_set = {s.strip() for s in args.lists_ignore.split(',') if s.strip()}

    # Fetch and list user lists if requested
    if (args.import_lists or args.list_lists) and not session_token:
        # Need a session; try logging in if not already
        md_user = args.md_username or os.environ.get("MANGADEX_USERNAME")
        md_pass = args.md_password or os.environ.get("MANGADEX_PASSWORD")
        if md_user and md_pass:
            session_token, login_err = login_mangadex_verbose(username=md_user, password=md_pass, two_factor=args.md_2fa)
        else:
            logger.info("Cannot fetch lists without MangaDex credentials/session.")
    if args.list_lists and session_token:
        lists = fetch_user_lists(session_token, debug=args.debug_lists)
        if not lists:
            logger.error("No lists found or fetch failed.")
        else:
            logger.info("MangaDex Lists:")
            for it in lists:
                logger.info(f"  {it['id']}: {it['name']}")
        return 0

    # Load list memberships for current ids if requested
    if args.import_lists and session_token:
        lists = fetch_user_lists(session_token, debug=args.debug_lists)
        name_by_id = {it['id']: it['name'] for it in lists}
        for lid, lname in name_by_id.items():
            ids_in = fetch_manga_ids_in_list(session_token, lid, debug=args.debug_lists)
            for mid in ids_in:
                if mid not in ids:
                    # include if not already
                    ids.append(mid)
                lists_membership.setdefault(mid, []).append(lname)

    if args.print_status_summary and args.import_reading_status:
        if reading_statuses:
            counts: Dict[str, int] = {}
            for s in reading_statuses.values():
                counts[s] = counts.get(s, 0) + 1
            mapped = sum(1 for s in reading_statuses.values() if s in status_map)
            coverage = (mapped / len(reading_statuses)) * 100 if reading_statuses else 0.0
            logger.info(f"Status summary: {', '.join(f'{k}={v}' for k,v in sorted(counts.items()))}")
            logger.info(f"Status mapping coverage: {mapped}/{len(reading_statuses)} ({coverage:.1f}%)")
        else:
            logger.info(f"Status summary: NONE ({status_fetch_note or 'no data'})")
        if args.assume_missing_status:
            logger.info(f"Assuming missing status = '{args.assume_missing_status.lower()}'")

    # --- Chapter read marker sync configuration ---
    chapter_sync_conf = {
        'enabled': args.import_read_chapters,
        'dry_run': args.read_chapters_dry_run,
        'delay': args.read_sync_delay,
        'rpm': args.max_read_requests_per_minute,
        'number_fallback': args.read_sync_number_fallback,
        'only_if_ahead': args.read_sync_only_if_ahead,
        'across_sources': args.read_sync_across_sources,
        'xsrc_title_threshold': float(args.cross_source_title_threshold),
        'xsrc_title_strict': bool(args.cross_source_title_strict),
    }
    # Publish chapter sync config globally for helpers
    try:
        global CHAPTER_SYNC_CONF
        CHAPTER_SYNC_CONF = dict(chapter_sync_conf)
    except Exception:
        pass
    # Global debug flag already set earlier for early traces
    if args.import_read_chapters and not session_token:
        logger.info("--import-read-chapters requires a MangaDex session (use --from-follows or --md-login-only). Disabling.")
        chapter_sync_conf['enabled'] = False

    client = SuwayomiClient(
        base_url=args.base_url,
        auth_mode=args.auth_mode,
        username=args.username,
        password=args.password,
        token=args.token,
        verify_tls=not args.insecure,
        request_timeout=args.request_timeout,
    )
    if READ_SYNC_DEBUG:
        try:
            logger.debug("[read-debug] client constructed")
        except Exception:
            pass

    # If a missing report is requested, ensure the file exists with header now (helps live tailing)
    pre_open_live_file: Optional[Path] = None
    if args.missing_report:
        try:
            outp = args.missing_report
            outp.parent.mkdir(parents=True, exist_ok=True)
            # Create file with header if empty/non-existent
            if not outp.exists() or outp.stat().st_size == 0:
                with outp.open('w', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow(["title", "md_id", "markable", "marked", "missing"])
            pre_open_live_file = outp
        except Exception:
            pre_open_live_file = None
    # Publish the report path globally for live appends in helpers
    try:
        global MISSING_REPORT_PATH
        MISSING_REPORT_PATH = pre_open_live_file
    except Exception:
        pass
    if READ_SYNC_DEBUG:
        try:
            logger.debug(f"[read-debug] missing_report path set: {bool(MISSING_REPORT_PATH)} -> {str(MISSING_REPORT_PATH) if MISSING_REPORT_PATH else ''}", flush=True)
        except Exception:
            pass
    # Unconditional progress marker to confirm flow
    if READ_SYNC_DEBUG:
        try:
            logger.debug("[read-debug] marker: after missing_report setup")
        except Exception:
            pass

    csv_existing_skips: List[Tuple[str, str]] = []
    csv_existing_internal: Dict[str, int] = {}
    if csv_resolved_source and getattr(args, 'csv_prefer_existing', False):
        normalized_existing: Set[str] = set(lookup.keys())
        existing_by_norm: Dict[str, int] = dict(lookup)
        if normalized_existing:
            filtered_ids: List[str] = []
            for md in ids:
                csv_item = csv_resolved_source.get(md)
                if not csv_item:
                    filtered_ids.append(md)
                    continue
                norms = set()
                primary = " ".join(_normalize_title_tokens(csv_item.title))
                if primary:
                    norms.add(primary)
                for syn in csv_item.synonyms:
                    norm_syn = " ".join(_normalize_title_tokens(syn))
                    if norm_syn:
                        norms.add(norm_syn)
                if any(norm in normalized_existing for norm in norms if norm):
                    csv_existing_skips.append((md, csv_item.title))
                    for norm in norms:
                        internal_id = existing_by_norm.get(norm)
                        if internal_id is not None:
                            csv_existing_internal[md] = internal_id
                            break
                    continue
                filtered_ids.append(md)
            if len(filtered_ids) != len(ids):
                ids = filtered_ids
                if READ_SYNC_DEBUG:
                    logger.debug(f"[csv-debug] prefer-existing skipped {len(csv_existing_skips)} items")
        # Trim CSV metadata to current ids and any entries kept for existing-library reconciliation
        active_md_ids = set(ids) | set(csv_existing_internal.keys())
        if csv_status_map:
            csv_status_map = {md: status for md, status in csv_status_map.items() if md in active_md_ids}
        if csv_progress_map:
            csv_progress_map = {md: hint for md, hint in csv_progress_map.items() if md in active_md_ids}
        csv_resolved_source = {md: item for md, item in csv_resolved_source.items() if md in active_md_ids}
        if csv_existing_internal:
            csv_existing_internal = {md: internal for md, internal in csv_existing_internal.items() if md in active_md_ids}

    if args.list_categories:
        try:
            cat_endpoints = [
                "/api/v1/category/list",  # common
                "/api/v1/category",       # alternative
                "/api/v1/categories",     # plural variant
            ]
            last_err: Optional[str] = None
            for ep in cat_endpoints:
                r = client.request("GET", ep)
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except Exception as je:
                        last_err = f"Invalid JSON from {ep}: {je}"
                        continue
                    # Some APIs wrap list inside a key
                    if isinstance(data, dict):
                        for k in ("data", "categories", "list"):
                            if k in data and isinstance(data[k], list):
                                data = data[k]
                                break
                    if not isinstance(data, list):
                        last_err = f"Unexpected format from {ep} (type {type(data)})"
                        continue
                    logger.info(f"Available Categories (from{ep}):")
                    for cat in data:
                        if not isinstance(cat, dict):
                            continue
                        cid = cat.get('id') or cat.get('categoryId')
                        name = cat.get('name') or cat.get('label') or ''
                        logger.info(f"  {cid}: {name}")
                    return 0
                else:
                    last_err = f"HTTP {r.status_code} {truncate_text(r.text,120)} at {ep}"
            logger.error(f"Failed to fetch categories. Tried endpoints: {', '.join(cat_endpoints)}")
            if last_err:
                logger.error(f"Last error:{last_err}")
            return 4
        except Exception as ce:
            logger.error(f"Error retrieving categories: {ce}")
            return 4

    # Hard prune mode: remove zero/low-chapter duplicates without searching
    if args.prune_zero_duplicates:
        from seiyomi.operations.prune import prune_zero_duplicates as _prune_zero_duplicates
        client_auth = SuwayomiClient(
            base_url=args.base_url,
            auth_mode=args.auth_mode,
            username=args.username,
            password=args.password,
            token=args.token,
            verify_tls=not args.insecure,
            request_timeout=args.request_timeout,
        )
        client_auth._auth()
        return _prune_zero_duplicates(client_auth, args)

    # List library entries (id, source, title) and exit
    if args.list_library_titles:
        try:
            srcs = client.get_sources()
            src_name_by_id = {}
            for s in srcs:
                try:
                    sid = s.get('id') or s.get('sourceId')
                    name = s.get('name') or s.get('sourceName') or s.get('lang') or ''
                    if sid is not None:
                        src_name_by_id[int(sid)] = str(name)
                except Exception:
                    pass
        except Exception:
            src_name_by_id = {}
        lib = client.get_library_graphql() or client.get_library() or []
        q = (args.filter_title or '').lower().strip()
        logger.info("Suwayomi library entries:")
        shown = 0
        for it in lib:
            try:
                mid, title, sid = _extract_entry_props(it)
                if title is None:
                    continue
                if q and q not in title.lower():
                    continue
                src_name = src_name_by_id.get(sid or -1, str(sid) if sid is not None else "?")
                logger.info(f"  id={mid}  source={src_name}  title={title}")
                shown += 1
            except Exception:
                continue
        logger.info(f"Total shown: {shown}")
        return 0

    # Prune non-preferred language entries when a preferred-language entry exists for the same title
    if args.prune_nonpreferred_langs:
        from seiyomi.operations.prune import prune_nonpreferred_langs as _prune_nonpreferred_langs
        client_auth = SuwayomiClient(
            base_url=args.base_url,
            auth_mode=args.auth_mode,
            username=args.username,
            password=args.password,
            token=args.token,
            verify_tls=not args.insecure,
            request_timeout=args.request_timeout,
        )
        client_auth._auth()
        return _prune_nonpreferred_langs(client_auth, args)

    # Standalone library migration flow (no MangaDex needed)
    if args.migrate_library:
        from seiyomi.operations.migrate import migrate_library as _migrate_library
        client_auth = SuwayomiClient(
            base_url=args.base_url,
            auth_mode=args.auth_mode,
            username=args.username,
            password=args.password,
            token=args.token,
            verify_tls=not args.insecure,
            request_timeout=args.request_timeout,
        )
        return _migrate_library(client_auth, args)

    # Continue with reporting/sync path (esp. when --no-add-library)
    if READ_SYNC_DEBUG:
        try:
            logger.debug("[read-debug] passed option gates (categories/prune/migrate checks)")
        except Exception:
            pass
    if READ_SYNC_DEBUG:
        try:
            logger.debug("[read-debug] entering report/sync phase")
        except Exception:
            pass
    sync_stats: List[Dict[str, Any]] = []
    added_entries: List[Tuple[str, int]] = []

    if READ_SYNC_DEBUG:
        try:
            logger.debug(f"[read-debug] about to branch on no_add_library={bool(args.no_add_library)}", flush=True)
        except Exception:
            pass
    if args.no_add_library:
        added, failed, failures = (0, 0, [])
        added_entries = []
        if READ_SYNC_DEBUG:
            try:
                logger.debug("[read-debug] --no-add-library path: will skip adds and proceed to reporting+sync")
            except Exception:
                pass
        if not args.no_progress:
            logger.info("Skipping add-to-library because --no-add-library is set; proceeding to reporting and read sync only.")
    else:
        added, failed, failures, added_entries = import_ids(
            client,
            ids,
            dry_run=args.dry_run,
            use_title_fallback=not args.no_title_fallback,
            show_progress=not args.no_progress,
            throttle=args.throttle,
            category_id=args.category_id,
            reading_statuses=reading_statuses,
            status_category_map=status_map,
            status_default_category=args.status_default_category,
            session_token=session_token if (args.from_follows or getattr(args, 'md_login_only', False)) else None,
            chapter_sync_conf=chapter_sync_conf,
            status_map_debug=args.status_map_debug,
            assume_missing_status=(args.assume_missing_status.lower() if args.assume_missing_status else None),
            lists_membership=lists_membership if args.import_lists else None,
            lists_category_map=lists_category_map if args.import_lists else None,
            lists_ignore_set=lists_ignore_set if args.import_lists else None,
            rehome_conf={
                'enabled': args.rehoming_enabled,
                'sources': [s.strip() for s in (args.rehoming_sources.split(',') if args.rehoming_sources else []) if s.strip()],
                'skip_if_ge': args.rehoming_skip_if_chapters_ge,
                'remove_md': getattr(args, 'rehoming_remove_source', False) or getattr(args, 'rehoming_remove_mangadex', False),
                'exclude_frags': [s.strip().lower() for s in (args.exclude_sources.split(',') if args.exclude_sources else []) if s.strip()],
                'best_source': bool(args.best_source),
                'best_candidates': int(args.best_source_candidates),
                'min_chapters_per_alt': int(args.min_chapters_per_alt),
                'canonical': bool(args.best_source_canonical),
                'title_threshold': float(args.migrate_title_threshold),
                'title_strict': bool(args.migrate_title_strict),
            } if args.rehoming_enabled else None,
        )

    direct_added: List[Tuple[CsvItem, int, str]] = []
    direct_existing: List[Tuple[CsvItem, int, str]] = []
    direct_failures: List[Tuple[CsvItem, str]] = []
    direct_progress_applied = 0
    direct_progress_skipped = 0
    if csv_direct_items:
        logger.info(f"CSV direct import mode: {len(csv_direct_items)} rows queued (via-mangadex={bool(getattr(args, 'csv_via_mangadex', False))}, MangaDex IDs={len(ids)}).")
        direct_added, direct_existing, direct_failures, direct_progress_applied, direct_progress_skipped = process_csv_direct_items(
            client=client,
            items=csv_direct_items,
            dry_run=bool(args.dry_run),
            prefer_existing=bool(getattr(args, 'csv_prefer_existing', False)),
            no_add_library=bool(args.no_add_library),
            status_category_map=status_map,
            status_default_category=args.status_default_category,
            status_map_debug=bool(args.status_map_debug),
            show_progress=not args.no_progress,
            apply_read_progress=bool(args.csv_apply_read_progress),
            chapter_sync_conf=chapter_sync_conf,
            title_threshold=max(0.0, min(1.0, float(getattr(args, 'csv_title_threshold', 0.6) or 0.0))),
            title_strict=bool(getattr(args, 'csv_title_strict', False)),
        )

    logger.error(f"Found {len(ids)} MangaDex IDs; Added: {added}, Failed: {failed}")
    if failures:
        logger.error("Failures:")
        for md, reason in failures[:50]:
            logger.info(f"  {md}: {reason}")
        if len(failures) > 50:
            logger.error(f"  ... and {len(failures) - 50} more")

    if direct_failures:
        for item, reason in direct_failures:
            csv_resolution_failures.append((item, reason))

    if csv_total_rows:
        matched = len(csv_resolved_source) + len(direct_added) + len(direct_existing)
        unmatched = max(0, csv_total_rows - matched)
        logger.info(f"CSV summary: rows={csv_total_rows}, matched={matched}, unmatched={unmatched}")
        if csv_existing_skips:
            logger.info(f"CSV entries already present in library (skipped add): {len(csv_existing_skips)}")
        if csv_resolution_failures:
            logger.error("CSV resolution failures:")
            for item, reason in csv_resolution_failures[:10]:
                logger.info(f"  {item.title}: {reason}")
            if len(csv_resolution_failures) > 10:
                logger.error(f"  ... and {len(csv_resolution_failures) - 10} more")
        if csv_direct_items:
            logger.error(f"CSV direct import: added={len(direct_added)}, existing={len(direct_existing)}, failed={len(direct_failures)}")

    csv_progress_applied = 0
    csv_progress_skipped = 0
    if csv_progress_map and args.csv_apply_read_progress:
        md_to_internal: Dict[str, int] = {}
        for md, internal in added_entries:
            if internal is None:
                continue
            md_to_internal[str(md)] = int(internal)
        for md, internal in csv_existing_internal.items():
            md_to_internal[str(md)] = int(internal)
        missing_progress_ids = [md for md in csv_progress_map.keys() if str(md) not in md_to_internal]
        library_norm_map: Dict[str, int] = {}
        if missing_progress_ids:
            try:
                library_entries = client.get_library_graphql() or client.get_library() or []
            except Exception as e:
                library_entries = []
                if READ_SYNC_DEBUG:
                    logger.error(f"[csv-progress] library fetch failed during progress mapping: {e}")
            for entry in library_entries:
                if not isinstance(entry, dict):
                    continue
                raw_id = entry.get('id') or entry.get('mangaId') or entry.get('manga_id')
                try:
                    internal_id = int(raw_id)
                except Exception:
                    continue
                titles: List[str] = []
                for key in ("title", "name"):
                    val = entry.get(key)
                    if isinstance(val, str) and val.strip():
                        titles.append(val)
                manga_info = entry.get('manga')
                if isinstance(manga_info, dict):
                    for key in ("title", "name"):
                        val = manga_info.get(key)
                        if isinstance(val, str) and val.strip():
                            titles.append(val)
                for title in titles:
                    norm = " ".join(_normalize_title_tokens(title))
                    if norm and norm not in library_norm_map:
                        library_norm_map[norm] = internal_id
            for md in missing_progress_ids:
                item = csv_resolved_source.get(md)
                if not item:
                    continue
                candidates = [item.title] + list(item.synonyms)
                for cand in candidates:
                    norm = " ".join(_normalize_title_tokens(cand))
                    internal_id = library_norm_map.get(norm) if norm else None
                    if internal_id is not None:
                        md_to_internal[str(md)] = internal_id
                        break
        rpm_limit = int(chapter_sync_conf.get('rpm', 300)) if chapter_sync_conf else 300
        dry_mark = bool(args.dry_run or (chapter_sync_conf and chapter_sync_conf.get('dry_run')))
        for md, hint in csv_progress_map.items():
            md_key = str(md)
            target = _parse_chapter_hint_to_float(hint)
            if target is None:
                csv_progress_skipped += 1
                continue
            internal_id = md_to_internal.get(md_key)
            if internal_id is None:
                csv_progress_skipped += 1
                if READ_SYNC_DEBUG:
                    logger.info(f"[csv-progress] missing internal id for {md_key}; skipping")
                continue
            if dry_mark:
                csv_progress_applied += 1
                if not args.no_progress:
                    logger.info(f"[csv-progress] (dry-run) would mark {md_key} up to chapter {hint}")
                continue
            try:
                _mark_entry_up_to_number(client, internal_id, target, rpm_limit, dry_run=False)
                csv_progress_applied += 1
                if not args.no_progress:
                    logger.info(f"[csv-progress] Marked {md_key} up to chapter {hint}")
            except Exception as exc:
                csv_progress_skipped += 1
                if READ_SYNC_DEBUG:
                    logger.error(f"[csv-progress] failed for {md_key}: {exc}")
    csv_progress_applied += direct_progress_applied
    csv_progress_skipped += direct_progress_skipped
    if args.csv_apply_read_progress and (csv_progress_applied or csv_progress_skipped):
        logger.info(f"CSV read progress applied={csv_progress_applied}, skipped={csv_progress_skipped}")

    if READ_SYNC_DEBUG:
        try:
            logger.debug(f"[read-debug] session_token present: {bool(session_token)}; starting reporting+sync if True", flush=True)
        except Exception:
            pass
    if session_token:
        md_source_id: Optional[int] = None
        try:
            srcs = client.get_sources()
            md_source_id = find_mangadex_source_id(srcs)
        except Exception:
            md_source_id = None
        if READ_SYNC_DEBUG:
            logger.debug(f"[read-debug] MangaDex source id: {md_source_id}")
        outp = args.missing_report if args.missing_report else None
        if outp:
            try:
                outp.parent.mkdir(parents=True, exist_ok=True)
                if not outp.exists() or outp.stat().st_size == 0:
                    with outp.open('w', newline='', encoding='utf-8') as f:
                        csv.writer(f).writerow(["title", "md_id", "markable", "marked", "missing"])
            except Exception:
                pass

        appended_count = 0
        written_ids: Set[str] = set()

        def _append_row(row: Dict[str, Any]) -> None:
            m = row.get('missing')
            is_missing = (isinstance(m, int) and m > 0) or (isinstance(m, str) and m.strip().lower() == 'unknown')
            if not is_missing:
                return
            mdv = str(row.get('md_id', '') or '')
            if mdv in written_ids:
                return
            written_ids.add(mdv)
            sync_stats.append(row)
            if outp:
                try:
                    with outp.open('a', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow([row.get('title', ''), row.get('md_id', ''), row.get('markable', ''), row.get('marked', ''), row.get('missing', '')])
                    nonlocal appended_count
                    appended_count += 1
                    if not args.no_progress:
                        logger.info(f"[report] appended {appended_count}: {row.get('md_id', '')} missing={row.get('missing', '')}")
                except Exception:
                    pass

        for md in ids:
            if not MD_ID_RE.match(md):
                continue
            try:
                if args.import_read_chapters and args.no_add_library and getattr(args, 'suwayomi_manga_id', None):
                    forced_id = int(args.suwayomi_manga_id)
                    if READ_SYNC_DEBUG:
                        logger.debug(f"[read-debug] Forcing read-sync onto Suwayomi manga id={forced_id} for MD {md}")
                    if chapter_sync_conf.get('delay', 0) and chapter_sync_conf.get('delay', 0) > 0:
                        time.sleep(float(chapter_sync_conf.get('delay', 0)))
                    sync_read_chapters_for_manga(
                        client,
                        session_token,
                        md,
                        forced_id,
                        dry_run=bool(chapter_sync_conf.get('dry_run')),
                        rpm=int(chapter_sync_conf.get('rpm', 300)),
                        show_progress=not args.no_progress,
                        prefix="[read-sync] ",
                    )
                elif args.import_read_chapters and args.no_add_library and md_source_id is not None:
                    try:
                        internal_id = search_by_mangadex_id(client, md_source_id, md)
                        if READ_SYNC_DEBUG:
                            logger.debug(f"[read-debug] UUID lookup for {md}: internal_id={internal_id}")
                        if internal_id:
                            if chapter_sync_conf.get('delay', 0) and chapter_sync_conf.get('delay', 0) > 0:
                                time.sleep(float(chapter_sync_conf.get('delay', 0)))
                            sync_read_chapters_for_manga(
                                client,
                                session_token,
                                md,
                                internal_id,
                                dry_run=bool(chapter_sync_conf.get('dry_run')),
                                rpm=int(chapter_sync_conf.get('rpm', 300)),
                                show_progress=not args.no_progress,
                                prefix="[read-sync] ",
                            )
                        else:
                            title = fetch_title_from_mangadex(md) or ""
                            if READ_SYNC_DEBUG:
                                logger.debug(f"[read-debug] Fallback by title for {md}: '{truncate_text(title, 120)}'")
                            if title:
                                lib = client.get_library_graphql() or client.get_library() or []
                                chosen_id: Optional[int] = None
                                for it in lib:
                                    mid2, t2, sid2 = _extract_entry_props(it)
                                    if sid2 is None or sid2 != md_source_id:
                                        continue
                                    if not t2:
                                        continue
                                    if _is_title_match(t2, title, threshold=0.6, strict_exact=False):
                                        chosen_id = mid2
                                        if READ_SYNC_DEBUG:
                                            logger.debug(f"[read-debug] Matched library MD entry by title: id={mid2} title='{truncate_text(t2, 80)}'")
                                        break
                                if chosen_id:
                                    if chapter_sync_conf.get('delay', 0) and chapter_sync_conf.get('delay', 0) > 0:
                                        time.sleep(float(chapter_sync_conf.get('delay', 0)))
                                    sync_read_chapters_for_manga(
                                        client,
                                        session_token,
                                        md,
                                        chosen_id,
                                        dry_run=bool(chapter_sync_conf.get('dry_run')),
                                        rpm=int(chapter_sync_conf.get('rpm', 300)),
                                        show_progress=not args.no_progress,
                                        prefix="[read-sync] ",
                                    )
                                else:
                                    if READ_SYNC_DEBUG:
                                        logger.debug(f"[read-debug] No MD-source library match by title for {md}; will rely on cross-source fallback if enabled.")
                    except Exception:
                        pass
                st = compute_md_missing_stats(client, session_token, md)
                if st:
                    _append_row(st)
                if chapter_sync_conf.get('enabled') and chapter_sync_conf.get('across_sources') and chapter_sync_conf.get('number_fallback'):
                    sync_cross_source_read_for_md(
                        client,
                        md,
                        session_token=session_token,
                        rpm=chapter_sync_conf.get('rpm', 300),
                        dry_run=bool(chapter_sync_conf.get('dry_run')),
                        only_if_ahead=bool(chapter_sync_conf.get('only_if_ahead')),
                        title_threshold=float(chapter_sync_conf.get('xsrc_title_threshold', 0.6)),
                        title_strict=bool(chapter_sync_conf.get('xsrc_title_strict', False)),
                    )
            except Exception as _e:
                if READ_SYNC_DEBUG:
                    try:
                        logger.debug(f"[read-debug] Exception during per-id processing for {md}: {_e}")
                    except Exception:
                        pass
                continue

    if args.missing_report:
        try:
            outp = args.missing_report
            try:
                outp.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            def _is_missing(row: Dict[str, Any]) -> bool:
                m = row.get('missing')
                if isinstance(m, int):
                    return m > 0
                if isinstance(m, str):
                    return m.strip().lower() == 'unknown'
                return False
            rows = [r for r in sync_stats if _is_missing(r)]
            with outp.open('w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["title", "md_id", "markable", "marked", "missing"])
                for row in rows:
                    w.writerow([row.get('title', ''), row.get('md_id', ''), row.get('markable', ''), row.get('marked', ''), row.get('missing', '')])
            logger.info(f"Missing-chapters report written to {outp} ({len(rows)} rows)")
        except Exception as e:
            logger.error(f"Failed to write --missing-report: {e}")

    return 0 if failed == 0 else 2

def _extract_int(v: Any) -> Optional[int]:
    try:
        if isinstance(v, bool) or v is None:
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip():
            return int(v.strip())
    except Exception:
        return None
    return None

def _extract_entry_props(it: Dict[str, Any]) -> Tuple[Optional[int], Optional[str], Optional[int]]:
    """Best-effort extract (internal_id, title, source_id) from a library entry with varied shapes."""
    mid: Optional[int] = None
    title: Optional[str] = None
    sid: Optional[int] = None
    # Direct fields
    mid = mid or _extract_int(it.get('id') or it.get('mangaId') or it.get('manga_id'))
    title = it.get('title') or it.get('name') or it.get('mangaTitle') or it.get('manga_title')
    sid = sid or _extract_int(it.get('sourceId') or it.get('source_id'))
    # Nested common containers
    m = it.get('manga') or {}
    if isinstance(m, dict):
        mid = mid or _extract_int(m.get('id'))
        title = title or m.get('title') or m.get('name')
        sid = sid or _extract_int(m.get('sourceId') or m.get('source_id'))
        src = m.get('source') or {}
        if isinstance(src, dict):
            sid = sid or _extract_int(src.get('id') or src.get('sourceId'))
    src2 = it.get('source') or {}
    if isinstance(src2, dict):
        sid = sid or _extract_int(src2.get('id') or src2.get('sourceId'))
    return mid, title, sid

if __name__ == "__main__":
    sys.exit(main())

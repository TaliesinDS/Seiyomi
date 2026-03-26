"""Seiyomi CLI — subcommand entry point (Phase 2).

Subcommands:
  seiyomi migrate                   Migrate library entries to better sources
  seiyomi import csv                Import CSV bookmarks (Comick, Manganato, …)
  seiyomi import follows            Import MangaDex follows
  seiyomi import ids                Import IDs from a file
  seiyomi prune duplicates          Remove zero-chapter duplicate entries
  seiyomi prune languages           Remove non-preferred-language entries
  seiyomi list categories           Show Suwayomi categories
  seiyomi list library              Show library contents
  seiyomi list sources              Show installed sources
  seiyomi sync reads                Sync read progress (MangaDex → Suwayomi)

Old flat-flag invocations (e.g. ``--migrate-library``) are translated by the
compat layer automatically — see ``seiyomi/compat.py``.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from seiyomi.compat import translate_old_args

logger = logging.getLogger("seiyomi")


# ── Shared argument groups ─────────────────────────────────────────────────

def _add_shared(p: argparse.ArgumentParser) -> None:
    """Add flags that apply to every subcommand."""
    p.add_argument("--base-url", default="http://127.0.0.1:4567",
                   help="Suwayomi server URL (default: http://127.0.0.1:4567)")
    p.add_argument("--auth", dest="auth_mode",
                   choices=["none", "basic", "bearer", "simple", "auto"],
                   default="auto", help="Auth mode (default: auto)")
    p.add_argument("--user", dest="username", default="",
                   help="Username for basic/simple auth")
    p.add_argument("--password", default="", help="Password for basic/simple auth")
    p.add_argument("--token", default="", help="Bearer token for token auth")
    p.add_argument("--dry-run", action="store_true",
                   help="Simulate without making changes")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Enable debug logging")
    p.add_argument("--no-progress", action="store_true",
                   help="Suppress per-item progress lines")


# ── Parser factory ─────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="seiyomi",
        description="Suwayomi library manager — import, migrate, and clean up.",
    )
    _add_shared(p)
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    # ── migrate ──
    mig = sub.add_parser("migrate", help="Migrate library entries to better sources")
    _add_shared(mig)
    mig.add_argument("--to", dest="migrate_sources", default="",
                     help="Preferred target sources (comma-separated name fragments)")
    mig.add_argument("--exclude", dest="exclude_sources", default="comick,hitomi",
                     help="Always-exclude source fragments (default: comick,hitomi)")
    mig.add_argument("--lang", dest="preferred_langs", default="en",
                     help="Preferred language codes, comma-separated (default: en)")
    mig.add_argument("--threshold", dest="migrate_threshold_chapters", type=int, default=1,
                     help="Only migrate entries with fewer chapters than this (default: 1)")
    mig.add_argument("--remove-old", dest="migrate_remove", action="store_true",
                     help="Remove original entry after successful migration")
    mig.add_argument("--candidates", dest="best_source_candidates", type=int, default=5,
                     help="Max candidates to score per title (default: 5)")
    mig.add_argument("--filter", dest="migrate_filter_title", default="",
                     help="Only process titles containing this substring")
    mig.add_argument("--timeout", dest="migrate_timeout", type=float, default=20.0,
                     help="Max seconds per title (default: 20)")

    # ── import ──
    imp = sub.add_parser("import", help="Import manga into Suwayomi")
    imp_sub = imp.add_subparsers(dest="import_command", metavar="TYPE")

    csv_p = imp_sub.add_parser("csv", help="Import from CSV export (Comick, Manganato, …)")
    _add_shared(csv_p)
    csv_p.add_argument("--file", dest="csv_files", action="append", type=Path,
                       required=True, help="CSV file path (repeatable)")
    csv_p.add_argument("--threshold", dest="csv_title_threshold", type=float, default=0.6,
                       help="Title match threshold 0..1 (default: 0.6)")
    csv_p.add_argument("--strict", dest="csv_title_strict", action="store_true",
                       help="Require near-exact title match")
    csv_p.add_argument("--status-map", dest="csv_status_to_category", default="",
                       help="Map status to category id: reading=5,completed=9")
    csv_p.add_argument("--apply-progress", dest="csv_apply_read_progress",
                       action="store_true", help="Sync last-read chapter hint after import")
    csv_p.add_argument("--prefer-existing", action="store_true",
                       help="Skip rows when title already exists in library")

    fol_p = imp_sub.add_parser("follows", help="Import MangaDex follows")
    _add_shared(fol_p)
    fol_p.add_argument("--md-user", dest="md_username", default="",
                       help="MangaDex username (or env MANGADEX_USERNAME)")
    fol_p.add_argument("--md-pass", dest="md_password", default="",
                       help="MangaDex password (or env MANGADEX_PASSWORD)")
    fol_p.add_argument("--import-status", dest="import_reading_status", action="store_true",
                       help="Map MangaDex reading statuses to categories")
    fol_p.add_argument("--import-read", dest="import_read_chapters", action="store_true",
                       help="Sync read progress from MangaDex")
    fol_p.add_argument("--status-map", dest="status_category_map", default="",
                       help="Map MangaDex statuses to category ids: reading=5,completed=9")

    ids_p = imp_sub.add_parser("ids", help="Import MangaDex IDs/URLs from a file")
    _add_shared(ids_p)
    ids_p.add_argument("file", type=Path, help="File containing MangaDex IDs or URLs")
    ids_p.add_argument("--import-read", dest="import_read_chapters", action="store_true",
                       help="Sync read progress from MangaDex")

    # ── prune ──
    prn = sub.add_parser("prune", help="Remove unwanted library entries")
    prn_sub = prn.add_subparsers(dest="prune_command", metavar="TYPE")

    dup_p = prn_sub.add_parser("duplicates",
                                help="Remove entries with 0 chapters when a better copy exists")
    _add_shared(dup_p)
    dup_p.add_argument("--threshold", dest="prune_threshold_chapters", type=int, default=0,
                       help="Prune entries with fewer chapters than this (default: 0)")
    dup_p.add_argument("--filter", dest="prune_filter_title", default="",
                       help="Only consider titles containing this substring")

    lang_p = prn_sub.add_parser("languages",
                                 help="Remove non-preferred-language entries")
    _add_shared(lang_p)
    lang_p.add_argument("--lang", dest="preferred_langs", default="en",
                        help="Keep entries in these languages (default: en)")
    lang_p.add_argument("--min-chapters", dest="prune_lang_threshold", type=int, default=1,
                        help="Min preferred-lang chapters to be a keeper (default: 1)")
    lang_p.add_argument("--filter", dest="prune_filter_title", default="")

    # ── list ──
    lst = sub.add_parser("list", help="List library / categories / sources")
    lst_sub = lst.add_subparsers(dest="list_command", metavar="TYPE")

    cat_p = lst_sub.add_parser("categories", help="Show Suwayomi categories")
    _add_shared(cat_p)

    lib_p = lst_sub.add_parser("library", help="Show library contents")
    _add_shared(lib_p)
    lib_p.add_argument("--filter", dest="filter_title", default="",
                       help="Show only titles containing this substring")

    src_p = lst_sub.add_parser("sources", help="Show installed sources")
    _add_shared(src_p)

    # ── sync ──
    sync_p = sub.add_parser("sync", help="Sync data between systems")
    sync_sub = sync_p.add_subparsers(dest="sync_command", metavar="TYPE")

    reads_p = sync_sub.add_parser("reads", help="Sync read progress (MangaDex → Suwayomi)")
    _add_shared(reads_p)
    reads_p.add_argument("--md-user", dest="md_username", default="")
    reads_p.add_argument("--md-pass", dest="md_password", default="")
    reads_p.add_argument("--only-if-ahead", dest="read_sync_only_if_ahead",
                         action="store_true")

    # ── gui ──
    sub.add_parser("gui", help="Launch the graphical interface")

    return p


# ── Client factory ─────────────────────────────────────────────────────────

def _make_client(args: argparse.Namespace):
    from seiyomi.clients.suwayomi import SuwayomiClient
    return SuwayomiClient(
        base_url=args.base_url,
        auth_mode=getattr(args, "auth_mode", "auto"),
        username=getattr(args, "username", "") or "",
        password=getattr(args, "password", "") or "",
        token=getattr(args, "token", "") or "",
    )


# ── Smart-default fill-ins (operations still use argparse namespace) ───────

def _fill(ns: argparse.Namespace, **defaults) -> None:
    """Set an attribute on ns only if it isn't already present."""
    for k, v in defaults.items():
        if not hasattr(ns, k):
            setattr(ns, k, v)


def _fill_migrate_defaults(args: argparse.Namespace) -> None:
    _fill(args,
          rehoming_sources="",
          migrate_remove_if_duplicate=False,
          debug_library=False,
          migrate_preferred_only=False,
          migrate_try_second_page=True,       # baked-in smart default
          migrate_include_categories="",
          migrate_exclude_categories="",
          migrate_max_sources_per_site=3,
          request_timeout=12.0,
          best_source=True,                   # baked-in smart default
          best_source_canonical=True,         # baked-in smart default
          best_source_global=False,
          min_chapters_per_alt=0,
          lang_fallback=False,
          prefer_sources="",
          prefer_boost=3,
          migrate_keep_both=False,
          keep_both_min_preferred=1,
          migrate_title_threshold=0.6,
          migrate_title_strict=False,
          )


def _fill_prune_defaults(args: argparse.Namespace) -> None:
    _fill(args,
          prune_filter_title="",
          prune_threshold_chapters=0,
          preferred_langs="en",
          prune_lang_threshold=1,
          prune_lang_fallback_keep_most=False,
          )


# ── Dispatch functions ─────────────────────────────────────────────────────

def _dispatch_migrate(args: argparse.Namespace) -> int:
    from seiyomi.operations.migrate import migrate_library
    _fill_migrate_defaults(args)
    return migrate_library(_make_client(args), args)


def _dispatch_prune_duplicates(args: argparse.Namespace) -> int:
    from seiyomi.operations.prune import prune_zero_duplicates
    _fill_prune_defaults(args)
    return prune_zero_duplicates(_make_client(args), args)


def _dispatch_prune_languages(args: argparse.Namespace) -> int:
    from seiyomi.operations.prune import prune_nonpreferred_langs
    _fill_prune_defaults(args)
    return prune_nonpreferred_langs(_make_client(args), args)


def _dispatch_list_categories(args: argparse.Namespace) -> int:
    client = _make_client(args)
    for cat in (client.list_categories() or []):
        print(f"{cat.get('id', '?')}: {cat.get('name', '?')}")
    return 0


def _dispatch_list_library(args: argparse.Namespace) -> int:
    client = _make_client(args)
    library = client.get_library_graphql() or client.get_library() or []
    flt = (getattr(args, "filter_title", "") or "").lower()
    for entry in library:
        title = str(entry.get("title") or entry.get("name") or "")
        mid = entry.get("id") or entry.get("mangaId") or ""
        if flt and flt not in title.lower():
            continue
        print(f"{mid}: {title}")
    return 0


def _dispatch_list_sources(args: argparse.Namespace) -> int:
    client = _make_client(args)
    for src in (client.get_sources() or []):
        print(f"{src.get('id', '?')}: {src.get('name', '?')}")
    return 0


def _dispatch_import_csv(args: argparse.Namespace) -> int:
    from seiyomi.importers.csv_import import load_csv_items, parse_csv_column_map, CSV_KIND_AUTO
    from seiyomi.operations.import_csv import process_csv_direct_items

    client = _make_client(args)
    items = []
    for csv_path in (args.csv_files or []):
        try:
            _kind, parsed = load_csv_items(csv_path, CSV_KIND_AUTO, {})
        except FileNotFoundError as e:
            logger.error("CSV error: %s", e)
            return 2
        except Exception as e:
            logger.error("Failed to parse CSV '%s': %s", csv_path, e)
            return 2
        items.extend(parsed)

    status_map: dict = {}
    for pair in (getattr(args, "csv_status_to_category", "") or "").split(","):
        if "=" in pair:
            k, _, v = pair.partition("=")
            try:
                status_map[k.strip().lower()] = int(v.strip())
            except ValueError:
                pass

    added, matched, failures, prog_applied, _skipped = process_csv_direct_items(
        client=client,
        items=items,
        dry_run=args.dry_run,
        prefer_existing=getattr(args, "prefer_existing", False),
        no_add_library=False,
        status_category_map=status_map,
        status_default_category=None,
        status_map_debug=args.verbose,
        show_progress=not args.no_progress,
        apply_read_progress=getattr(args, "csv_apply_read_progress", False),
        chapter_sync_conf=None,
        title_threshold=getattr(args, "csv_title_threshold", 0.6),
        title_strict=getattr(args, "csv_title_strict", False),
    )
    logger.info("CSV import complete: %d added, %d matched existing, %d failed",
                len(added), len(matched), len(failures))
    return 0 if not failures else 2


def _delegate_to_monolith(original_argv: List[str]) -> int:
    """Delegate a subcommand to the monolith for modes not yet fully extracted.

    The original pre-translation argv is used so the monolith's own argparse
    can handle its full flag set without us reverse-engineering every flag.
    """
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from import_mangadex_bookmarks_to_suwayomi_refactored import main as _m  # noqa: PLC0415
    return _m(original_argv)


# ── Entry point ────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])

    # Apply compat translation BEFORE parsing so old flat-flag invocations work.
    translated = translate_old_args(list(raw_argv))

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = _build_parser()

    if not translated:
        parser.print_help()
        return 1

    args, _unknown = parser.parse_known_args(translated)

    if getattr(args, "verbose", False):
        logging.getLogger().setLevel(logging.DEBUG)

    cmd = getattr(args, "command", None)

    if cmd == "migrate":
        return _dispatch_migrate(args)

    if cmd == "prune":
        prune_cmd = getattr(args, "prune_command", None)
        if prune_cmd == "duplicates":
            return _dispatch_prune_duplicates(args)
        if prune_cmd == "languages":
            return _dispatch_prune_languages(args)
        parser.parse_args(["prune", "--help"])
        return 1

    if cmd == "list":
        list_cmd = getattr(args, "list_command", None)
        if list_cmd == "categories":
            return _dispatch_list_categories(args)
        if list_cmd == "library":
            return _dispatch_list_library(args)
        if list_cmd == "sources":
            return _dispatch_list_sources(args)
        parser.parse_args(["list", "--help"])
        return 1

    if cmd == "import":
        import_cmd = getattr(args, "import_command", None)
        if import_cmd == "csv":
            return _dispatch_import_csv(args)
        # follows, ids — delegate to monolith (not yet fully extracted)
        return _delegate_to_monolith(raw_argv)

    if cmd == "sync":
        # delegate to monolith (not yet fully extracted)
        return _delegate_to_monolith(raw_argv)

    if cmd == "gui":
        from seiyomi.gui.app import launch
        launch()
        return 0

    # Unknown command — fall back to monolith (handles remaining old flags)
    return _delegate_to_monolith(raw_argv)


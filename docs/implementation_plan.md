# Seiyomi Implementation Plan

Derived from the [Full Application Review](full_app_review.md). Each step is self-contained, testable, and deployable — you should be able to ship after any completed step without breaking existing functionality.

Prerequisite reading: **§3** (architecture & MangaDex origin problem), **§8** (API reality check), **§19** (known bugs).

**Python version:** 3.10+ (required for `match`/`case` in Phase 1.6; use `if`/`elif` if 3.9 support is needed).
**CLI framework decision:** Use `argparse` throughout. It's already used, adds no dependency, and the subcommand structure in Phase 2 works fine with `argparse.add_subparsers()`. Consider `typer` as a future upgrade.

### Ground Rules for AI Agents

These rules apply to ALL phases. Read them before starting any step.

**Extraction discipline (Phases 1.1–1.4):**
- Move code EXACTLY as-is first. Do not refactor logic, simplify conditionals, rename internal variables, or "clean up" during extraction.
- The ONLY changes allowed during extraction are:
  - Function signature (replace 15 loose params with config dataclass)
  - Replace `args.X` references with `config.X`
  - Replace `print()` with `logger.info/debug/warning`
  - Replace global variable reads with config/parameter accesses
- Do NOT restructure control flow, eliminate nesting, combine branches, or "improve" algorithms.
- Refactoring of internal logic happens AFTER all modules are extracted, tests pass, and Phase 1.6 is complete.

**Dependency direction (all phases):**
- `seiyomi/operations/*` may import from `seiyomi/clients/*` and `seiyomi/matching/*`
- `seiyomi/clients/*` must NOT import from `seiyomi/operations/*`
- `seiyomi/gui/*` may import from anything in `seiyomi/` but must NOT contain business logic (see GUI rules below)
- Nothing may import from the monolith after Phase 1.6

**GUI rules (Phase 3):**
- GUI may call `SuwayomiClient` ONLY for **read-only data** (library listing, source listing, category listing, connection test)
- ALL mutations (migrate, import, prune, sync, add/remove from library) MUST go through CLI via `ProcessRunner`
- No business logic in GUI code — no title matching, no chapter marking, no migration decisions
- This prevents a parallel architecture from forming inside the GUI

---

## Phase 0 — Foundation (minimal user-visible changes)

The goal is to stop the bleeding, establish the package structure, and make the codebase safe to refactor. Steps 0.1–0.4 are invisible to the end user. Step 0.5 (MangaDex decoupling) changes the default CSV behavior — this is an intentional, documented breaking change.

### 0.1 Repository hygiene

**Do first — sets up the workspace for everything else.**

1. Create the package skeleton:
   ```
   seiyomi/
   ├── __init__.py          # version string only
   ├── __main__.py          # see below
   ├── clients/
   │   └── __init__.py
   ├── importers/
   │   └── __init__.py
   ├── operations/
   │   └── __init__.py
   ├── matching/
   │   └── __init__.py
   └── gui/
       └── __init__.py
   ```
   The `__main__.py` is a **temporary stub** that delegates to the monolith until Phase 1.6 replaces it:
   ```python
   # seiyomi/__main__.py — temporary, replaced in Phase 1.6
   import sys
   from pathlib import Path
   # Add repo root so monolith is importable
   sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
   from import_mangadex_bookmarks_to_suwayomi_refactored import main
   sys.exit(main())
   ```
2. Fix `requirements.txt`:
   - Add `requests>=2.28.0` (currently used but not declared)
   - Move `pyinstaller`, `markdown`, `tkhtmlview` to either `requirements-gui.txt` or mark as optional
3. Fix `requirements-dev.txt` — already good, no changes needed.
4. Move standalone scripts out of root:
   - `Convert .xlsx to .xml MAL.py` → `scripts/convert_xlsx_to_mal.py`
   - `Export libraries from MangaDex.py` → `scripts/export_mangadex.py`
   - `Mangaupdates MD List.py` → `scripts/mangaupdates_list.py`
   - Delete `get-pip.py` (shouldn't be in repo)
5. Add `.gitignore` entry for `get-pip.py` if not already there.
6. Delete or rename `import_mangadex_bookmarks_to_suwayomi.py` (the non-refactored original). It's 3,571 lines of abandoned code. If you want to keep it for reference, move to `archive/`.

**Acceptance:** `python -m seiyomi --help` prints the existing argparse help (delegated from monolith). `pytest` still passes. Root directory has fewer loose scripts.

### 0.2 Fix known bugs (§19)

**Each fix is a single commit with a matching test.**

| # | Bug | Fix | Test |
|---|-----|-----|------|
| 1 | Duplicate `return 0` in `get_manga_chapters_count()` | Delete the dead second `return 0` | Existing tests cover (no new test needed) |
| 2 | Duplicate `303` in `_auth()` status check | Change to `(200, 301, 302, 303)` | Unit test: mock auth returning 301 |
| 3 | `visit()` nested function redefined in loop | Extract outside loop (moot after §0.4 rewrites this) | Skip — will be deleted in 0.4 |
| 4 | Read-sync token lost with `--md-login-only` | Always pass `session_token` to `import_ids()` when available | Scenario test: `--md-login-only --import-read-chapters` with mocked endpoints |
| 5 | Preference filter no-op in rehome (`pass` → `continue`) | Replace `pass` with `continue` | Unit test: rehome with non-preferred source should skip |
| 6 | Missing report silently fails on Windows | Catch `PermissionError`, log warning, retry with temp file | Manual (OS-level file locking) |
| 7 | `_normalize_last_read()` rejects `"0"` | Treat `"0"` as valid (chapter 0) | Unit test parametrized |
| 8 | `--list-library-titles` blocked by MangaDex gate | Add `args.list_library_titles` to the exemption check at L2993 | CLI scenario test: `--list-library-titles` with no input file |

**Acceptance:** All 8 bugs have either a fix+test or are marked as deferred. `pytest` passes.

### 0.3 Replace `print()` with `logging`

This is mechanical but touches many lines. Do it in one focused commit.

1. At module top: `import logging; logger = logging.getLogger("seiyomi")`
2. Replace every `print(...)` with `logger.info(...)`, `logger.debug(...)`, or `logger.warning(...)`:
   - Progress messages (`[1/47] adding...`) → `logger.info`
   - Debug markers (`[read-debug]`, `[csv-debug]`) → `logger.debug`
   - Error messages → `logger.error` or `logger.warning`
3. In `main()`, configure the root logger:
   ```python
   logging.basicConfig(
       level=logging.DEBUG if args.verbose else logging.INFO,
       format="%(message)s",  # preserve current output format
   )
   ```
4. Collapse the 5 debug flags (`--debug-login`, `--debug-follows`, `--debug-status`, `--debug-lists`, `--debug-read-sync`) into a single `--verbose` / `-v` flag. Keep the old flags as hidden aliases that set `verbose=True` (backward compat).
5. Remove all `try: print(...) except Exception: pass` wrappers — `logging` handles encoding errors internally.

**Acceptance:** Same visible output for a normal run. `--verbose` shows debug lines. No raw `print()` calls remain in the main script.

### 0.4 Rewrite `SuwayomiClient` with correct API endpoints

**This is the highest-impact single change.** It fixes the silent chapter-marking bug, eliminates ~500 lines of dead fallback code, and makes the client testable.

1. Create `seiyomi/clients/suwayomi.py` with a new `SuwayomiClient` class.
2. Implement each method using the **authoritative endpoints from §8** (the full endpoint reference is in the review document's §8 "Authoritative REST API" tables).

   **Important context on the existing code:** In the monolith, `SuwayomiClient` (starts at class def around L913) contains library/chapter/source methods, but `mark_chapter_read()` is a **standalone function** (around L2192, not a class method) and category listing is done inline in `main()`. The new class consolidates all these into one place.

   New method signatures (these replace BOTH the existing class methods AND the standalone functions):

   | Method | Implementation |
   |--------|---------------|
   | `get_library()` | `GET /api/v1/category/0` → JSON array. Fallback: GQL `mangas(condition:{inLibrary:true}) { nodes { ... } }` |
   | `get_manga(id)` | `GET /api/v1/manga/{id}` |
   | `get_chapters(manga_id)` | `GET /api/v1/manga/{id}/chapters` |
   | `get_chapter_count(manga_id)` | GQL `manga(id:N) { chapters { totalCount } }` |
   | `mark_chapters_read(chapter_ids)` | `POST /api/v1/chapter/batch` with `{"chapterIds": ids, "change": {"isRead": true}}`. Fallback: GQL `updateChapters`. |
   | `mark_chapter_read(manga_id, chapter_index)` | `PATCH /api/v1/manga/{mid}/chapter/{index}` with **form-encoded** `read=true` |
   | `add_to_library(manga_id)` | `GET /api/v1/manga/{id}/library` |
   | `remove_from_library(manga_id)` | `DELETE /api/v1/manga/{id}/library` |
   | `list_categories()` | `GET /api/v1/category` |
   | `get_category_manga(category_id)` | `GET /api/v1/category/{id}` |
   | `add_to_category(manga_id, cat_id)` | `GET /api/v1/manga/{mid}/category/{cid}` |
   | `remove_from_category(manga_id, cat_id)` | `DELETE /api/v1/manga/{mid}/category/{cid}` |
   | `get_sources()` | `GET /api/v1/source/list` |
   | `search_source(source_id, term, page)` | `GET /api/v1/source/{id}/search?searchTerm=...&pageNum=...` |
   | `graphql(query, variables)` | `POST /api/graphql` with proper error handling |

3. **Each method gets exactly 1-2 endpoint calls.** No fallback chains. No guessing.
4. If a method needs both REST and GQL paths (e.g., `mark_chapters_read` for batch), implement the REST batch as primary and GQL as ONE explicit fallback.
5. Add a `server_version` property that calls `GET /api/v1/settings/about` once on first use and caches.
6. Write the `__init__` to accept `base_url`, `auth_mode`, `username`, `password` as explicit params (no globals).

7. **Migrate the monolith to use the new client.** This is the most labor-intensive part of 0.4:
   - Delete the old `SuwayomiClient` class from the monolith (L913–L1596).
   - Add `from seiyomi.clients.suwayomi import SuwayomiClient` at the top.
   - Update every call site. Key mappings:
     | Old call (in monolith) | New call |
     |---|---|
     | `client.get_library()` / `client.get_library_graphql()` | `client.get_library()` (single method, no separate GQL variant) |
     | `client.get_manga_chapters_count(mid)` | `client.get_chapter_count(mid)` |
     | `client.get_manga_chapters_entries(mid)` | `client.get_chapters(mid)` |
     | `client.get_manga_chapters_canonical_count(mid)` | Remove — compute from `client.get_chapters(mid)` + `canonical_key_from_chapter()` at the call site |
     | `client.get_manga_chapters_count_by_lang(mid, langs)` | Remove — compute from `client.get_chapters(mid)` + `_filter_items_by_lang()` at the call site |
     | `mark_chapter_read(client, chapter_id)` (standalone fn) | `client.mark_chapters_read([chapter_id])` |
     | `client.add_manga_to_category(mid, cid)` | `client.add_to_category(mid, cid)` |
     | `client.get_manga_details(mid)` | `client.get_manga(mid)` |
   - Search for `client.request(` — any direct calls to the old `request()` method need to use the new one or be replaced with a specific method.
   - Search for `mark_chapter_read(` (the standalone function) — replace all calls with `client.mark_chapters_read([id])`.
   - Run `pytest` after each batch of call-site updates to catch regressions early.

**Tests for 0.4:**
- Unit tests using `responses` mock for every method (happy path + error)
- Specific test: `mark_chapters_read([21, 22])` sends `POST /api/v1/chapter/batch` with correct JSON body
- Specific test: `mark_chapter_read(1, 5)` sends `PATCH /api/v1/manga/1/chapter/5` with form-encoded `read=true`
- Specific test: `get_library()` sends `GET /api/v1/category/0`, not `/api/v1/library`
- Specific test: `list_categories()` sends `GET /api/v1/category`, not `/api/v1/category/list`

**Acceptance:** Chapter marking works via REST. Zero 404s during normal operation. All fallback chain code deleted. Test suite covers every `SuwayomiClient` method.

### 0.5 Decouple MangaDex from non-MangaDex operations

**Fixes the architectural issue from §3. This is a deliberate breaking change:** CSV import switches from MangaDex-resolution-by-default to direct-Suwayomi-by-default. Document in release notes.

1. **Invert the gate.** Replace the "No MangaDex IDs" negative check (search for `"No MangaDex IDs to process"` to find it) with positive mode dispatch:
   ```python
   # Instead of: if not ids and not csv_direct_items and not ...:
   #                 print("No MangaDex IDs to process")
   # Do:
   mode = determine_mode(args)
   ```
   `determine_mode(args)` returns one of: `'import_follows'`, `'import_csv'`, `'import_ids'`, `'migrate'`, `'prune_dupes'`, `'prune_langs'`, `'list_categories'`, `'list_library'`.

   **Conflict resolution:** If multiple mode flags are set (e.g., `--from-csv` + `--migrate-library`), raise `SystemExit("Only one operation mode at a time. Got: --from-csv, --migrate-library")`. The current code allows some combinations but they're untested and fragile — making them explicit errors is safer.

   Each mode explicitly declares what it needs. New modes don't need to be added to an exemption list.

2. **Make CSV direct mode the default.** When `--from-csv` is used without `--csv-via-mangadex` (renamed from the double-negative `--csv-no-mangadex`), route items to `process_csv_direct_items()` directly. The MangaDex resolution path becomes opt-in via `--csv-via-mangadex`.

3. **Rename MangaDex-specific flags:**
   | Old name | New name | Why |
   |----------|----------|-----|
   | `--rehoming-remove-mangadex` | `--rehoming-remove-source` | Rehoming works for any source |
   | `--csv-no-mangadex` | Remove (invert default); add `--csv-via-mangadex` for the old default behavior | Double negative is confusing |

4. **Update program description:** `"Suwayomi library manager — import, migrate, clean up."` Keep the old name as the module filename until Phase 1 completes the package rename.

5. **Update GUI text** in `gui_launcher_tk.py`:
   - About: "Seiyomi — Suwayomi Library Manager"
   - CSV tab: remove "merge with MangaDex lookups" from description
   - Migrate tab: remove "from MangaDex to alternatives"
   - Rehoming: "Remove source entry after rehome" (not "Remove MangaDex entry")
   - Config directory: rename from `MangaDex_Suwayomi` to `Seiyomi` (with migration: check for old dir, copy config, log notice)

**Acceptance:** `seiyomi --from-csv comick.csv --base-url http://...` works without touching MangaDex. `seiyomi --list-library-titles --base-url ...` works without input file. `seiyomi --migrate-library --base-url ...` works without MangaDex extension. No mention of "MangaDex" in output unless the user is actually doing a MangaDex import.

### Phase 0 Gate — STOP here until ALL of these are true

- [ ] `python -m seiyomi --help` runs and prints help text
- [ ] `python -m seiyomi --list-categories --base-url http://127.0.0.1:4567` returns categories (tests SuwayomiClient rewrite)
- [ ] `python -m seiyomi --from-csv comick.csv --base-url ...` imports WITHOUT calling `api.mangadex.org` (tests MangaDex decoupling)
- [ ] `python -m seiyomi --list-library-titles --base-url ...` works without an input file (tests gate bug fix)
- [ ] No `print()` calls remain in the refactored script (all replaced with `logging`)
- [ ] `pytest` passes with no failures
- [ ] The original `import_mangadex_bookmarks_to_suwayomi.py` is deleted or archived

**Do NOT proceed to Phase 1 until all boxes are checked.** Phase 0 is the foundation — extracting modules from broken code just moves the bugs around.

---

## Phase 1 — Extract Modules (same features, new structure)

Everything here preserves the existing CLI flags. The monolith shrinks as code moves into the `seiyomi/` package. After each extraction, the monolith imports from the package.

### 1.1 Extract title matching → `seiyomi/matching/titles.py`

Move out of the monolith:
- `normalize_title()`, `tokenize()`, `title_similarity()`, `is_title_match()`, `jaccard_similarity()`
- `canonical_key_from_chapter()`, `is_canonical_chapter()`

**Boundary:** Pure functions, no I/O, no dependencies on other modules. Existing tests in `test_title_and_input_helpers.py` already cover these — update imports.

**Acceptance:** Existing title-matching tests pass against the extracted module. Monolith imports from `seiyomi.matching.titles`.

### 1.2 Extract CSV parsing → `seiyomi/importers/csv_import.py`

Move:
- `CsvItem` dataclass
- `detect_csv_kind()`, `parse_comick_csv()`, `parse_manganato_csv()`, `auto_parse_csv()`
- `_normalize_last_read()`
- Column mapping logic

**Boundary:** Takes a file path or file-like, returns `list[CsvItem]`. No API calls, no MangaDex.

**Tests:** Parametrized tests for each CSV format, column mapping overrides, edge cases (empty files, malformed rows, `"0"` as last_read).

### 1.3 Extract MangaDex client → `seiyomi/clients/mangadex.py`

Move:
- `login_mangadex()`, `login_mangadex_verbose()`
- `fetch_all_follows()`, `fetch_all_follows_adv()`
- `fetch_reading_statuses()`, `fetch_single_status()`, `fetch_all_statuses()`
- `fetch_mangadex_read_chapters()`
- `fetch_user_lists()`, `fetch_manga_ids_in_list()`
- `_search_mangadex_titles()`, `find_mangadex_match_for_item()`
- `fetch_title_from_mangadex()`
- `MANGADEX_API` constant, `MD_ID_RE`, `MD_URL_RE`

**Boundary:** Class `MangaDexClient` with `session_token` as state. All methods take explicit params, return typed results. No reference to Suwayomi.

**Tests:** Mock all HTTP calls via `responses`. Test login success/failure/2FA, follows pagination, status fetching, list membership.

### 1.4 Extract operations → `seiyomi/operations/`

**Do these as 6 separate commits, one per module.** Order matters — do `read_sync` first (it's used by both `import_follows` and `import_csv`), then the rest in any order.

To find each block of code: search for the function name in the monolith (NOT by line number — line numbers shift after earlier phases). The function names are stable.

#### 1.4a `read_sync.py` — extract first, used by others
- Find: `sync_read_chapters_for_manga()`, `_mark_entry_up_to_number()`, `_compute_entry_progress_by_number()`
- New signature: `sync_read_progress(suwayomi: SuwayomiClient, manga_id: int, md_chapters: dict, config: ReadSyncConfig) → ReadSyncResult`
- **Boundary constraint:** `read_sync.py` must depend ONLY on `SuwayomiClient`. It must NOT import or call `MangaDexClient`. MangaDex read data is passed in as plain `dict`/`list` arguments (the `md_chapters` param). This keeps read_sync reusable for any source, not just MangaDex.
- Test: mock `suwayomi.get_chapters()` and `suwayomi.mark_chapters_read()`, verify correct chapters get marked

#### 1.4b `migrate.py`
- Find: the `if args.migrate_library:` block in `main()` and all functions it calls
- New signature: `migrate_library(suwayomi: SuwayomiClient, config: MigrateConfig) → MigrationResult`
- Test: mock `suwayomi.get_library()`, `suwayomi.search_source()`, `suwayomi.add_to_library()`, verify source selection logic

#### 1.4c `prune.py`
- Find: the `if args.prune_zero_duplicates:` and `if args.prune_nonpreferred_langs:` blocks in `main()`
- New signatures: `prune_zero_duplicates(suwayomi, config) → PruneResult`, `prune_nonpreferred_langs(suwayomi, config) → PruneResult`
- Test: mock library with duplicates, verify correct entries selected for removal

#### 1.4d `rehome.py`
- Find: rehoming logic is interleaved inside `import_ids()` — search for `rehome` in that function
- New signature: `rehome_entry(suwayomi: SuwayomiClient, manga_id: int, config: RehomeConfig) → bool`
- Test: mock source search, verify best-source selection and old-entry removal

#### 1.4e `import_follows.py`
- Find: `import_ids()` function — this is the MangaDex follows import orchestrator
- New signature: `import_follows(suwayomi: SuwayomiClient, mangadex: MangaDexClient, ids: list[str], config: ImportConfig) → ImportResult`
- This module imports from `read_sync` and `rehome`
- Test: mock both clients, verify add-to-library + category assignment + read sync calls

#### 1.4f `import_csv.py` (the operation, not the parser from 1.2)
- Find: `process_csv_direct_items()` function
- New signature: `import_csv_entries(suwayomi: SuwayomiClient, items: list[CsvItem], config: CsvImportConfig) → ImportResult`
- Test: mock suwayomi client, verify title matching + library adds + optional read progress

**Rules for all operation modules:**
- Takes a `SuwayomiClient` (and optionally `MangaDexClient`) as explicit dependency
- Takes a `@dataclass` config object (not raw argparse namespace)
- Returns a result dataclass (counts, failures list, report data)
- Has no `import argparse`, no globals, no `print()` — use `logging.getLogger(__name__)`

### 1.5 Create config dataclasses → `seiyomi/config.py`

```python
@dataclass
class ConnectionConfig:
    base_url: str
    auth_mode: str = "none"  # "none", "basic", "digest"
    username: str = ""
    password: str = ""

@dataclass
class MigrateConfig:
    threshold_chapters: int = 1
    preferred_sources: list[str] = field(default_factory=list)
    exclude_sources: list[str] = field(default_factory=list)
    preferred_langs: list[str] = field(default_factory=lambda: ["en"])
    remove_original: bool = False
    similarity_threshold: float = 0.7
    best_source: bool = True
    canonical: bool = True
    max_candidates: int = 5
    timeout: int = 20
    dry_run: bool = False

@dataclass
class ReadSyncConfig:
    enabled: bool = False
    number_fallback: bool = True
    across_sources: bool = True
    only_if_ahead: bool = True
    delay: float = 1.0
    max_rpm: int = 30
    dry_run: bool = False

@dataclass  
class CsvImportConfig:
    title_threshold: float = 0.6
    strict_match: bool = False
    apply_read_progress: bool = False
    status_to_category: dict[str, int] = field(default_factory=dict)

@dataclass
class PruneConfig:
    mode: str = "duplicates"  # "duplicates" or "languages"
    threshold_chapters: int = 0
    preferred_langs: list[str] = field(default_factory=lambda: ["en"])
    dry_run: bool = False

@dataclass
class RehomeConfig:
    enabled: bool = False
    preferred_sources: list[str] = field(default_factory=list)
    skip_if_chapters_ge: int = 1
    remove_source_entry: bool = False
    dry_run: bool = False

@dataclass
class MangaDexImportConfig:
    from_follows: bool = False
    import_statuses: bool = False
    import_read_chapters: bool = False
    status_category_map: dict[str, int] = field(default_factory=dict)
    default_category: int | None = None
    ignore_statuses: list[str] = field(default_factory=list)
    dry_run: bool = False
```

Each config class should have a `@classmethod from_args(cls, args: argparse.Namespace) -> Self` that extracts the relevant fields from the argparse namespace. Keep this method on the dataclass, not in a separate module.

### 1.6 Reduce `main()` to dispatch

After extractions, `main()` becomes ~200 lines. Rewrite it in `seiyomi/cli.py` and update `seiyomi/__main__.py` to call it (replacing the temporary monolith stub from 0.1).

Use `if`/`elif` (not `match`/`case`) for Python 3.9 compatibility, or require 3.10+ and document it:

```python
# seiyomi/cli.py
import argparse, logging, sys
from seiyomi.config import ConnectionConfig, MigrateConfig, CsvImportConfig, ...
from seiyomi.clients.suwayomi import SuwayomiClient
from seiyomi.operations.migrate import migrate_library
from seiyomi.operations.prune import prune_zero_duplicates, prune_nonpreferred_langs
from seiyomi.operations.import_csv import import_csv_entries
from seiyomi.operations.import_follows import import_follows
from seiyomi.importers.csv_import import auto_parse_csv

def determine_mode(args) -> str:
    """Return exactly one mode string, or exit with error if ambiguous."""
    modes = []
    if args.migrate_library: modes.append("migrate")
    if args.csv_files: modes.append("import_csv")
    if args.from_follows: modes.append("import_follows")
    if getattr(args, 'prune_zero_duplicates', False): modes.append("prune_dupes")
    if getattr(args, 'prune_nonpreferred_langs', False): modes.append("prune_langs")
    if args.list_categories: modes.append("list_categories")
    if getattr(args, 'list_library_titles', False): modes.append("list_library")
    if args.input_file: modes.append("import_ids")
    if len(modes) > 1:
        sys.exit(f"Only one operation mode at a time. Got: {', '.join(modes)}")
    if len(modes) == 0:
        sys.exit("No operation specified. Use --help to see available modes.")
    return modes[0]

def main(argv=None) -> int:
    args = parse_args(argv)  # argparse setup, same flags as before
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    
    conn = ConnectionConfig.from_args(args)
    suwayomi = SuwayomiClient(conn.base_url, conn.auth_mode, conn.username, conn.password)
    
    mode = determine_mode(args)
    
    if mode == "migrate":
        config = MigrateConfig.from_args(args)
        result = migrate_library(suwayomi, config)
        # print summary from result
    elif mode == "import_csv":
        items = []
        for csv_path in args.csv_files:
            items.extend(auto_parse_csv(csv_path))
        config = CsvImportConfig.from_args(args)
        result = import_csv_entries(suwayomi, items, config)
    elif mode == "import_follows":
        from seiyomi.clients.mangadex import MangaDexClient
        md = MangaDexClient()
        md.login(args.md_username, args.md_password)
        config = MangaDexImportConfig.from_args(args)
        result = import_follows(suwayomi, md, config)
    elif mode == "list_categories":
        for cat in suwayomi.list_categories():
            print(f"{cat['id']}: {cat['name']}")
    # ... etc for remaining modes
    return 0
```

Then update `seiyomi/__main__.py`:
```python
from seiyomi.cli import main
import sys
sys.exit(main())
```

And delete the temporary stub from Phase 0.1.

**Acceptance for all of Phase 1:** `seiyomi/cli.py` contains `main()` at under 300 lines. All logic lives in `seiyomi/` submodules. The existing CLI flags all still work (test with: `python -m seiyomi --list-categories --base-url http://127.0.0.1:4567`). `pytest` covers every extracted module. The monolith file (`import_mangadex_bookmarks_to_suwayomi_refactored.py`) is either deleted or kept as a deprecated entrypoint that imports and calls `seiyomi.cli.main()`.

### Phase 1 Gate — STOP here until ALL of these are true

- [ ] `python -m seiyomi --list-categories --base-url http://127.0.0.1:4567` still works
- [ ] `python -m seiyomi --from-csv comick.csv --base-url ...` still works (no MangaDex)
- [ ] `python -m seiyomi --migrate-library --base-url ...` still works end-to-end
- [ ] No code remains in the monolith except CLI delegation, OR the monolith file is deleted
- [ ] Every module in `seiyomi/` has at least one test file
- [ ] `pytest` passes with no failures
- [ ] `seiyomi/operations/read_sync.py` does NOT import `MangaDexClient`

**Do NOT proceed to Phase 2 until all boxes are checked.** Phase 2 changes the user-facing interface — if Phase 1 is incomplete, you'll be building a new CLI on top of half-extracted code.

---

## Phase 2 — Subcommand CLI (new interface, backward-compatible)

### 2.1 Design the subcommand structure

```
seiyomi migrate              # Library migration between Suwayomi sources
seiyomi import follows       # MangaDex follows → Suwayomi
seiyomi import csv           # CSV bookmarks → Suwayomi (Comick, Manganato, etc.)
seiyomi import ids           # ID file → Suwayomi
seiyomi prune duplicates     # Remove zero-chapter duplicate entries
seiyomi prune languages      # Remove non-preferred language variants
seiyomi sync reads           # Sync read progress (MangaDex → Suwayomi)
seiyomi list categories      # Show Suwayomi categories
seiyomi list library         # Show library contents
seiyomi list sources         # Show installed sources (new!)
```

Shared parent flags:
```
--base-url URL       Suwayomi server URL (default: http://127.0.0.1:4567)
--auth MODE          Auth mode: none, basic, digest (default: none)
--user USER          Username for auth
--password PASSWORD   Password for auth
--dry-run            Simulate without making changes
-v, --verbose        Enable debug logging
```

> **Note:** Use `--password`, not `--pass`. `--pass` invites shell confusion and keyword collisions. Enforce this consistently everywhere — CLI, config, GUI labels.

### 2.2 Implement with `argparse` subparsers

One subparser per mode. Each subparser defines only the flags relevant to that mode. The `from_args()` classmethod on each config dataclass handles the mapping.

```python
# seiyomi/cli.py (Phase 2 version, replacing Phase 1 flat-flag parser)
p = argparse.ArgumentParser(prog="seiyomi", description="Suwayomi library manager")
# Shared flags on parent parser:
p.add_argument("--base-url", default="http://127.0.0.1:4567")
p.add_argument("--auth", choices=["none", "basic", "digest"], default="none")
p.add_argument("--user", default="")
p.add_argument("--password", default="")
p.add_argument("--dry-run", action="store_true")
p.add_argument("-v", "--verbose", action="store_true")

sub = p.add_subparsers(dest="command", required=True)

# Example: migrate subcommand
mig = sub.add_parser("migrate", help="Migrate titles between sources")
mig.add_argument("--from", dest="from_source", required=True, help="Source to migrate away from")
mig.add_argument("--to", dest="to_sources", required=True, help="Comma-separated target sources")
mig.add_argument("--lang", default="en", help="Preferred language (default: en)")
mig.add_argument("--remove-old", action="store_true", help="Remove original after successful migration")
mig.add_argument("--similarity", type=float, default=0.7)
mig.add_argument("--candidates", type=int, default=5)
# ... etc — only migrate-relevant flags
```

### 2.3 Bake in smart defaults per subcommand

The §7 analysis showed that most flags exist because the code doesn't have sensible defaults. Each subcommand hardcodes the right defaults:

| Subcommand | Defaults baked in |
|------------|-------------------|
| `seiyomi migrate` | `--best-source --canonical --try-second-page --similarity 0.7 --candidates 5 --timeout 20 --number-fallback --across-sources --only-if-ahead` |
| `seiyomi import csv` | `--direct` (no MangaDex resolution), `--threshold 0.6` |
| `seiyomi prune duplicates` | `--threshold 0` (any entry with 0 chapters) |
| `seiyomi sync reads` | `--number-fallback --only-if-ahead --across-sources` |

Users only override when they want non-default behavior.

### 2.4 Backward compatibility wrapper

Keep the old flat-flag interface working during transition. Create `seiyomi/compat.py`:

```python
def translate_old_args(argv: list[str]) -> list[str]:
    """Convert old flat-flag invocations to subcommand form.
    
    Only handles the most common patterns. Unmapped flags pass through unchanged
    (argparse will error on them, which is the desired behavior — it tells the user
    to update their command).
    """
    # Detection: old-style if no subcommand is the first non-flag arg
    if not argv or argv[0].startswith("--"):
        # Map mode flags to subcommands
        mode_map = {
            "--migrate-library": "migrate",
            "--prune-zero-duplicates": "prune duplicates",
            "--prune-nonpreferred-langs": "prune languages",
            "--list-categories": "list categories",
            "--list-library-titles": "list library",
            "--from-follows": "import follows",
        }
        for old_flag, subcommand in mode_map.items():
            if old_flag in argv:
                argv.remove(old_flag)
                return subcommand.split() + argv
        
        # CSV detection
        if "--from-csv" in argv:
            return ["import", "csv"] + argv
        
        # ID file (positional first arg in old interface)
        # Leave as-is — will need manual migration
    
    return argv
```

Wire it into `main()`: `argv = translate_old_args(argv or sys.argv[1:])`. Log a deprecation warning when translation triggers.

This is intentionally incomplete — it covers the ~80% case. Obscure flag combinations will error and tell the user to update. Don't try to be exhaustive: the compat layer is a bridge, not a permanent feature.

**Compat layer removal:** Delete `compat.py` when Phase 3 (GUI rebuild) is complete — the new GUI generates subcommand-style args directly. Do NOT extend the compat layer to support any new flags added in Phase 2+. If a flag isn't mapped, users update their command.

**Acceptance:** `seiyomi migrate --from bato.to --to "manga buddy" --lang en --remove-old --dry-run` executes a migration with zero MangaDex involvement. `seiyomi import follows --md-user X --md-pass Y` imports MangaDex follows. Old-style `seiyomi --migrate-library --base-url ...` still works via compat layer.

---

## Phase 3 — GUI Rebuild

### 3.1 Architecture

```
seiyomi/gui/
├── __init__.py
├── app.py              # SeiyomiApp(tk.Tk) — main window, navigation, connection bar
├── state.py            # AppState dataclass — replaces vals dict
├── runner.py           # ProcessRunner — launches CLI, captures stdout/stderr, streams to UI
├── widgets.py          # Reusable: LabeledEntry, LabeledDropdown, Tooltip, WarningBanner
└── views/
    ├── __init__.py
    ├── home.py          # HomeView — workflow cards (the landing screen from §7)
    ├── migrate.py       # MigrateWizard — 4-step wizard
    ├── import_md.py     # ImportMangaDexView — follows/status/lists
    ├── import_csv.py    # ImportCsvView — CSV import
    ├── cleanup.py       # CleanupView — prune duplicates + languages
    ├── advanced.py      # AdvancedView — full flag access (old interface)
    └── settings.py      # SettingsView — connection, auth, profiles
```

### 3.2 Key design decisions

1. **Each view is a class** with `build()`, `validate() → list[str]` (returns errors), and `get_args() → list[str]` methods.
2. **`ProcessRunner`** uses `subprocess.Popen` with `stdout=PIPE, stderr=STDOUT` and a background thread that reads lines and posts them to a tkinter Text widget via `widget.after()`. Provides `cancel()` via `process.terminate()`.
3. **Connection bar** at the bottom of every view — shows server status (green/red dot), tests connection on startup.
4. **`AppState`** is a `@dataclass` that serializes to JSON for profile save/load. Replace the 80+ `StringVar` dict.
5. **Wizard views** use a `WizardFrame` base class with Back/Next/Run buttons and step tracking.
6. **Data fetching for wizards.** The migrate wizard needs to query the library AT STEP 1 (to list sources and title counts BEFORE the user clicks Run). This means the GUI must import `SuwayomiClient` from `seiyomi.clients.suwayomi` directly — it cannot shell out to the CLI for this. Add a `seiyomi/gui/api.py` helper:
   ```python
   # seiyomi/gui/api.py
   from seiyomi.clients.suwayomi import SuwayomiClient
   from seiyomi.config import ConnectionConfig
   import threading
   
   def fetch_library_async(config: ConnectionConfig, callback):
       """Fetch library in background thread, call callback(result) on main thread."""
       def _worker():
           client = SuwayomiClient(config.base_url, config.auth_mode, config.username, config.password)
           library = client.get_library()
           # callback must be scheduled on tkinter main thread via widget.after()
           callback(library)
       threading.Thread(target=_worker, daemon=True).start()
   ```
   The `ProcessRunner` is still used for the actual operation execution (it runs the CLI command). `api.py` is only for pre-flight data fetching like source lists and library contents. See "GUI rules" in the Ground Rules section — `api.py` is read-only, all mutations go through CLI.

### 3.3 Implementation order

1. `app.py` + `state.py` + `runner.py` — the shell works, can launch commands
2. `home.py` — landing screen with cards
3. `settings.py` — connection config + profile management
4. `advanced.py` — port the existing full-flag interface (safety net)
5. `migrate.py` — the wizard from §7
6. `import_csv.py` — simple form
7. `import_md.py` — MangaDex import form
8. `cleanup.py` — prune form
9. Delete old `gui_launcher_tk.py`

### 3.4 Config directory migration

Old: `%APPDATA%/MangaDex_Suwayomi/`
New: `%APPDATA%/Seiyomi/`

On first launch, check for old directory. If found: copy profiles to new location, log a notice, leave old dir untouched (user can delete manually).

**Acceptance:** New GUI launches, connects to Suwayomi, runs a migration wizard end-to-end, shows live output, and can cancel a running operation. "Advanced" tab provides full flag access for power users.

---

## Phase 4 — Quality of Life

These are independent improvements that can be done in any order after Phase 1.

### 4.1 Centralized rate limiter

Replace all scattered `time.sleep()` and `--read-sync-delay` / `--max-read-requests-per-minute` with a token bucket:

```python
class RateLimiter:
    def __init__(self, rpm: int = 60):
        self.min_interval = 60.0 / rpm
        self.last_call = 0.0
    
    def wait(self):
        elapsed = time.monotonic() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.monotonic()
```

Inject into `SuwayomiClient` and `MangaDexClient`. One `--rpm` flag controls both.

### 4.2 Better title matching

Add `rapidfuzz` as optional dependency (falls back to current Jaccard if not installed):

```python
try:
    from rapidfuzz import fuzz
    def title_similarity(a, b):
        return fuzz.token_sort_ratio(a, b) / 100.0
except ImportError:
    # Keep current Jaccard implementation
    pass
```

### 4.3 Interactive mode

For ambiguous matches during migration or CSV import:

```
[migrate 12/47] "The Beginning After the End" — multiple matches:
  1. The Beginning After the End (Manga Buddy) — 180 chapters, 95% match
  2. The Beginning After The End (Weeb Central) — 175 chapters, 92% match
  3. Beginning After the End (Asura) — 160 chapters, 88% match
  Choose [1-3, s=skip, a=auto-pick best]: _
```

Add `--interactive` / `-i` flag. Default is auto-pick (current behavior).

### 4.4 Retry with backoff

```python
@retry(max_attempts=3, backoff_base=2.0, retryable=(ConnectionError, Timeout, HTTPError))
def _request(self, method, url, **kwargs):
    ...
```

Apply to both clients. Log retries at debug level.

### 4.5 Resumable operations

For long migrations (50+ titles), write a checkpoint file:

```json
{"mode": "migrate", "completed": ["manga_id_1", "manga_id_2"], "timestamp": "..."}
```

On restart with `--resume`, skip already-completed entries. Delete checkpoint on successful completion.

---

## Phase 5 — Testing Strategy

This is **not a sequential phase** — it describes the test architecture that should be built incrementally throughout Phases 0–4. Each step above specifies its own tests. This section is the reference for how tests are organized and what the final coverage looks like.

### Test pyramid

| Layer | Count (target) | What it covers |
|-------|-----------------|----------------|
| **Unit** | ~80 tests | Title matching, CSV parsing, config construction, chapter canonicalization, rate limiter |
| **Service contract** | ~40 tests | `SuwayomiClient` methods with `responses` mocks, `MangaDexClient` with mocks |
| **Operation** | ~30 tests | `migrate_library()`, `prune_zero_duplicates()`, `import_csv_entries()` with injected mock clients |
| **CLI scenario** | ~15 tests | `main()` invoked with argv, full end-to-end with all HTTP mocked |
| **Integration** | ~5 tests | Docker Suwayomi instance (CI only, optional) |

### Test execution

```bash
pytest                           # All unit + service + operation + CLI tests
pytest -m "not integration"      # Skip Docker tests (default)
pytest --cov=seiyomi             # With coverage
```

### Key test fixtures

The existing `tests/fixtures/` structure is good. Expand it:
```
tests/
├── conftest.py                  # Shared fixtures (mock clients, sample data)
├── fixtures/
│   ├── mangadex/
│   │   ├── sample_follows.json
│   │   ├── sample_statuses.json
│   │   └── sample_read_chapters.json
│   ├── suwayomi/
│   │   ├── sample_library.json
│   │   ├── sample_chapters.json      # NEW: chapter list with index + id mapping
│   │   ├── sample_categories.json    # NEW
│   │   └── sample_sources.json       # NEW
│   └── csv/
│       ├── comick_export.csv         # NEW: sample Comick CSV
│       └── manganato_export.csv      # NEW: sample Manganato CSV
├── test_matching.py                  # Title matching tests
├── test_csv_import.py                # CSV parsing tests
├── test_suwayomi_client.py           # SuwayomiClient tests (replace current)
├── test_mangadex_client.py           # MangaDexClient tests
├── test_migrate.py                   # Migration operation tests
├── test_prune.py                     # Prune operation tests
├── test_read_sync.py                 # Read sync tests
├── test_import_csv.py                # CSV import operation tests
├── test_import_follows.py            # MangaDex import operation tests
└── test_cli.py                       # Full CLI scenario tests
```

---

## Execution Order & Dependencies

```
Phase 0.1 (repo hygiene)
    │
    ├── 0.2 (bug fixes) ──────────────────────────────┐
    │                                                   │
    ├── 0.3 (logging) ─────────────────────────────────┤
    │                                                   │
    └── 0.4 (SuwayomiClient rewrite) ──────────────────┤
                                                        │
Phase 0.5 (MangaDex decoupling) ◄──────────────────────┘
    │
    ├── 1.1 (title matching) ──┐
    ├── 1.2 (CSV parsing) ─────┤
    ├── 1.3 (MangaDex client) ─┤── can be done in parallel
    └── 1.4 (operations) ◄─────┘
            │
            ├── 1.5 (config dataclasses)
            └── 1.6 (main() dispatch)
                    │
        ┌───────────┴───────────┐
        │                       │
    Phase 2 (CLI)          Phase 3 (GUI)  ── can be done in parallel
        │                       │
        └───────────┬───────────┘
                    │
              Phase 4 (QoL)  ── items are independent, any order
```

Steps 0.2, 0.3, and 0.4 can be done in parallel (they touch different parts of the code). Steps 1.1–1.3 can be done in parallel (they extract independent modules). Phase 2 and Phase 3 can be done in parallel (CLI doesn't depend on GUI or vice versa).

---

## What Gets Deleted

| What | Lines | When |
|------|-------|------|
| All REST fallback chains in `SuwayomiClient` | ~500 | Phase 0.4 |
| `get_library_graphql()` 17-query explorer | ~200 | Phase 0.4 |
| `get_manga_chapters_count()` 8-attempt chain | ~100 | Phase 0.4 |
| `mark_chapter_read()` 12-attempt chain | ~150 | Phase 0.4 |
| "No MangaDex IDs" gate + exemption list | ~15 | Phase 0.5 |
| `import_mangadex_bookmarks_to_suwayomi.py` (original) | 3,571 | Phase 0.1 |
| `get-pip.py` | ~1,800 | Phase 0.1 |
| `gui_launcher_tk.py` (old GUI) | 1,713 | Phase 3.3 (step 9) |
| Monolith main script (after extractions complete) | 4,426→0 | Phase 1.6 |
| Total deleted | **~12,000 lines** | |

## What Gets Created

| What | Est. lines | When |
|------|-----------|------|
| `seiyomi/clients/suwayomi.py` | ~300 | Phase 0.4 |
| `seiyomi/clients/mangadex.py` | ~250 | Phase 1.3 |
| `seiyomi/matching/titles.py` | ~100 | Phase 1.1 |
| `seiyomi/importers/csv_import.py` | ~150 | Phase 1.2 |
| `seiyomi/operations/*.py` (6 modules) | ~600 | Phase 1.4 |
| `seiyomi/config.py` | ~150 | Phase 1.5 |
| `seiyomi/cli.py` (subcommand CLI) | ~200 | Phase 2 |
| `seiyomi/gui/**` (rebuilt GUI) | ~800 | Phase 3 |
| Test files | ~1,000 | Throughout |
| Total new | **~3,550 lines** | |

**Net: ~12,000 lines deleted, ~3,550 created.** The application goes from ~10,000 lines of tangled monolith to ~3,500 lines of modular, tested code with the same feature set.

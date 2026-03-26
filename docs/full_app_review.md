# Seiyomi — Full Application Review

> Reviewed: 2026-03-26  
> Scope: architecture, code quality, GUI, testing, UX, security, and a concrete overhaul roadmap

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What the App Does Well](#2-what-the-app-does-well)
3. [Architecture & Structure](#3-architecture--structure)
4. [Code Quality Issues](#4-code-quality-issues)
5. [The CLI: Flag Explosion](#5-the-cli-flag-explosion)
6. [The GUI: gui_launcher_tk.py](#6-the-gui-gui_launcher_tkpy)
7. [**UX Deep-Dive: The Minesweeper Problem**](#7-ux-deep-dive-the-minesweeper-problem)
8. [**API Reality Check: Live Server Testing**](#8-api-reality-check-live-server-testing)
9. [SuwayomiClient](#9-suwayomiclient)
10. [MangaDex Integration](#10-mangadex-integration)
11. [Title Matching & Fuzzy Logic](#11-title-matching--fuzzy-logic)
12. [Chapter Sync & Read Progress](#12-chapter-sync--read-progress)
13. [CSV Import Pipeline](#13-csv-import-pipeline)
14. [Migration & Pruning](#14-migration--pruning)
15. [Error Handling & Logging](#15-error-handling--logging)
16. [Testing](#16-testing)
17. [Security & Safety](#17-security--safety)
18. [Dependencies & Packaging](#18-dependencies--packaging)
19. [Known Bugs & Correctness Issues](#19-known-bugs--correctness-issues)
20. [Overhaul Roadmap](#20-overhaul-roadmap)

---

## 1. Executive Summary

Seiyomi is a remarkably feature-rich tool that solves a real problem — managing a Suwayomi manga library across sources, syncing read progress, migrating when sites go down, and bulk-importing from MangaDex, Comick, and Manganato. The domain knowledge embedded in it (fractional chapter handling, multi-fork API compatibility, cross-source read sync) is genuinely impressive.

However, the codebase has grown organically into a state where adding features, fixing bugs, and onboarding is extremely difficult:

| Metric | Current State |
|---|---|
| Main script | **4,426 lines** in a single file |
| `main()` function | **~1,700 lines** |
| CLI arguments | **~70 flags** |
| GUI `main()` | **~1,243 lines** |
| Test coverage | **~3 test files** covering utilities only |
| Module count | **2** (one CLI, one GUI) |
| Logging | `print()` only, no structured logging |
| API endpoint attempts | **~70** across all fallback chains |
| API endpoints that work | **~15** (verified live + server source, §8) |

The "refactored" version (`_refactored.py`) is not a true refactor — it's the original with CSV features bolted on. The original `import_mangadex_bookmarks_to_suwayomi.py` (3,571 lines) still ships alongside it, creating confusion about which file is canonical.

**Bottom line:** The feature set is solid. The architecture needs to be rebuilt around it. And the GUI needs to stop asking users to understand the implementation — it should ask them what they want to accomplish.

---

## 2. What the App Does Well

Credit where it's due — these are genuine strengths:

- **Deep API compatibility (with caveats).** The client handles REST + GraphQL, multiple auth modes, and varied response shapes. The fallback chains are extensive but mostly unnecessary — live testing (§8) shows that ~85% of the attempted endpoints either don't exist or silently do nothing. The intent is admirable; the execution overshoots.
- **Canonical chapter logic.** The fractional chapter handling (`.1–.4` canonical, `.5` conditional, title-hint exclusion for extras/omakes) is well-thought-out and correctly implements manga-specific semantics.
- **Cross-source read sync.** Being able to sync MangaDex read progress to non-MangaDex entries by chapter number is genuinely useful and not offered by any other tool.
- **Non-destructive defaults.** Destructive operations require explicit opt-in. The GUI marks them in red. Dry-run is available everywhere.
- **Comprehensive dry-run.** Every mode supports dry-run, and the GUI auto-generates the exact CLI command being run — great for transparency.
- **Feature scope that outgrew its name.** What started as a MangaDex bookmark importer now handles source migration, library pruning, CSV import from multiple sites, and general Suwayomi library management. That's a lot of useful functionality in one tool — the problem is that the architecture never caught up with the scope (§3).
- **Tooltips throughout the GUI.** Nearly every control has a tooltip explaining what it does.

---

## 3. Architecture & Structure

### Current State (monolith)

```
import_mangadex_bookmarks_to_suwayomi_refactored.py  (4,426 lines — EVERYTHING)
├── CsvItem dataclass + CSV parsers
├── Title matching helpers
├── MangaDex API functions (login, follows, statuses, lists, chapter sync)
├── SuwayomiClient class (~650 lines)
├── import_ids() orchestrator
├── process_csv_direct_items() orchestrator
├── Migration logic
├── Prune logic
├── Cross-source sync logic
├── main() with argparse (~1,700 lines)
└── Dozens of private helper functions

gui_launcher_tk.py  (1,713 lines — entire GUI in one function)
├── _Tooltip class
├── CLI helpers
├── build_args() (arg dict → CLI list)
├── launch_command()
├── main() with all tabs, all controls, all event handlers
```

### The MangaDex Origin Problem

The app started as "import MangaDex bookmarks to Suwayomi" and grew into a general-purpose library manager. But the MangaDex origins are still the load-bearing walls of the architecture — even operations that have **nothing to do with MangaDex** are routed through MangaDex concepts, gated by MangaDex checks, or named after MangaDex.

#### Hard coupling: Code that won't work without MangaDex

| Operation mode | MangaDex entanglement |
|---|---|
| **CSV import (default)** | Every Comick/Manganato CSV row is sent to `find_mangadex_match_for_item()` → `_search_mangadex_titles()` which makes **live HTTP requests to `api.mangadex.org`**. The matched MangaDex UUID becomes the item's identity, and it's funneled through `import_ids()` which requires the MangaDex extension installed in Suwayomi. A Comick bookmark → MangaDex API lookup → MangaDex UUID → Suwayomi MangaDex source search. The `--csv-no-mangadex` flag exists to bypass this, but it's opt-in on CLI. |
| **`import_ids()` orchestrator** | Unconditionally calls `find_mangadex_source_id(sources)` and crashes with `SystemExit("Could not find MangaDex source...")` if no MangaDex extension exists. CSV items resolved via the default path are forced through this MangaDex-only pipeline. |
| **"No MangaDex IDs" gate** | At L2993, `main()` checks `if not ids and not csv_direct_items and not args.list_categories and not args.migrate_library and not args.prune_*:` and prints `"No MangaDex IDs to process"`. Every new non-MangaDex mode must be manually added to this growing exclusion list, or users get a misleading error. |
| **`--list-library-titles`** | This flag is **NOT** in the MangaDex gate exemption list — running it without an input file or follows hits the "No MangaDex IDs" error before reaching the list-library code. **This is a bug.** |

#### Naming and conceptual leakage

MangaDex terminology saturates non-MangaDex features:

| Where | Example |
|---|---|
| Filename | `import_mangadex_bookmarks_to_suwayomi_refactored.py` — invoked for migration, pruning, CSV import |
| Program description | `"Import MangaDex bookmarks / follows into Suwayomi library."` — shown for every `--help`, every mode |
| GUI config directory | `MangaDex_Suwayomi/` — stores ALL profiles, even Suwayomi-only migration configs |
| EXE name | `import_mangadex_bookmarks_to_suwayomi_refactored.exe` |
| `--rehoming-remove-mangadex` | Flag name hardcodes the assumption that the source being rehomed FROM is always MangaDex |
| Rehoming UI text | "When a MangaDex entry has no chapters" — rehoming works for any source |
| CSV tab description | "merge with MangaDex lookups" — on a Comick/Manganato import feature |
| CSV title threshold tooltip | "matching CSV titles to MangaDex" |
| Migrate tab description | "from MangaDex to alternatives" — migration works between any sources |
| About dialog | "A helper GUI to import from MangaDex..." |
| ~15 more tooltips | Reference "MangaDex" on fields that apply to any source |

#### The architecture this implies

The codebase has two mental models fighting each other:

```
                 What the code thinks it is:
                ┌─────────────────────────────┐
                │    MangaDex Import Tool      │
                │ (with some Suwayomi extras)  │
                └─────────────────────────────┘
                        │
         ┌──────────────┼──────────────┐
   MangaDex follows   CSV → MD UUID    Direct Suwayomi ops
   (core feature)     (bolt-on)        (escape hatches)

                 What it actually is:
                ┌─────────────────────────────┐
                │   Suwayomi Library Manager   │
                │ (with MangaDex as one input) │
                └─────────────────────────────┘
                        │
      ┌─────────┬───────┼───────┬──────────┐
   Import     Import   Migrate  Prune    List/
   from MD    from CSV  sources  dupes    query
   (one mode) (one mode)(independent)(independent)
```

The proposed `seiyomi/` package structure (below) already addresses this — MangaDex becomes `clients/mangadex.py` + `importers/mangadex.py`, and operations like migration, pruning, and CSV import have no dependency on it.

### Problems

1. **Everything in one file.** There's no module separation. The Suwayomi client, MangaDex client, title matching, CSV parsing, migration logic, read sync, and CLI parsing are all entangled in one file. This means:
   - You can't import `SuwayomiClient` without loading the entire 4,400-line module
   - A change to CSV parsing can accidentally break migration logic
   - IDE navigation/refactoring tools struggle with the file size
   - Code review is impractical

2. **`main()` is the application.** At ~1,700 lines, `main()` handles argument parsing, configuration assembly, mode dispatch, all orchestration logic, and inline progress reporting. It's untestable in its current form because there's no way to invoke a specific mode without parsing 70 CLI arguments.

3. **Two copies of the script.** Both `import_mangadex_bookmarks_to_suwayomi.py` (3,571 lines) and `import_mangadex_bookmarks_to_suwayomi_refactored.py` (4,426 lines) exist. The GUI points to the refactored one. The README examples reference the original. Users won't know which to run.

4. **GUI as shell launcher.** The GUI builds a CLI command string and shells out to PowerShell. It has no knowledge of the running process — it can't display progress, can't cancel, can't show errors inline. It's a fancy argument form generator.

5. **No configuration objects.** Settings flow as dozens of individual function parameters (some functions have 15+ arguments). There are no dataclass-based config objects — just raw dicts and argparse namespaces.

### Proposed Structure

```
seiyomi/
├── __init__.py
├── __main__.py              # Entry point: python -m seiyomi
├── cli.py                   # Argparse definitions, mode dispatch
├── config.py                # Dataclass-based configuration objects
├── clients/
│   ├── __init__.py
│   ├── suwayomi.py          # SuwayomiClient (HTTP + GraphQL)
│   └── mangadex.py          # MangaDex API client (login, follows, statuses)
├── importers/
│   ├── __init__.py
│   ├── mangadex.py          # MangaDex follows → Suwayomi import
│   ├── csv_import.py        # CSV parsing, format detection, CsvItem
│   └── id_file.py           # Text/JSON/CSV ID file reader
├── operations/
│   ├── __init__.py
│   ├── migrate.py           # Library migration logic
│   ├── prune.py             # Duplicate/language pruning
│   ├── read_sync.py         # Chapter read progress sync
│   └── rehome.py            # Source rehoming
├── matching/
│   ├── __init__.py
│   └── titles.py            # Normalization, Jaccard, token matching
├── reporting/
│   ├── __init__.py
│   └── missing_report.py    # Centralized CSV report writer
└── gui/
    ├── __init__.py
    ├── app.py               # Main window, tab container
    ├── tabs/                 # One module per tab
    │   ├── migrate.py
    │   ├── prune.py
    │   ├── mangadex.py
    │   ├── csv_import.py
    │   ├── database.py
    │   └── settings.py
    ├── widgets.py            # Reusable components (tooltip, labeled entry, etc.)
    └── runner.py             # Process launching, output capture
```

---

## 4. Code Quality Issues

### 4.1 Global Mutable State

```python
CHAPTER_SYNC_CONF: Dict[str, Any] = {}
READ_SYNC_DEBUG: bool = False
MISSING_REPORT_PATH: Optional[Path] = None
```

These globals are written in `main()` and read by functions deep in the call stack. This creates invisible coupling, makes testing require monkey-patching, and means function signatures lie about their inputs.

**Fix:** Pass configuration through explicit parameters or dataclass config objects.

### 4.2 God Functions

| Function | Lines | Responsibility |
|---|---|---|
| `main()` | ~1,700 | Everything |
| `import_ids()` | ~200 | MangaDex import + read sync + category mapping + rehoming |
| `process_csv_direct_items()` | ~250 | CSV import + library match + source search + category + progress |
| `get_library_graphql()` | ~200 | Tries 10+ GraphQL query shapes |
| `get_manga_chapters_count()` | ~100 | Tries 6 REST + 4 GraphQL endpoints |

Each of these should be decomposed into smaller, single-responsibility functions.

### 4.3 Copy-Paste Patterns

The missing-report CSV is written in at least 4 different places with slightly different field ordering. The "try multiple endpoints" pattern is repeated for chapters, library, marks, and removal without a shared helper. Language filtering logic appears in both migration and prune paths.

### 4.4 Magic Strings and Numbers

```python
for k in ('mangaList','mangaListData','manga_list','results','data','list','items','entries','mangas','manga'):
```

These field name lists appear in multiple places and aren't centralized. Endpoint paths are hardcoded strings repeated across methods.

### 4.5 Deeply Nested Conditionals

The migration and prune sections in `main()` have 6-8 levels of nesting. Example pattern:

```python
for entry in library:
    if condition:
        for source in sources:
            if condition:
                try:
                    items = search(...)
                    for cand in items:
                        if condition:
                            if score > threshold:
                                if prefer:
                                    ...
```

This makes the logic nearly impossible to follow or modify safely.

---

## 5. The CLI: Flag Explosion

The CLI has ~70 flags. This is the root cause of the GUI being a mess — it mirrors a CLI that was never designed for human use. The flags have grown organically with each feature, and many are interdependent in undocumented ways.

### Problems

1. **Flags that only work together.** `--read-sync-number-fallback` and `--read-sync-across-sources` require `--import-read-chapters` which requires `--from-follows` or `--md-login-only`. These dependencies aren't enforced or documented in the argparse setup.

2. **Flags that conflict.** `--migrate-library` vs `--prune-zero-duplicates` vs `--prune-nonpreferred-langs` vs the default import mode — these are mutually exclusive modes but aren't defined as such in argparse.

3. **Flags with misleading defaults.** `--migrate-threshold-chapters` defaults to 0, meaning migration triggers for *any* entry with 0 chapters. A first-time user running `--migrate-library` without understanding this will migrate their entire library.

4. **Too many flags for the same concern.** Read sync alone has 8 flags: `--import-read-chapters`, `--read-chapters-dry-run`, `--read-sync-delay`, `--max-read-requests-per-minute`, `--read-sync-number-fallback`, `--read-sync-across-sources`, `--read-sync-only-if-ahead`, `--debug-read-sync`.

### What to Do Instead

Replace the flat flag namespace with **subcommands** (like `git`):

```
seiyomi import follows      # MangaDex follows import
seiyomi import csv           # CSV import
seiyomi import ids           # ID file import
seiyomi migrate              # Library migration
seiyomi prune duplicates     # Prune zero-chapter duplicates
seiyomi prune languages      # Prune non-preferred languages
seiyomi sync reads           # Read progress sync
seiyomi list categories      # List categories
seiyomi list library         # List library titles
```

Each subcommand gets only the flags relevant to it. Shared options (connection, auth, dry-run) go on the parent parser. This eliminates conflicting flags, makes `--help` useful per-mode, and maps cleanly to GUI tabs.

---

## 6. The GUI: gui_launcher_tk.py

### What Works
- Tabs are logically organized
- Tooltips are comprehensive
- Command preview is a good idea for transparency
- Destructive action warnings are thoughtful
- Preset system is useful for common workflows
- Dark mode toggle and config persistence

### What Doesn't Work

1. **1,243-line `main()` function.** The entire GUI — all widgets, all layouts, all event handlers, all popups — is in a single function. Local variables like `vals` (a dict with 80+ tkinter StringVar/BooleanVar entries) are the only state mechanism.

2. **No separation of concerns.** Widget creation, layout, validation, arg building, and process management are interleaved. You can't change the Migrate tab layout without reading through hundreds of unrelated lines.

3. **Fire-and-forget process launching.** `subprocess.Popen()` is called but the handle isn't stored. There's no way to:
   - See output in the GUI
   - Cancel a running operation
   - Know when it finished
   - Show errors inline

4. **Windows-only.** `os.startfile()`, `CREATE_NO_WINDOW`, `CREATE_NEW_CONSOLE`, PowerShell-specific quoting — no cross-platform support. Not necessarily wrong for a personal tool, but limits distribution.

5. **No validation.** The GUI will happily generate a command with missing required fields (empty base URL, no auth when needed). Validation only happens when the CLI script runs and fails.

6. **`build_args()` re-parses all GUI state.** Instead of having each tab produce its own arguments, a single 200-line function checks every `vals` key. Adding a new option requires changes in 3 places: the widget, `vals`, and `build_args()`.

### Recommended Approach

If staying with tkinter (reasonable for a local tool):
- One class per tab, each responsible for its own widgets, layout, and arg generation
- A shared `AppState` dataclass instead of a `vals` dict
- Process runner that captures stdout/stderr and displays in an output panel
- Move `build_args()` logic into each tab/subcommand
- Add basic validation (highlight missing required fields, disable Run button)

A larger overhaul could consider:
- **textual** for a TUI (terminal UI) — cross-platform, looks good, no tkinter grief
- **DearPyGui** or **CustomTkinter** for a more modern look
- Keeping the GUI thin and investing in making the CLI genuinely pleasant to use (with subcommands, interactive prompts, and good defaults)

---

## 7. UX Deep-Dive: The Minesweeper Problem

This is the core usability issue. The GUI mirrors the CLI's 70-flag internal structure rather than the tasks a user actually wants to do. The result is that performing a simple, common operation — "bato.to shut down, move my manga to another source without losing read progress" — requires understanding and correctly configuring ~20 scattered checkboxes and fields across multiple tabs.

### What a User Has to Do Today (bato.to migration example)

To migrate away from a dead source and keep read progress, a user currently needs to:

1. **Suwayomi Database tab:** Set base URL, auth mode, credentials
2. **Migrate tab:** Enable "Migrate library" ✓, set threshold to "1", manually type source names into "Preferred sources", set "Exclude sources", enable "Best source" ✓, enable "Canonical" ✓, set "Best-source candidates" to "5", set "Min chapters per alt", set "Preferred languages" to "en,en-us", consider "Preferred only" vs not, decide on "Keep both", decide on "Remove original" (red, scary), set "Similarity threshold", decide "Strict" or not, set "Timeout", set "Max sources per site", consider "Try second page"
3. **Migrate tab → Rehoming section (buried below):** Maybe enable "Enable rehoming" ✓, set rehoming sources, set skip threshold, decide on "Remove MangaDex entry" 
4. **MangaDex Import tab → Chapter Read Sync section:** Enable "Import read chapters" ✓, enable "Number fallback" ✓, enable "Across sources" ✓, enable "Only if ahead" ✓, set delay, set requests/min — but wait, this requires MangaDex login too, so also fill in MD Username, MD Password...
5. **Settings tab:** Maybe enable "Debug output" to see what's happening

That's **~25 decisions** spread across **3 tabs** with no guidance about which combination is correct. Many options interact in non-obvious ways (e.g., "Only if ahead" does nothing without "Across sources"; "Number fallback" does nothing without "Import read chapters"). A wrong combination silently does nothing instead of warning the user.

### What This *Should* Look Like

Instead of exposing every internal flag, the GUI should present **task-oriented workflows**:

#### Home Screen: "What do you want to do?"

```
┌─────────────────────────────────────────────────────────┐
│  Seiyomi — Suwayomi Library Manager                     │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 🔄  Migrate a Dead Source                       │    │
│  │     Move titles from a source that shut down    │    │
│  │     to the best available alternative.          │    │
│  │     Preserves read progress.                    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 📥  Import from MangaDex                        │    │
│  │     Bring your MangaDex follows, statuses,      │    │
│  │     and read progress into Suwayomi.            │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 📋  Import from CSV                             │    │
│  │     Import bookmarks from Comick, Manganato,    │    │
│  │     or other sites via CSV export.              │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 🧹  Clean Up Library                            │    │
│  │     Remove duplicates, dead entries, or         │    │
│  │     non-preferred language variants.            │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ ⚙️  Advanced / Custom Command                   │    │
│  │     Full access to all CLI flags for            │    │
│  │     power users.                                │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  [Connection: http://127.0.0.1:4567 ✓]    [Settings]   │
└─────────────────────────────────────────────────────────┘
```

#### Example: "Migrate a Dead Source" wizard

When a user clicks "Migrate a Dead Source", they get a focused, step-by-step flow:

```
Step 1 of 4: Which source is gone?
┌───────────────────────────────────────────────────┐
│ Source to migrate FROM:  [bato.to          ▼]     │
│                                                   │
│ (Auto-detected from your library: bato.to has     │
│  47 titles. 31 have 0 chapters loaded.)           │
│                                                   │
│               [Next →]                            │
└───────────────────────────────────────────────────┘

Step 2 of 4: Where should titles move?
┌───────────────────────────────────────────────────┐
│ Search these sources for replacements:            │
│                                                   │
│ ☑ Manga Buddy     ☑ Weeb Central                 │
│ ☑ MangaPark       ☑ Asura Scans                  │
│ ☑ Flame Comics    ☐ MangaDex                     │
│                                                   │
│ Language: [English ▼]                             │
│                                                   │
│ ☑ Remove old entry after successful migration     │
│                                                   │
│        [← Back]              [Next →]             │
└───────────────────────────────────────────────────┘

Step 3 of 4: Read progress
┌───────────────────────────────────────────────────┐
│ ☑ Preserve read progress                          │
│   (Marks chapters as read on the new source       │
│    based on your current read position)           │
│                                                   │
│ MangaDex credentials (needed for read sync):      │
│   Username: [____________]                        │
│   Password: [____________]                        │
│                                                   │
│ Or: ☐ Skip — I'll re-mark chapters manually       │
│                                                   │
│        [← Back]              [Next →]             │
└───────────────────────────────────────────────────┘

Step 4 of 4: Review & Run
┌───────────────────────────────────────────────────┐
│ Summary:                                          │
│  • Migrate 47 titles from bato.to                 │
│  • Search: Manga Buddy, Weeb Central, MangaPark,  │
│    Asura, Flame                                   │
│  • Language: English                              │
│  • Remove old entries after migration: Yes        │
│  • Preserve read progress: Yes (via MangaDex)     │
│                                                   │
│ ☑ Dry run first (simulate without changes)        │
│                                                   │
│  [← Back]    [▶ Run Dry Run]    [▶ Run for Real]  │
│                                                   │
│ ┌─ Output ──────────────────────────────────────┐ │
│ │ [migrate 1/47] Solo Leveling → Manga Buddy   │ │
│ │   ✓ Found: 214 chapters (was 0)              │ │
│ │   ✓ Read progress: 180/214 chapters marked   │ │
│ │ [migrate 2/47] Blue Lock → Weeb Central      │ │
│ │   ✓ Found: 283 chapters (was 0)              │ │
│ │   ...                                        │ │
│ └───────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

### What This Means Concretely

The ~25 flags from the current flow collapse into **5 user decisions**:

| User decision | Current flags it replaces |
|---|---|
| "Which source is gone?" | `--migrate-library`, `--migrate-threshold-chapters 1`, `--migrate-filter-title`, `--migrate-include-categories`, `--migrate-exclude-categories` |
| "Where should titles move?" | `--migrate-sources`, `--exclude-sources`, `--best-source`, `--best-source-canonical`, `--best-source-candidates`, `--min-chapters-per-alt`, `--migrate-preferred-only`, `--prefer-sources`, `--prefer-boost`, `--migrate-max-sources-per-site`, `--migrate-try-second-page`, `--migrate-timeout` |
| "What language?" | `--preferred-langs`, `--lang-fallback` |
| "Remove old entries?" | `--migrate-remove`, `--migrate-remove-if-duplicate` |
| "Preserve read progress?" | `--import-read-chapters`, `--read-sync-number-fallback`, `--read-sync-across-sources`, `--read-sync-only-if-ahead`, `--read-sync-delay`, `--max-read-requests-per-minute`, `--cross-source-title-threshold` |

The smart defaults do the rest:
- `--best-source` and `--best-source-canonical` are **always on** in a migration — why would you ever want a worse source?
- `--read-sync-only-if-ahead` is **always on** — overwriting ahead-progress with behind-progress is never desirable
- `--read-sync-number-fallback` is **always on** when doing cross-source migration — UUID matching won't work across sources
- `--migrate-title-threshold` defaults to `0.7` for migrations (stricter than general use) — wrong matches during migration are worse than missed matches
- `--migrate-timeout` defaults to `20` — always reasonable
- `--best-source-candidates` defaults to `5` — good enough for most cases

### Other Workflows That Should Be Simplified

#### "Import from MangaDex" (currently 15+ fields)

Should be:
1. Enter MangaDex credentials
2. Choose what to import: ☑ Follows ☑ Reading statuses ☑ Read progress ☐ Custom lists
3. Map statuses to categories (dropdown per status, not a free-text string)
4. Run

The MangaDex tab currently exposes: debug login, debug follows, max follows, save import JSON, debug lists, lists category map, lists ignore, debug status, status endpoint raw, fallback per-manga, fallback throttle, ignore statuses, verify IDs, export statuses JSON, assume missing status, read chapters dry run, delay, max requests/min, number fallback, across sources, only if ahead, missing report path. That's 20+ controls where 4 decisions cover 90% of use cases.

#### "Clean Up Library" (currently 8+ fields across Prune tab)

Should be:
1. Choose cleanup type: "Remove duplicates" / "Remove non-English variants" / "Both"
2. Show preview of what will be removed
3. Confirm and run

### The "Advanced" Escape Hatch

The current full-flag interface shouldn't be deleted — it should be accessible via an "Advanced / Custom Command" option for power users and edge cases. But it should never be the *default* experience. Think of it like Photoshop's "Quick Selection" vs the full pen tool — most users need the simple version.

### Flags That Should Be Eliminated Entirely

Some flags exist only because the code doesn't have smart defaults:

| Flag | Why it exists | What should happen instead |
|---|---|---|
| `--migrate-title-threshold` | Different operations need different strictness | Each workflow sets its own sensible default |
| `--migrate-try-second-page` | Sometimes first page returns nothing | Always try second page — the cost is one extra API call |
| `--migrate-max-sources-per-site` | Performance concern | Default to 3, never expose it |
| `--best-source-candidates` | Performance concern | Default to 5, never expose it |
| `--read-sync-delay` | Server needs time to populate chapters | Auto-detect: poll chapter count after adding, retry if 0 |
| `--status-fallback-single` | Bulk endpoint sometimes fails | Always try bulk first, fall back to single automatically |
| `--status-fallback-throttle` | Rate limiting concern | Use centralized rate limiter, never expose the number |
| `--status-endpoint-raw` | Debug only | Move to debug log, not a checkbox |
| `--debug-login`, `--debug-follows`, `--debug-status`, `--debug-lists`, `--debug-read-sync` | 5 separate debug flags! | One "verbose logging" toggle, route through `logging` |
| `--no-title-fallback` | Edge case workaround | Smart retry logic instead of a flag |
| `--migrate-timeout` | Per-request timeout | Sensible default (20s), only in advanced |

### Summary

The GUI needs to shift from **"here are all the knobs"** to **"what are you trying to accomplish?"**. The current design forces users to understand the internal implementation (sources, thresholds, API call timing, endpoint shapes) just to do basic library maintenance. A wizard-based, task-oriented approach would make the same powerful features accessible without requiring users to play minesweeper with checkboxes.

---

## 8. API Reality Check: Live Server Testing

Tested against **Suwayomi-Server v2.1.1867** (Stable) running at `http://127.0.0.1:4567`, cross-referenced with the [server source code](https://github.com/Suwayomi/Suwayomi-Server) (Javalin/Kotlin). Note: the Swagger UI mentioned in the server README is **commented out** in the source (`JavalinSetup.kt` line ~65: `// config.registerPlugin(OpenApiPlugin(...))`) — no interactive API explorer is available.

The results reveal that most of the code's elaborate fallback chains are unnecessary — the code tries dozens of endpoint variations where only a handful actually exist. More critically, the endpoints it *does* hit are called with the **wrong parameter style**, causing silent failures.

### Authoritative REST API (from Server Source)

The following is the **complete REST API surface relevant to the importer**, compiled from `MangaAPI.kt`, `MangaController.kt`, and `Chapter.kt` in the server repository. No guessing — these are the actual registered Javalin routes.

#### Library & Manga

| Method | Path | Param Style | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/manga/{mangaId}` | Query: `?onlineFetch=false` | Get manga info |
| `GET` | `/api/v1/manga/{mangaId}/full` | Query: `?onlineFetch=false` | Get manga with all data filled |
| `GET` | `/api/v1/manga/{mangaId}/library` | — | **Add manga to library** (GET to mutate) |
| `DELETE` | `/api/v1/manga/{mangaId}/library` | — | **Remove manga from library** |

#### Chapters

| Method | Path | Param Style | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/manga/{mangaId}/chapters` | Query: `?onlineFetch=false` | List all chapters for manga |
| `GET` | `/api/v1/manga/{mangaId}/chapter/{chapterIndex}` | — | Get single chapter (by **index**, not ID) |
| `PATCH` | `/api/v1/manga/{mangaId}/chapter/{chapterIndex}` | **Form params**: `read`, `bookmarked`, `markPrevRead`, `lastPageRead` | **Modify single chapter** |
| `PUT` | `/api/v1/manga/{mangaId}/chapter/{chapterIndex}` | Same as PATCH (alias) | Same handler as PATCH |
| `POST` | `/api/v1/manga/{mangaId}/chapter/batch` | **JSON body**: `{ chapterIds: [int], chapterIndexes: [int], change: { isRead, isBookmarked, lastPageRead, delete } }` | **Batch edit chapters** (one manga) |
| `POST` | `/api/v1/chapter/batch` | **JSON body**: `{ chapterIds: [int], change: { isRead, isBookmarked, lastPageRead, delete } }` | **Batch edit chapters** (cross-manga) |

#### Categories

| Method | Path | Param Style | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/category` | — | **List all categories** |
| `GET` | `/api/v1/category/{categoryId}` | — | **Get manga in category** (category 0 = all library manga) |
| `POST` | `/api/v1/category` | Form: `name` | Create category |
| `PATCH` | `/api/v1/category/{categoryId}` | Form: `name`, `default`, `includeInUpdate`, `includeInDownload` | Modify category |
| `DELETE` | `/api/v1/category/{categoryId}` | — | Delete category |
| `GET` | `/api/v1/manga/{mangaId}/category` | — | List manga's categories |
| `GET` | `/api/v1/manga/{mangaId}/category/{categoryId}` | — | **Add manga to category** (GET to mutate) |
| `DELETE` | `/api/v1/manga/{mangaId}/category/{categoryId}` | — | **Remove manga from category** |

#### Sources

| Method | Path | Param Style | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/source/list` | — | List all sources |
| `GET` | `/api/v1/source/{sourceId}` | — | Get single source |
| `GET` | `/api/v1/source/{sourceId}/search` | Query: `?searchTerm=...&pageNum=1` | Search source |
| `POST` | `/api/v1/source/{sourceId}/quick-search` | Query: `?pageNum=1`, JSON body: filter data | Quick search with filters |

#### Other

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/settings/about` | Server version/build info |
| `POST` | `/api/graphql` | GraphQL endpoint (not under `/api/v1/`) |

### The Two Critical Bugs in the Code

#### Bug 1: `chapterIndex` vs `chapterId` — Silent No-Op

The REST chapter path is `/api/v1/manga/{mangaId}/chapter/{chapterIndex}` — the second parameter is the **1-based position index** in the chapter list, NOT the database chapter ID.

Live verification:
```
Chapter database id=21  →  has index=1  (it's the first chapter)
Chapter database id=25  →  has index=5  (it's the fifth chapter)
```

When the code sends `PATCH /api/v1/manga/1/chapter/21`, it's targeting the chapter at **index 21**, not the chapter with **id 21**. For manga with fewer than 21 chapters, this targets a non-existent index. The server returns 200 (no error), but nothing changes because the Javalin handler receives `null` form params and does nothing.

**The code uses database IDs (from GraphQL/chapter list responses) in a URL path that expects positional indexes.** This is why every REST chapter-mark attempt appeared to silently succeed but didn't actually modify anything.

#### Bug 2: JSON Body vs Form Params

The single-chapter PATCH expects **form-encoded parameters** (`application/x-www-form-urlencoded`), not JSON:

| What the code sends | What the server expects |
|---|---|
| `PATCH .../chapter/21` with `Content-Type: application/json`, body: `{"read": true}` | `PATCH .../chapter/{index}` with `Content-Type: application/x-www-form-urlencoded`, body: `read=true` |
| Parameter name `isRead` (several attempts) | Parameter name `read` |
| Chapter **database ID** in URL | Chapter **index** (1-based position) in URL |

Live test results with correct parameters:
```
PATCH /manga/1/chapter/1  data="read=true"  (form-encoded, correct index)
  → HTTP 200, isRead: True  ✓ WORKS!

PATCH /manga/1/chapter/5  data="read=true&markPrevRead=true"  (form-encoded)
  → HTTP 200, chapters 1-5 all marked read  ✓ WORKS!

POST /manga/1/chapter/batch  json={chapterIds:[21,22], change:{isRead:true}}
  → HTTP 200, both chapters marked read  ✓ WORKS!

POST /chapter/batch  json={chapterIds:[21,22], change:{isRead:true}}
  → HTTP 200, both chapters marked read  ✓ WORKS!
```

**The REST batch endpoints use database IDs (correct) and JSON body (correct).** They work perfectly. The code never tries them.

### REST Endpoints That Don't Exist

The code tries these paths that aren't registered in the server at all:

| Endpoint | The code tries it in | Verdict |
|---|---|---|
| `GET /api/v1/library` | `get_library()` #1 | Returns HTML (SPA web UI), not JSON — no such REST endpoint |
| `GET /api/v1/manga/list` | `get_library()` #2 | 404 |
| `GET /api/v1/manga` | `get_library()` #3 | 404 |
| `GET /api/v1/library/list` | `get_library()` #4 | 404 |
| `GET /api/v1/library/manga` | `get_library()` #5 | 404 |
| `GET /api/v1/category/list` | `list_categories()` #1 | 404 |
| `GET /api/v1/categories` | `list_categories()` #3 | 404 |
| `POST /api/v1/chapter/{id}/read` | `mark_chapter_read()` #1 | 404 |
| `POST /api/v1/chapters/{id}/read` | `mark_chapter_read()` #2 | 404 |
| `PUT /api/v1/chapter/{id}/read` | `mark_chapter_read()` #5 | 404 |
| `POST /api/v1/chapter/read` | `mark_chapter_read()` #7 | 404 |
| `POST /api/v1/chapter/batch/read` | `mark_chapter_read()` #9 | 404 |
| `GET /api/v1/manga/{id}/library/remove` | `remove_from_library()` #2 | Not a registered route (may get caught by SPA fallback) |

None of these paths exist in `MangaAPI.kt`. They are guesses.

### The Code's Fallback Chains vs. Reality

#### `mark_chapter_read()` — 14 attempts, wrong on every REST call

```
Code tries (in order):                          Problem:
──────────────────────────────────────────────────────────────────────────
 1. POST /api/v1/chapter/{id}/read              Path doesn't exist (404)
 2. POST /api/v1/chapters/{id}/read             Path doesn't exist (404)
 3. PATCH /api/v1/chapter/{id} {read:true}      Wrong path (no /manga/ prefix)
 4. PATCH /api/v1/chapters/{id} {read:true}     Path doesn't exist (404)
 5. PUT /api/v1/chapter/{id}/read               Path doesn't exist (404)
 6. PUT /api/v1/chapters/{id}/read              Path doesn't exist (404)
 7. POST /api/v1/chapter/read {ids}             Path doesn't exist (404)
 8. POST /api/v1/chapters/read {ids}            Path doesn't exist (404)
 9. POST /api/v1/chapter/batch/read             Path doesn't exist (404)
10. GET  /api/v1/chapter/read?id={id}           Path doesn't exist
11. POST /api/v1/chapter/read?id={id}           Path doesn't exist
12. GET  /api/v1/chapter/{id}/read              Path doesn't exist (200 = SPA HTML)
13. GQL updateChapters (batch)                  ✓ WORKS
14. GQL updateChapter (single)                  ✓ WORKS
```

None of the 12 REST attempts use the correct path (`/api/v1/manga/{mangaId}/chapter/{chapterIndex}`), correct parameter style (form-encoded), or correct identifier (index not ID). The code falls through to GraphQL every time.

What it should be — REST batch (best):
```python
def mark_chapters_read(self, chapter_ids: list[int]) -> None:
    """Mark chapters as read using database IDs."""
    requests.post(
        f"{self.base_url}/api/v1/chapter/batch",
        json={"chapterIds": chapter_ids, "change": {"isRead": True}}
    )
```

Or GraphQL batch:
```python
def mark_chapters_read(self, chapter_ids: list[int]) -> None:
    self.graphql(
        "mutation($ids:[Int!]!) { updateChapters(input:{ids:$ids,patch:{isRead:true}}) { chapters { id isRead } } }",
        {"ids": chapter_ids}
    )
```

One call. Batch. Done. The `markPrevRead` form param is also available for "mark all previous chapters read" in a single request.

#### `get_library()` — 5 REST endpoints fail, then 17+ GraphQL attempts

```
Code tries (REST phase):               Server response:
──────────────────────────────────────────────────────────
 1. GET /api/v1/library          → 200 HTML (web UI, not JSON!)
 2. GET /api/v1/manga/list       → 404
 3. GET /api/v1/manga            → 404
 4. GET /api/v1/library/list     → 404
 5. GET /api/v1/library/manga    → 404

(All REST fail, then get_library_graphql() starts)

Code tries (GraphQL phase — 17+ queries including introspection):
 6-22. Various query shapes including "library { entries ... }",
       "mangaList", dynamic __schema introspection, etc.

What actually works:
  REST: GET /api/v1/category/0  → returns all library manga as JSON array
  GQL:  { mangas(condition:{inLibrary:true}) { nodes { id title } } }
```

Note that `GET /api/v1/library` returns HTTP 200 with HTML content (the Suwayomi web UI SPA fallback), so the code sees a 200 status but gets HTML instead of JSON. This triggers a JSON parse error that the code catches and moves on from.

The **correct REST path** for library listing is `GET /api/v1/category/0` (category 0 = default = all library manga) or `GET /api/v1/category/{id}` for a specific category. These return proper JSON arrays of `MangaDataClass`.

#### `get_manga_chapters_count()` — 8 attempts for a simple count

```
Code tries (REST):                 Server response:     Needed?
──────────────────────────────────────────────────────────────────
 1. GET .../chapters      → 200 (list of chapters)     Works (but returns full objects)
 2. GET .../chapter       → same endpoint alias         Redundant
 3. GET ...?withChapters  → 200 (manga detail only)     Useless
 4. GET .../manga/{id}    → 200 (manga detail only)     Useless
 5-8. Four GraphQL variants with different field names

What actually works:
  GET /api/v1/manga/{id}/chapters         → len(result) = chapter count
  { manga(id:N) { chapters { totalCount } } }  → direct count, no transfer
```

The GraphQL `totalCount` is the most efficient — it returns a count without transferring all chapter objects.

#### `list_categories()` — 3 attempts for a simple list

```
Code tries:                      Server response:
─────────────────────────────────────────────────
 1. GET /api/v1/category/list  → 404
 2. GET /api/v1/category       → 200 ✓
 3. GET /api/v1/categories     → 404
```

Only `GET /api/v1/category` is a registered route.

### Summary: Correct API Surface

For Suwayomi v2.1.x, the **entire working API** the code needs:

| Operation | Best endpoint | Alternative |
|---|---|---|
| Get library | REST `GET /api/v1/category/0` | GQL `mangas(condition:{inLibrary:true}) { nodes { ... } }` |
| Get manga details | REST `GET /api/v1/manga/{id}` | GQL `manga(id:N) { ... }` |
| Get chapters | REST `GET /api/v1/manga/{id}/chapters` | GQL `manga(id:N) { chapters { nodes { ... } } }` |
| Get chapter count | GQL `manga(id:N) { chapters { totalCount } }` | REST `GET .../chapters` then `len()` |
| **Mark chapters read** | **REST `POST /api/v1/chapter/batch`** (JSON, uses DB IDs) | GQL `updateChapters` (batch) |
| Mark single chapter | REST `PATCH /api/v1/manga/{mid}/chapter/{INDEX}` (form, uses **index**) | GQL `updateChapter` |
| Mark previous read | REST `PATCH .../chapter/{INDEX}` with `markPrevRead=true` | No GQL equivalent |
| Add to library | REST `GET /api/v1/manga/{id}/library` | GQL `updateManga(inLibrary:true)` |
| Remove from library | REST `DELETE /api/v1/manga/{id}/library` | GQL `updateManga(inLibrary:false)` |
| Assign category | REST `GET /api/v1/manga/{id}/category/{catId}` | GQL `updateMangaCategories` |
| Remove category | REST `DELETE /api/v1/manga/{id}/category/{catId}` | GQL `updateMangaCategories` |
| List categories | REST `GET /api/v1/category` | GQL `categories { nodes { id name } }` |
| Get category manga | REST `GET /api/v1/category/{id}` | — |
| Search source | REST `GET /api/v1/source/{id}/search?searchTerm=...` | GQL `fetchSourceManga` (LongString source ID) |
| List sources | REST `GET /api/v1/source/list` | GQL `sources { nodes { ... } }` |

**The code currently has ~70 endpoint attempts across its fallback chains. The actual working API surface is ~15 endpoints.** The rest are:
- Paths that don't exist in the server (guesses)
- Correct paths with wrong parameter encoding (JSON instead of form-encoded)
- Correct paths with wrong identifiers (database ID instead of chapter index)
- The `/api/v1/library` SPA fallback that returns HTML

### Root Cause

Two separate issues compound:

1. **No API documentation consulted.** The code was written by guessing endpoint shapes. The Swagger UI referenced in the server README is commented out in the source, so there's no interactive explorer. But the route definitions in `MangaAPI.kt` are clear and concise.

2. **`chapterIndex` vs `chapterId` confusion.** The REST API uses positional indexes for single-chapter paths but database IDs for batch endpoints. This asymmetry is a server design quirk, but the server source makes it explicit — `pathParam<Int>("chapterIndex")` vs `chapterIds: List<Int>` in the batch input. The code treats both as the same thing.

The consequences:
- **12 wasted REST requests per chapter mark.** None reach a valid endpoint.
- **Silent success with no effect.** Several paths return 200 (caught by the SPA fallback or by the server accepting but ignoring malformed params).
- **Massive latency.** Marking 500 chapters generates 6,000+ failed requests before GraphQL succeeds.
- **Debugging is impossible.** Every operation produces 12+ "trying endpoint X... failed" log lines.

The fix: use `POST /api/v1/chapter/batch` with `{chapterIds: [...], change: {isRead: true}}` for batch operations, or the GraphQL `updateChapters` mutation. Drop all other chapter-marking attempts.

---

## 9. SuwayomiClient

### Strengths
- Handles 4 auth modes with smart fallback
- `normalize_search_items()` handles 10+ response shapes
- `extract_manga_id()` handles varied field names
- `request()` auto-retries on 401 for `auto` auth mode

### Issues

1. **Mixed responsibilities.** The client class contains both HTTP communication and business logic:
   - `get_manga_chapters_canonical_count()` implements canonical chapter deduplication — that's business logic, not API communication
   - `_filter_items_by_lang()` is domain logic
   - `get_manga_chapters_count_by_lang()` combines fetching, filtering, and counting

2. **`get_library_graphql()` is ~200 lines of dead code.** As confirmed by live testing (§8), it tries 17+ GraphQL query shapes where the first one works. The other 16 are for hypothetical Suwayomi schemas that don't exist in any current server version. This is a schema-discovery engine for a schema that has been stable for years.

3. **`mark_chapter_read()` has three compounding bugs.** Live testing + server source analysis (§8) found:
   - The URL path uses database `chapterId` where the server expects `chapterIndex` (1-based position) — wrong identifier
   - It sends JSON body where the server expects `application/x-www-form-urlencoded` — wrong encoding
   - The parameter is named `read` (not `isRead`) in form params — wrong field name
   - None of the 12 REST attempts use the correct path `/api/v1/manga/{mangaId}/chapter/{INDEX}`
   - The REST batch endpoint `POST /api/v1/chapter/batch` (which uses DB IDs and JSON) is never tried
   - All 12 REST calls fail, falling through to GraphQL every time

4. **`get_library()` starts with a non-API path that returns HTML.** `GET /api/v1/library` isn't a registered REST route — the SPA serves HTML for any unmatched path. The correct REST library endpoint is `GET /api/v1/category/0` (all library manga) or `GET /api/v1/category/{id}` (per category).

5. **REST chapter PATCH/PUT silently does nothing (index/ID mismatch).** The server's `PATCH /api/v1/manga/{mid}/chapter/{chapterIndex}` expects a 1-based chapter **position index**, but the code passes the database **chapter ID**. For a manga with 77 chapters, sending `chapter/535051` (a real DB ID) targets an index that doesn't exist. The server returns 200 and does nothing. This was the root cause of the "silent no-op" — not a broken endpoint, but wrong identifiers.

6. **No response caching.** The library is fetched fresh in several places within a single run.

7. **GET for mutations.** `add_to_library()` and `add_manga_to_category()` use HTTP GET. This is a real Suwayomi server API quirk (confirmed working), but it should be documented.

### Recommendation

Split into:
- `SuwayomiHttpClient` — raw HTTP + GraphQL communication, auth, retries
- `SuwayomiLibrary` — library operations (add, remove, categories, list)
- `SuwayomiChapters` — chapter operations (list, count, mark read, canonical count)
- `SuwayomiSources` — source listing, searching

Each with clear interfaces, using the known-working endpoints from §8. No fallback chains. Domain logic (canonical counting, language filtering, etc.) moves to the `operations/` layer.

---

## 10. MangaDex Integration

The MangaDex code (~600 lines) handles:
- OAuth login with client credentials, 2FA, and token refresh
- Paginated follows fetch (with configurable limits)
- Reading status retrieval (bulk + single-manga fallback)
- Read chapter UUID retrieval
- Custom list enumeration and membership
- Title search for CSV resolution

### Issues

1. **Not encapsulated as a client.** MangaDex functions are module-level functions (`mangadex_login()`, `fetch_follows()`, `fetch_reading_statuses()`, etc.) that share state through returned values passed back via `main()`. There's no `MangaDexClient` class.

2. **Secrets in memory.** MangaDex credentials (username, password, client ID/secret) are passed as plain strings through multiple function layers. While this is typical for CLI tools, a proper secrets handling pattern (or at minimum clearing them after use) would be better.

3. **Rate limiting is ad-hoc.** `time.sleep()` calls are scattered throughout, with values that sometimes come from CLI flags and sometimes are hardcoded. No centralized rate limiter.

4. **`fetch_reading_statuses()` has two entirely separate code paths** — a bulk endpoint and a per-manga fallback. The fallback can generate hundreds/thousands of API calls with no progress indicator if the bulk endpoint fails.

---

## 11. Title Matching & Fuzzy Logic

```python
def _title_similarity(a: str, b: str) -> float:
    ta = set(_normalize_title_tokens(a))
    tb = set(_normalize_title_tokens(b))
    inter = ta & tb
    union = ta | tb
    return len(inter) / len(union)
```

### What Works
- Normalization strips brackets, parentheticals, noise words (Official, Colored), stop words
- Token-based Jaccard is fast and reasonable for most manga titles
- Strict mode requires exact normalized match

### What Doesn't
- **Short titles have inflated similarity.** "Blue Lock" and "Blue Box" share "blue" and get 0.5 similarity (above the 0.6 default threshold for CSV import). Similarly, single-word titles like "Berserk" and "Bersert" (typo) get 0.0 because Jaccard doesn't handle edit distance.
- **No n-gram or edit distance fallback.** Cases like "Jujutsu Kaisen" vs "Jujustu Kaisen" (common typo) score 0.5 instead of near-1.0.
- **Token Jaccard is symmetric but matching shouldn't be.** If the library has "Attack on Titan: Season 2" and the CSV has "Attack on Titan", containment (already partially implemented) is the right metric, not Jaccard.

### Recommendation
- **Primary:** Keep token Jaccard as the fast path
- **Secondary:** Add character-level edit distance (Levenshtein ratio) as a fallback when Jaccard is below threshold but above a lower bound
- **Or:** Use the `rapidfuzz` library which provides `fuzz.ratio`, `fuzz.token_sort_ratio`, and `fuzz.partial_ratio` — all of which are battle-tested for exactly this use case and implemented in C (fast)

---

## 12. Chapter Sync & Read Progress

This is the most complex feature and the most valuable for the bato.to shutdown scenario.

### Strengths
- UUID-based matching (MangaDex chapter UUID embedded in Suwayomi chapter URL) — very precise
- Number-based fallback when UUIDs don't match (different sources)
- Cross-source sync — applies progress from one source entry to same-title entries under other sources
- Canonical chapter deduplication (fractional chapters)
- Rate limiting and delay support
- Missing-reads CSV report

### Issues

1. **`mark_chapter_read()` tries 14 different API calls.** This is the single most impactful performance problem. For a library of 500 manga with 100 chapters each, that's potentially 500 × 100 × 14 = 700,000 HTTP requests in the worst case. In practice, an early endpoint usually works, but the fallback behavior is catastrophic when none of the REST ones work and it always falls through to GraphQL.

   **Fix:** Probe once at startup which endpoints work, then use only that one. Cache the result.

2. **No batch marking.** `mark_chapter_read()` marks one chapter at a time. The GraphQL `updateChapters` mutation supports batch operations but is only tried as a single-chapter call. Implementing batch marking would reduce API calls by 50-100x for large libraries.

3. **Rate limiting is honor-system.** The `--max-read-requests-per-minute` flag controls a `time.sleep()` delay, but doesn't account for time spent on failed endpoints. If 13 endpoints fail before the 14th works, the actual rate is 14x the nominal rate.

4. **Missing report is append-only.** The CSV file is opened and appended to for each manga. On Windows, if the file is open in Excel, the append fails silently. There's a note in the README about this, but a better approach would be to buffer in memory and write once at the end.

---

## 13. CSV Import Pipeline

### Strengths
- Auto-detects CSV format from headers
- `CsvItem` dataclass is well-designed
- Column mapping override for unknown formats
- External ID extraction (MAL, AniList, MangaUpdates)
- Read progress preservation via `last_read_chapter`
- Status mapping to Suwayomi categories

### Issues

1. **Two import paths.** When `--csv-no-mangadex` is set, items go through `process_csv_direct_items()` which searches Suwayomi sources directly. Otherwise, they go through a MangaDex title search → UUID resolution → `import_ids()` pipeline. These two paths have different behavior, different error handling, and different progress reporting. They should share a common pipeline.

2. **Library snapshot loaded eagerly.** `process_csv_direct_items()` fetches the entire library upfront. For large libraries (10,000+ entries), this can be slow and memory-intensive. A lazy lookup or indexed approach would be better.

3. **Source selection is naive.** `_select_candidate_sources()` matches source names against CSV source hints using substring matching. A CSV from Manganato checks all sources for "manganato" in their name. This means it searches sources like "ComickManganato" (hypothetical) even when the intent was the official source.

4. **No progress callback or cancellation.** The CSV import loop runs synchronously with no way to report progress to a GUI or cancel mid-run.

---

## 14. Migration & Pruning

### Migration
The migration mode (`--migrate-library`) scans the library and finds alternative sources for under-performing entries. It's powerful but complex:

- Scores alternatives by chapter count, canonical count, language preference, source preference
- Supports "keep both" mode for backup coverage
- Can filter by category, title pattern, source inclusion/exclusion

**Issues:**
- The scoring logic is inline in `main()` — not testable in isolation
- "Best source" mode generates multiple search requests per source per title — very slow for large libraries
- No caching of search results — the same title searched across 5 sources triggers 5 separate API calls

### Pruning
Two prune modes: zero-chapter duplicate removal and non-preferred-language removal.

**Issues:**
- Prune groups entries by normalized title, but normalized titles can collide for genuinely different manga (e.g., "Monster" could be 3 different series)
- No confirmation or preview of what will be removed (except dry-run) — a single command can remove hundreds of entries
- The pruning logic is also inline in `main()`

---

## 15. Error Handling & Logging

This is the single biggest quality issue after architecture.

### Current State

```python
try:
    resp = self.request("GET", endpoint)
    return resp.json()
except Exception:
    pass  # ← silent failure
```

This pattern (or close variants) appears **hundreds** of times. Real errors — network timeouts, API changes, authentication failures, JSON decode errors, type mismatches — are all swallowed silently.

Debug output is gated behind 5+ different `--debug-*` flags, and even then uses `print()` with manual prefix strings like `[read-debug]`, `[lib-debug]`, `[migrate]`.

### What Should Happen

1. **Use Python `logging`.** Replace all `print()` calls with `logger.info()`, `logger.debug()`, `logger.warning()`, `logger.error()`. Gate verbose output on log level, not custom flags.

2. **Never bare `except Exception: pass`.** At minimum, log the exception. In most cases, the appropriate action is to log and continue (for recovery loops) or log and raise (for critical operations).

3. **Domain-specific exceptions.** Define exceptions like `SuwayomiConnectionError`, `MangaDexAuthError`, `TitleNotFoundError` instead of catching `Exception` everywhere.

4. **Structured error accumulation.** Instead of printing errors inline, collect them and report at the end. This is partially done with the `failures` list in `process_csv_direct_items()` but inconsistently applied elsewhere.

---

## 16. Testing

### Current State

| File | Tests | Coverage |
|---|---|---|
| `test_title_and_input_helpers.py` | 9 tests | Title normalization, similarity, ID extraction, file reading, chapter helpers |
| `test_suwayomi_client_http.py` | 3 tests | `remove_from_library` fallback, GraphQL endpoint fallback |
| **Total** | **12 tests** | **Utility functions only** |

### What's Not Tested

- `main()` (any mode, any argument combination)
- `import_ids()` end-to-end flow
- `process_csv_direct_items()` end-to-end flow
- CSV parsing with real-world files
- MangaDex login/follows/statuses flow
- Migration logic
- Prune logic
- Read sync logic
- Cross-source sync
- GUI `build_args()` correctness
- Error recovery paths

### What's Needed

The test infrastructure is already set up (pytest, responses, conftest with fixtures). The problem isn't missing tooling — it's that the code is structured in a way that makes testing impractical. A 1,700-line `main()` that directly calls external APIs can't be unit-tested.

**Priority test targets after restructuring:**
1. Each subcommand's orchestration logic (with mocked clients)
2. `SuwayomiClient` HTTP behavior (already started — expand)
3. CSV parsing edge cases (malformed files, missing columns, encoding issues)
4. Title matching edge cases (short titles, non-Latin, near-misses)
5. Migration scoring logic (deterministic, no I/O)
6. Read sync chapter resolution logic

---

## 17. Security & Safety

### Good
- TLS verification is on by default (`--insecure` required to disable)
- Destructive operations require explicit flags
- GUI confirms destructive actions
- Dry-run is comprehensive

### Concerns

1. **Credentials on command line.** `--md-password`, `--password`, and `--token` appear in the CLI command — visible in process lists, shell history, and the GUI's command preview. Consider environment variable or config file support.

2. **No input sanitization for file paths.** The `--from-csv`, `--missing-report`, and input file paths are passed directly to `open()`. While this is a local tool, path traversal isn't considered.

3. **Plaintext credentials in config.** The GUI's `_save_config()` stores the base URL and potentially other settings in `%APPDATA%` as plain JSON. If credentials were ever saved (currently they aren't), they'd be in plaintext.

4. **HTTP GET for mutations.** `add_to_library()` uses GET — this means browser prefetching, proxy caching, or log systems could inadvertently trigger library mutations. This is a server-side issue, but the client should document the risk.

---

## 18. Dependencies & Packaging

### Runtime Dependencies
- `requests` — not in `requirements.txt` (implicit dependency!)
- `pandas` — optional, used for xlsx reading
- `pyinstaller` — in `requirements.txt` but is a build tool, not a runtime dependency
- `markdown` and `tkhtmlview` — GUI-only optional deps, in `requirements.txt`

### Issues
1. **`requests` is missing from `requirements.txt`.** The main script does `import requests` but it's not listed. It probably installs as a transitive dependency of something else, but this is fragile.
2. **Build tools in runtime requirements.** `pyinstaller` should be in `requirements-dev.txt`, not `requirements.txt`.
3. **No pinned versions for runtime deps.** Only dev deps have minimum versions specified.

### Recommended `requirements.txt`
```
requests>=2.28.0
```

### Recommended `requirements-dev.txt`
```
pytest>=8.3.0
pytest-cov>=5.0.0
responses>=0.25.0
pytest-httpserver>=1.1.0
freezegun>=1.4.0
factory_boy>=3.3.0
pyinstaller>=6.6.0
markdown>=3.5
tkhtmlview>=0.3.1
```

---

## 19. Known Bugs & Correctness Issues

These were identified from code reading (also partly documented in `docs/importer_refactor_proposal.md`):

1. **Duplicate `return 0` in `get_manga_chapters_count()`.** Two consecutive `return 0` statements — the second is dead code.

2. **`_auth()` has duplicate status code `303`.** Line `if resp.status_code not in (200, 302, 303, 303):` — `303` is listed twice, likely meant to include `301`.

3. **`visit()` nested function redefined in a loop.** Inside `get_manga_chapters_count()`, the `visit()` function and its `ids` list are recreated on each iteration of the GraphQL fallback loop — wastes memory and is confusing.

4. **Read-sync token lost with `--md-login-only`.** The `session_token` is only passed to `import_ids()` when `--from-follows` is set. Using `--md-login-only` + `--import-read-chapters` means read sync silently gets no auth token.

5. **Preference filter in rehome path is a no-op.** The branch that should skip non-preferred sources does `pass` instead of `continue`.

6. **Missing report can silently fail on Windows.** File append fails when the CSV is open in Excel, but the exception is caught and suppressed.

7. **`_normalize_last_read()` rejects valid dates.** The string `"0"` is rejected, but some sources use `0` to mean "first chapter" not "no data".

8. **`--list-library-titles` blocked by MangaDex gate.** Running `--list-library-titles` without an input file or `--from-follows` hits the "No MangaDex IDs to process" check at L2993 before reaching the list-library code at L3430. The exemption list checks `list_categories`, `migrate_library`, and the prune modes, but `list_library_titles` was never added.

---

## 20. Overhaul Roadmap

### Phase 0: Cleanup & Consolidation (no behavior changes)

**Goal:** Reduce confusion, fix bugs, improve developer experience.

- [ ] Delete the original `import_mangadex_bookmarks_to_suwayomi.py` or clearly mark it as deprecated
- [ ] Fix the known bugs listed in §19
- [ ] Add `requests` to `requirements.txt`, move `pyinstaller` to dev
- [ ] Replace `print()` with Python `logging` — keep all existing outputs but route through loggers
- [ ] Replace global variables with a config object passed explicitly
- [ ] **Decouple MangaDex from non-MangaDex operations (§3).** Remove the "No MangaDex IDs" gate or invert it to a per-mode dispatch. Make `--from-csv` default to direct Suwayomi import (current `--csv-no-mangadex` behavior). Rename `--rehoming-remove-mangadex` to `--rehoming-remove-source`. Fix `--list-library-titles` gate bug.
- [ ] Rename program description from "Import MangaDex bookmarks" to "Suwayomi library manager"

### Phase 1: Modularize (same features, same CLI, new structure)

**Goal:** Split the monolith into importable modules without changing external behavior.

- [ ] **Rewrite `SuwayomiClient` using the correct API endpoints (§8).** Remove all fallback chains. Use `POST /api/v1/chapter/batch` (REST) or GraphQL `updateChapters` for chapter marking, `GET /api/v1/category/0` or GQL `mangas(condition:{inLibrary:true})` for library fetch. Fix the `chapterIndex` vs `chapterId` confusion and form-encoded vs JSON parameter encoding.
- [ ] **Delete ~500 lines of dead fallback code.** The 12-endpoint `mark_chapter_read()`, 17-query `get_library_graphql()`, and 8-attempt `get_manga_chapters_count()` each collapse to ~5 lines.
- [ ] Extract `SuwayomiClient` into `seiyomi/clients/suwayomi.py`
- [ ] Extract MangaDex functions into `seiyomi/clients/mangadex.py`
- [ ] Extract title matching into `seiyomi/matching/titles.py`
- [ ] Extract CSV parsing into `seiyomi/importers/csv_import.py`
- [ ] Extract read sync into `seiyomi/operations/read_sync.py`
- [ ] Extract migration into `seiyomi/operations/migrate.py`
- [ ] Extract prune into `seiyomi/operations/prune.py`
- [ ] Create config dataclasses for each operation domain
- [ ] Keep the existing CLI interface as a thin wrapper that delegates to modules
- [ ] Add tests for each extracted module

### Phase 2: Subcommand CLI + Smart Defaults (new interface, same features)

**Goal:** Replace the 70-flag flat CLI with subcommands and bake in sensible defaults so the common case requires minimal flags (see §5 and §7).

- [ ] Implement `seiyomi migrate` with auto-best-source, auto-canonical, sensible defaults for threshold/timeout/candidates
- [ ] Implement `seiyomi import follows`, `seiyomi import csv`, `seiyomi import ids`
- [ ] Implement `seiyomi prune duplicates`, `seiyomi prune languages`
- [ ] Implement `seiyomi sync reads`
- [ ] Implement `seiyomi list categories`, `seiyomi list library`
- [ ] Shared parent parser for connection/auth/dry-run
- [ ] Validate flag dependencies at parse time (not at runtime)
- [ ] Eliminate flags that should be smart defaults (see §7 table: always try second page, always auto-fallback, etc.)
- [ ] Collapse 5 debug flags into one `--verbose` / `-v` with log levels
- [ ] Consider using `click` or `typer` instead of `argparse` for better UX
- [ ] Example: `seiyomi migrate --from bato.to --to "manga buddy,weeb central" --lang en --remove-old` should be the entire command for the bato.to scenario

### Phase 3: GUI Rebuild

**Goal:** Replace the minesweeper checkbox wall with task-oriented workflows (see §7).

- [ ] Home screen with workflow cards: "Migrate a Dead Source", "Import from MangaDex", "Import from CSV", "Clean Up Library", "Advanced"
- [ ] Wizard flow for each workflow (step-by-step, only relevant options per step)
- [ ] Smart defaults per workflow — no exposed thresholds, timeouts, or debug flags in normal mode
- [ ] Source auto-detection: query library on startup, show which sources exist and how many titles each has
- [ ] Status-to-category mapping via dropdown per status, not a free-text string
- [ ] Embedded output panel showing real-time stdout/stderr from the running process
- [ ] Cancel button that kills the subprocess
- [ ] Progress bar (parse stdout markers for progress)
- [ ] "Advanced / Custom Command" escape hatch preserving full flag access for power users
- [ ] Class-per-tab/wizard-step architecture internally
- [ ] Shared `AppState` dataclass replacing `vals` dict
- [ ] Field validation (highlight missing required fields, disable Run when incomplete)
- [ ] Consider moving to CustomTkinter or textual for a modern look

### Phase 4: Quality of Life

**Goal:** Make the tool genuinely pleasant to use.

- [ ] ~~Endpoint probing at startup~~ — no longer needed; §8 mapped the correct endpoints. Just use them directly.
- [ ] ~~Batch `mark_chapter_read()`~~ — moved to Phase 1; this is a bug fix, not a nice-to-have (REST chapter marking silently does nothing)
- [ ] Centralized rate limiter (token bucket) instead of scattered `time.sleep()`
- [ ] Better title matching (add `rapidfuzz` as optional dependency)
- [ ] Interactive mode where ambiguous matches are presented to the user for selection
- [ ] Credential support via environment variables (`SEIYOMI_BASE_URL`, etc.)
- [ ] Cross-platform support (or at least document Windows-only limitations)

### Phase 5: Robustness

**Goal:** Make it reliable for large libraries and unattended runs.

- [ ] Structured error accumulation and end-of-run summary
- [ ] Retry with exponential backoff for transient API failures
- [ ] Resumable operations (checkpoint file for long migrations)
- [ ] Library cache to avoid redundant full-library fetches within a run
- [ ] Integration tests with a Docker Suwayomi instance

---

## Appendix: File Inventory

| File | Lines | Role | Keep? |
|---|---|---|---|
| `import_mangadex_bookmarks_to_suwayomi_refactored.py` | 4,426 | Main CLI (canonical) | Decompose into `seiyomi/` package |
| `import_mangadex_bookmarks_to_suwayomi.py` | 3,571 | Original CLI (deprecated) | Delete or archive |
| `gui_launcher_tk.py` | 1,713 | GUI launcher | Rebuild as `seiyomi/gui/` |
| `Convert .xlsx to .xml MAL.py` | — | Standalone converter | Move to `scripts/` |
| `Export libraries from MangaDex.py` | — | Standalone exporter | Move to `scripts/` |
| `Mangaupdates MD List.py` | — | Standalone tool | Move to `scripts/` |
| `get-pip.py` | — | pip bootstrapper | Delete (shouldn't be in repo) |
| `run_importer.bat` | — | Batch launcher | Keep or replace with entry point |
| `build_exe.ps1` | — | PyInstaller build script | Keep in `scripts/` |

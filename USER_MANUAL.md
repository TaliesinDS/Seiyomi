# Seiyomi User Manual

A step-by-step guide to managing your Suwayomi manga library with Seiyomi. Covers everything from first install to advanced migration workflows.

For a quick feature overview, see [README.md](README.md).

---

## Table of Contents

1. [What This Tool Does](#1-what-this-tool-does)
2. [Prerequisites](#2-prerequisites)
3. [Installation](#3-installation)
4. [Quick Start Recipes](#4-quick-start-recipes)
5. [CSV Import (Comick, Manganato)](#5-csv-import)
6. [Library Migration](#6-library-migration)
7. [Pruning (Duplicates & Languages)](#7-pruning)
8. [MangaDex Import](#8-mangadex-import)
9. [Read Progress Sync](#9-read-progress-sync)
10. [Interactive Mode & Resume](#10-interactive-mode--resume)
11. [Listing & Inspection](#11-listing--inspection)
12. [GUI](#12-gui)
13. [Categories & Status Mapping](#13-categories--status-mapping)
14. [Title Matching](#14-title-matching)
15. [Safety & Dry Runs](#15-safety--dry-runs)
16. [Troubleshooting](#16-troubleshooting)
17. [Old Command Translation](#17-old-command-translation)

---

## 1. What This Tool Does

Seiyomi manages your Suwayomi manga library from the command line or a GUI. It can:

- **Import** manga from CSV exports (Comick, Manganato) or MangaDex follows
- **Migrate** zero/low-chapter entries to better sources across all installed extensions
- **Prune** duplicate entries and non-preferred-language variants
- **Sync** MangaDex read progress into Suwayomi (including cross-source by chapter number)
- **List** your library, categories, and installed sources

It does **not**:

- Create Suwayomi categories (create them in the Suwayomi UI first)
- Recover DMCA-removed or delisted chapters
- Run continuously (it's a one-time or occasional-run tool)

---

## 2. Prerequisites

| What | Why | How to get it |
|------|-----|---------------|
| Python 3.10+ | Runs the tool | [python.org/downloads](https://www.python.org/downloads/) — check "Add to PATH" during install |
| Suwayomi server | Your manga library | Start your server (default: `http://localhost:4567`) |
| MangaDex account (optional) | Only needed for `import follows` and `sync reads` | Your existing MangaDex login |

**Check Python is installed:**

```powershell
python --version
# Should print: Python 3.10.x or higher
```

---

## 3. Installation

```powershell
git clone https://github.com/yourusername/Seiyomi.git
cd Seiyomi
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

Verify:

```powershell
python -m seiyomi --help
```

You should see the help text listing all subcommands.

> **Note:** Throughout this manual, `seiyomi` is shorthand for `python -m seiyomi`. If the command isn't on your PATH, use the full form.

---

## 4. Quick Start Recipes

These are copy-paste commands for the most common tasks. All use `--dry-run` so nothing changes on your first attempt — remove it when you're happy with the output.

### See what's in your library

```powershell
seiyomi list categories --base-url http://127.0.0.1:4567
seiyomi list library --base-url http://127.0.0.1:4567
seiyomi list sources --base-url http://127.0.0.1:4567
```

### Import a Comick CSV export

```powershell
seiyomi import csv `
  --file comick-mylist-2025-09-23.csv `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Migrate zero-chapter entries to better sources

```powershell
seiyomi migrate `
  --to "bato.to,mangabuddy,weeb central,mangapark" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Remove duplicate zero-chapter entries

```powershell
seiyomi prune duplicates `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Remove non-English language variants

```powershell
seiyomi prune languages `
  --lang en `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Import MangaDex follows

```powershell
seiyomi import follows `
  --md-user YOUR_USER `
  --md-pass YOUR_PASS `
  --import-status `
  --status-map "completed=5,reading=2,dropped=8" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

---

## 5. CSV Import

Import manga from a Comick or Manganato CSV export. The format is auto-detected from column headers.

### Basic import

```powershell
seiyomi import csv `
  --file comick-mylist-2025-09-23.csv `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Map CSV statuses to Suwayomi categories

First, find your category IDs:

```powershell
seiyomi list categories --base-url http://127.0.0.1:4567
# Output: 2: Reading, 5: Completed, 7: On Hold, 8: Dropped, 9: Plan to Read
```

Then import with the mapping:

```powershell
seiyomi import csv `
  --file comick-mylist.csv `
  --status-map "Reading=2,Completed=5,On Hold=7,Dropped=8,Plan to Read=9" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Apply read progress from CSV

If your CSV has a "last read chapter" column (Comick exports do), you can sync that into Suwayomi:

```powershell
seiyomi import csv `
  --file comick-mylist.csv `
  --apply-progress `
  --base-url http://127.0.0.1:4567
```

### Import multiple CSV files

```powershell
seiyomi import csv `
  --file comick-mylist.csv `
  --file manganato-bookmarks.csv `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Skip titles already in your library

```powershell
seiyomi import csv `
  --file comick-mylist.csv `
  --prefer-existing `
  --base-url http://127.0.0.1:4567
```

### Strict title matching

If you're getting false matches, tighten the threshold or use strict mode:

```powershell
# Raise threshold (0.6 is default, 1.0 is exact)
seiyomi import csv --file mylist.csv --threshold 0.8

# Or require near-exact matches only
seiyomi import csv --file mylist.csv --strict
```

See [CSV_IMPORT.md](CSV_IMPORT.md) for details on supported CSV formats and column schemas.

---

## 6. Library Migration

Migrate titles that have zero (or few) chapters to better alternatives from other installed sources.

### Migrate everything from a dead source

When a source shuts down (e.g. Bato.to), migrate all entries from that source to the best available alternatives:

```powershell
seiyomi migrate `
  --from "bato" `
  --to "mangabuddy,weeb central,mangapark" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

`--from` filters your library to only entries belonging to the named source (matched by name fragment). When `--from` is used, the chapter threshold is automatically raised so **all** entries from that source are considered, not just zero-chapter ones.

Combine with `--remove-old` to clean up the dead entries after migration:

```powershell
seiyomi migrate `
  --from "bato" `
  --to "mangabuddy,weeb central,mangapark" `
  --remove-old `
  --base-url http://127.0.0.1:4567
```

### How it works

1. Scans your Suwayomi library for entries below the chapter threshold (default: 1)
2. Searches each configured source for the same title
3. Scores candidates by chapter count (with language preference)
4. Adds the best match to your library
5. Optionally removes the original entry

### Basic migration (dry run)

```powershell
seiyomi migrate `
  --to "bato.to,mangabuddy,weeb central,mangapark" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Migrate and remove originals (destructive)

```powershell
seiyomi migrate `
  --to "bato.to,mangabuddy,weeb central" `
  --remove-old `
  --base-url http://127.0.0.1:4567
```

### Exclude specific sources

```powershell
seiyomi migrate `
  --to "bato.to,mangabuddy" `
  --exclude "comick,hitomi,mangakakalot" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Prefer English sources

```powershell
seiyomi migrate `
  --to "bato.to,mangabuddy,weeb central" `
  --lang en `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Only migrate entries with very few chapters

```powershell
seiyomi migrate `
  --to "bato.to,mangabuddy" `
  --threshold 5 `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Test on a single title first

```powershell
seiyomi migrate `
  --to "bato.to,mangabuddy" `
  --filter "Solo Leveling" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Interactive mode (pick the match yourself)

```powershell
seiyomi migrate `
  --to "bato.to,mangabuddy,weeb central" `
  --interactive `
  --base-url http://127.0.0.1:4567
```

In interactive mode, each match shows numbered candidates and you choose:
```
[12] 'The Beginning After the End' — 3 result(s) in 'bato.to':
  1. The Beginning After the End (180 ch) [id=12345] *
  2. Beginning After the End (175 ch) [id=12346]
  Choose [1-2 / s=skip / a=auto / q=quit]: _
```

### Resume an interrupted migration

If a migration was interrupted (network error, Ctrl+C), pick up where you left off:

```powershell
seiyomi migrate `
  --to "bato.to,mangabuddy" `
  --resume `
  --base-url http://127.0.0.1:4567
```

### Migration tips

- List preferred sources first (e.g. `bato.to` before `mangabuddy`). Ties are broken by list order.
- Use `--candidates 8` to consider more options per title (default: 5).
- Use `--timeout 30` if your sources are slow to respond (default: 20 seconds).
- Default excluded sources are `comick,hitomi`. Override with `--exclude`.
- Smart defaults are baked in: best-source scoring, canonical chapter counting, and second-page search are all on automatically.

---

## 7. Pruning

Clean up your library by removing entries that are duplicates or in the wrong language.

### Remove zero-chapter duplicates

When migration adds a better source, the old zero-chapter entry may still be in your library. This removes it:

```powershell
seiyomi prune duplicates `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

Only prune entries below a specific chapter count:

```powershell
seiyomi prune duplicates `
  --threshold 3 `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

Target a specific title:

```powershell
seiyomi prune duplicates `
  --filter "Solo Leveling" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Remove non-preferred language entries

Remove entries that only have chapters in languages you don't read:

```powershell
seiyomi prune languages `
  --lang "en,en-us" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

Only remove if the entry has fewer than N preferred-language chapters:

```powershell
seiyomi prune languages `
  --lang en `
  --min-chapters 3 `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

---

## 8. MangaDex Import

Import your MangaDex follows, statuses, and read progress into Suwayomi.

### Import follows only

```powershell
seiyomi import follows `
  --md-user YOUR_USER `
  --md-pass YOUR_PASS `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Import with status mapping

```powershell
seiyomi import follows `
  --md-user YOUR_USER `
  --md-pass YOUR_PASS `
  --import-status `
  --status-map "completed=5,reading=2,on_hold=7,dropped=8,plan_to_read=9" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Import with read chapter sync

```powershell
seiyomi import follows `
  --md-user YOUR_USER `
  --md-pass YOUR_PASS `
  --import-read `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Full import (follows + statuses + read progress)

```powershell
seiyomi import follows `
  --md-user YOUR_USER `
  --md-pass YOUR_PASS `
  --import-status `
  --import-read `
  --status-map "completed=5,reading=2,on_hold=7,dropped=8,plan_to_read=9" `
  --base-url http://127.0.0.1:4567
```

### Import specific IDs from a file

Create a text file with one MangaDex UUID or URL per line, then:

```powershell
seiyomi import ids manga_ids.txt `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

---

## 9. Read Progress Sync

Sync your MangaDex read chapter history into Suwayomi. This is part of `import follows` but can be run standalone:

```powershell
seiyomi sync reads `
  --md-user YOUR_USER `
  --md-pass YOUR_PASS `
  --only-if-ahead `
  --base-url http://127.0.0.1:4567
```

### How read sync works

1. Fetches your read chapter UUIDs from MangaDex
2. For MangaDex-source entries: matches by UUID directly
3. For migrated entries (other sources): falls back to chapter number matching
4. Marks matched chapters as read in Suwayomi

**`--only-if-ahead`** prevents regressions — chapters are only marked read if your MangaDex progress is ahead of Suwayomi.

---

## 10. Interactive Mode & Resume

### Interactive migration

When you want to review each match before it's committed:

```powershell
seiyomi migrate --to "bato.to,mangabuddy" -i --base-url http://127.0.0.1:4567
```

Each title shows numbered candidates. Enter a number to pick, `s` to skip, `a` for auto-pick, or `q` to quit.

### Resumable operations

Long migrations (50+ titles) write a checkpoint file. If the run is interrupted:

```powershell
seiyomi migrate --to "bato.to,mangabuddy" --resume --base-url http://127.0.0.1:4567
```

This skips entries that were already completed. The checkpoint is automatically deleted when the run finishes successfully.

---

## 11. Listing & Inspection

### List categories

```powershell
seiyomi list categories --base-url http://127.0.0.1:4567
# Output:
# 0: Default
# 2: Reading
# 5: Completed
# 7: On Hold
```

### List library

```powershell
seiyomi list library --base-url http://127.0.0.1:4567
# Output:
# 12345: Solo Leveling
# 12346: One Piece
# ...
```

Filter by title:

```powershell
seiyomi list library --filter "berserk" --base-url http://127.0.0.1:4567
```

### List installed sources

```powershell
seiyomi list sources --base-url http://127.0.0.1:4567
# Output:
# 1234567890: Bato.to
# 9876543210: MangaBuddy
# ...
```

---

## 12. GUI

Launch the graphical interface:

```powershell
seiyomi gui
```

Or directly:

```powershell
python gui_launcher_tk.py
```

The GUI provides tabbed access to all operations:

| Tab | What it does |
|-----|-------------|
| Home | Connection test and workflow cards |
| Migrate | Source migration with live output |
| Import CSV | CSV import with format auto-detection |
| Import MangaDex | Follows, statuses, and read sync |
| Cleanup | Prune duplicates and languages |
| Settings | Server URL, auth, presets |
| Advanced | Full flag access for power users |

All mutations run through the CLI as a subprocess — the GUI reads data from Suwayomi for display, but never modifies your library directly.

See [GUI_README.md](GUI_README.md) for the full GUI guide.

---

## 13. Categories & Status Mapping

### Finding your category IDs

```powershell
seiyomi list categories --base-url http://127.0.0.1:4567
```

### Mapping format

Use `status=category_id` pairs, comma-separated:

```
reading=2,completed=5,on_hold=7,dropped=8,plan_to_read=9
```

This works for both MangaDex status mapping (`import follows --status-map`) and CSV status mapping (`import csv --status-map`).

If a status appears in your data but isn't in the mapping, that entry is added to the library without a category assignment.

---

## 14. Title Matching

Seiyomi uses normalized title similarity to match entries across sources. This is especially important during migration and CSV import.

### How it works

1. Titles are lowercased and stripped of bracketed noise like `(Official)` or `[Color]`
2. Punctuation is removed, whitespace collapsed
3. Stop words (`the`, `a`, `of`, etc.) are dropped
4. Remaining tokens are compared using `rapidfuzz` (token sort ratio) or Jaccard similarity

### Tuning

- **`--threshold`** (default: `0.6`): minimum similarity score. Higher = fewer false matches but more misses.
- **`--strict`**: only accept exact or substring containment matches. Disables fuzzy matching entirely.

### When to tighten matching

- Sources return unrelated popular titles for specific searches → raise threshold to `0.8` or use `--strict`
- Getting false matches on short titles → use `--strict`
- Missing valid matches → lower threshold to `0.4`

---

## 15. Safety & Dry Runs

- **Non-destructive by default.** No entry is ever removed unless you explicitly pass `--remove-old` (migration) or use a prune command.
- **Always dry-run first.** Every command supports `--dry-run`. Use it on your first attempt, review the output, then re-run without it.
- **Destructive options in the GUI** are marked in red with "(destructive)" labels and trigger a confirmation dialog on first use.
- **Interrupted runs are safe.** Re-running a command is harmless — already-added entries are skipped or harmlessly re-added. Use `--resume` for migrations to skip completed entries efficiently.

---

## 16. Troubleshooting

| Problem | Solution |
|---------|----------|
| `seiyomi` command not found | Use `python -m seiyomi` instead, or activate your venv |
| Auth fails (401/403) | Try `--auth basic` or `--auth simple`; check Suwayomi server config |
| Migration finds few results | Add more sources to `--to`; increase `--candidates` and `--timeout` |
| Wrong title matched | Raise `--threshold` (try 0.8) or use `--strict` |
| Chapters not marking as read | Ensure GraphQL is enabled; increase delay between operations |
| "WARN no chapters loaded yet" | Open the title in Suwayomi UI to trigger chapter fetch, then retry |
| Slow performance | Use `--no-progress` to reduce output; the rate limiter runs automatically |
| CSV not recognized | Check that column headers match Comick or Manganato format; see [CSV_IMPORT.md](CSV_IMPORT.md) |

### Debug mode

Add `-v` (or `--verbose`) to any command for detailed debug output:

```powershell
seiyomi migrate --to "bato.to" -v --dry-run --base-url http://127.0.0.1:4567
```

---

## 17. Old Command Translation

If you used the old flat-flag interface, your commands still work. Seiyomi automatically translates them:

| Old syntax | New equivalent |
|------------|----------------|
| `python import_mangadex_bookmarks_to_suwayomi.py --migrate-library ...` | `seiyomi migrate ...` |
| `--prune-zero-duplicates` | `seiyomi prune duplicates` |
| `--prune-nonpreferred-langs` | `seiyomi prune languages` |
| `--from-follows` | `seiyomi import follows` |
| `--from-csv FILE` | `seiyomi import csv --file FILE` |
| `--list-categories` | `seiyomi list categories` |
| `--list-library-titles` | `seiyomi list library` |

A deprecation notice appears when the old format is detected. Update your scripts to the new subcommand form at your convenience.

### Flag name changes

| Old flag | New flag |
|----------|----------|
| `--md-username` | `--md-user` |
| `--md-password` | `--md-pass` |
| `--username` | `--user` |
| `--migrate-sources` | `--to` |
| `--exclude-sources` | `--exclude` |
| `--migrate-threshold-chapters` | `--threshold` |
| `--migrate-remove` | `--remove-old` |
| `--migrate-filter-title` | `--filter` |
| `--best-source-candidates` | `--candidates` |
| `--migrate-timeout` | `--timeout` |
| `--preferred-langs` | `--lang` |

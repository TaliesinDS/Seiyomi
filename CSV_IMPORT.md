# CSV Import Guide

Import your Comick or Manganato bookmarks into Suwayomi using the `seiyomi import csv` command.

---

## Quick Start

```powershell
seiyomi import csv --file comick-mylist-2025-09-23.csv --base-url http://127.0.0.1:4567 --dry-run
```

Remove `--dry-run` when you're satisfied with the output.

---

## Supported CSV Formats

The format is auto-detected from column headers. No `--csv-kind` flag is needed.

### Comick (`comick-mylist-YYYY-MM-DD.csv`)

Exported from Comick.io's MyList/bookmarks page.

| Column | Used for |
|--------|----------|
| `hid` | Comick internal ID |
| `title` | Primary title — used for Suwayomi source search |
| `type` | Reading status (e.g. `Reading`, `Completed`) — mapped via `--status-map` |
| `read` | Last-read chapter number — used by `--apply-progress` |
| `last_read` | Timestamp of last read (informational) |
| `synonyms` | Alternate titles (comma-separated) — used as fallback for matching |
| `mal` | MyAnimeList URL — ID extracted for future matching |
| `anilist` | AniList URL — ID extracted for future matching |
| `mangaupdates` | MangaUpdates URL |

### Manganato (`manganato.gg_bookmarks.csv`)

Exported from Manganato's bookmarks page.

| Column | Used for |
|--------|----------|
| `title` | Title string — used for search |
| `url` | Manganato URL |
| `viewed` | Last read chapter hint — used by `--apply-progress` |

Custom column names can be mapped with `--csv-col-map` if your export differs.

---

## Command Reference

```powershell
seiyomi import csv --file PATH [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--file PATH` | required | CSV file to import (repeat for multiple files) |
| `--threshold N` | `0.6` | Title match similarity 0–1 |
| `--strict` | off | Require near-exact matches only |
| `--status-map MAP` | | Map status to category: `Reading=2,Completed=5` |
| `--apply-progress` | off | Mark chapters read up to CSV last-read hint |
| `--prefer-existing` | off | Skip rows when title already in library |
| `--dry-run` | off | Simulate without changes |
| `-v` | off | Verbose debug output |

---

## Examples

### Basic Comick import

```powershell
seiyomi import csv `
  --file comick-mylist-2025-09-23.csv `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### With status mapping

First, find your Suwayomi category IDs:

```powershell
seiyomi list categories --base-url http://127.0.0.1:4567
# 2: Reading, 5: Completed, 7: On Hold, 8: Dropped, 9: Plan to Read
```

Then:

```powershell
seiyomi import csv `
  --file comick-mylist.csv `
  --status-map "Reading=2,Completed=5,On Hold=7,Dropped=8,Plan to Read=9" `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### With read progress

```powershell
seiyomi import csv `
  --file comick-mylist.csv `
  --apply-progress `
  --base-url http://127.0.0.1:4567
```

### Manganato bookmarks

```powershell
seiyomi import csv `
  --file manganato.gg_bookmarks.csv `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Multiple files at once

```powershell
seiyomi import csv `
  --file comick.csv `
  --file manganato.csv `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Strict matching (fewer false positives)

```powershell
seiyomi import csv `
  --file comick.csv `
  --strict `
  --base-url http://127.0.0.1:4567 `
  --dry-run
```

### Skip titles already in library

```powershell
seiyomi import csv `
  --file comick.csv `
  --prefer-existing `
  --base-url http://127.0.0.1:4567
```

---

## How Matching Works

1. Each CSV row's title is normalized (lowercased, punctuation stripped, stop words removed)
2. The title is searched against your installed Suwayomi sources
3. Results are scored by title similarity (using `rapidfuzz` if installed, Jaccard otherwise)
4. The best match above the threshold is added to your library
5. If `--status-map` is set and the CSV has a status column, the entry is placed in the matching category
6. If `--apply-progress` is set and the CSV has a last-read column, chapters up to that number are marked read

### Tuning matches

- **Too many false matches:** raise `--threshold` (try `0.8`) or use `--strict`
- **Too many misses:** lower `--threshold` (try `0.4`)
- **Short titles matching wrong things:** use `--strict`

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| Empty `last_read` or `0000:00:00` | Ignored — no progress applied |
| Multiple matches above threshold | Best chapter count wins; preferred-language entries preferred |
| Non-numeric `last_read` (e.g. "Chapter 50.5") | Best-effort float extraction; skipped if unparsable |
| Title already in library | Skipped if `--prefer-existing`; otherwise matched and reported |
| Duplicate rows in CSV | Deduplicated by normalized title |

---

## Fractional Chapter Rules

When applying read progress, fractional chapters (e.g. 50.1, 50.5) follow these rules:

- `.1–.4` are **canonical** (count toward progress)
- `.5` is canonical **only if** other split parts exist for that base chapter (`.1–.4` or `.6+`); isolated `.5` is treated as extra
- `.6+` are canonical when present
- Titles containing "extra", "omake", "special", or "side story" are always excluded from progress

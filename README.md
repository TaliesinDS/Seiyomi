# Seiyomi — Suwayomi Library Manager

<div align="center">

<img src="assets/icon_256.png" alt="Seiyomi icon (整)" width="128" height="128" />

**Import, migrate, and clean up your Suwayomi manga library.**

</div>

---

## What It Does

- **Import** — add manga from CSV exports (Comick, Manganato) or MangaDex follows
- **Migrate** — find better sources for zero/low-chapter entries across all installed Suwayomi extensions
- **Prune** — remove duplicate entries and non-preferred-language variants
- **List** — inspect your library, categories, and installed sources
- **Sync** — mirror MangaDex read progress into Suwayomi (including cross-source by chapter number)

All operations are non-destructive by default. Use `--dry-run` to preview any command before committing.

---

## Requirements

| What | Version |
|------|---------|
| Python | 3.10+ |
| Suwayomi server | Running and reachable (default `http://127.0.0.1:4567`) |
| OS | Windows 10/11 (tested), macOS/Linux (should work) |

Optional: `rapidfuzz` (installed by default) for faster title matching. Falls back to Jaccard similarity if absent.

---

## Install

```powershell
git clone https://github.com/yourusername/Seiyomi.git
cd Seiyomi
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

Verify:

```powershell
python -m seiyomi --help
```

---

## Quick Start

### List your Suwayomi categories

```powershell
seiyomi list categories --base-url http://127.0.0.1:4567
```

### Import a Comick CSV export (dry run first)

```powershell
seiyomi import csv --file comick-mylist-2025-09-23.csv --base-url http://127.0.0.1:4567 --dry-run
```

### Migrate zero-chapter entries to better sources

```powershell
seiyomi migrate --to "bato.to,mangabuddy,weeb central" --base-url http://127.0.0.1:4567 --dry-run
```

### Remove duplicate entries

```powershell
seiyomi prune duplicates --base-url http://127.0.0.1:4567 --dry-run
```

### Launch the GUI

```powershell
seiyomi gui
```

Remove `--dry-run` from any command when you're satisfied with the preview.

> **Tip:** `python -m seiyomi` works the same as `seiyomi` if the package isn't installed system-wide.

---

## CLI Reference

### Shared flags (all commands)

| Flag | Default | Description |
|------|---------|-------------|
| `--base-url URL` | `http://127.0.0.1:4567` | Suwayomi server address |
| `--auth MODE` | `auto` | Auth: `none`, `basic`, `bearer`, `simple`, `auto` |
| `--user USER` | | Username for basic/simple auth |
| `--password PASS` | | Password |
| `--token TOKEN` | | Bearer token |
| `--dry-run` | off | Simulate without making changes |
| `-v, --verbose` | off | Show debug output |
| `--no-progress` | off | Suppress per-item progress lines |

---

### `seiyomi migrate`

Find better sources for library entries that have zero or few chapters.

```powershell
seiyomi migrate [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--to SOURCES` | | Preferred target sources (comma-separated fragments, e.g. `"bato.to,mangabuddy"`) |
| `--exclude SOURCES` | `comick,hitomi` | Skip these sources during search |
| `--lang LANGS` | `en` | Preferred language codes (comma-separated) |
| `--threshold N` | `1` | Only migrate entries with fewer than N chapters |
| `--remove-old` | off | Remove original after successful migration (destructive) |
| `--candidates N` | `5` | Max candidates to score per title |
| `--filter TEXT` | | Only process titles containing this substring |
| `--timeout SECS` | `20` | Max seconds per title |
| `--interactive, -i` | off | Prompt before each migration |
| `--resume` | off | Continue from where a previous run was interrupted |

Smart defaults are baked in: best-source scoring, canonical chapter counting, and second-page search are all enabled automatically.

**Examples:**

```powershell
# Interactive migration to English sources
seiyomi migrate --to "bato.to,mangabuddy,weeb central" --lang en -i

# Resume an interrupted run
seiyomi migrate --to "mangapark,weeb central" --resume

# Migrate and remove originals
seiyomi migrate --to "bato.to" --remove-old
```

---

### `seiyomi import csv`

Import manga from a CSV export file (Comick, Manganato, or custom format).

```powershell
seiyomi import csv --file PATH [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--file PATH` | required | CSV file path (repeatable: `--file a.csv --file b.csv`) |
| `--threshold N` | `0.6` | Title match threshold 0–1 |
| `--strict` | off | Require near-exact title match only |
| `--status-map MAP` | | Map CSV status to category: `Reading=2,Completed=5` |
| `--apply-progress` | off | Mark chapters read up to CSV last-read hint |
| `--prefer-existing` | off | Skip rows when title already exists in library |

CSV format is auto-detected by column headers. See [CSV_IMPORT.md](CSV_IMPORT.md) for schema details.

**Examples:**

```powershell
# Import with status mapping
seiyomi import csv --file comick.csv --status-map "Reading=2,Completed=5"

# Strict matching, skip duplicates
seiyomi import csv --file manganato.csv --strict --prefer-existing --dry-run
```

---

### `seiyomi import follows`

Import your MangaDex followed manga into Suwayomi.

```powershell
seiyomi import follows --md-user USER --md-pass PASS [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--md-user USER` | | MangaDex username |
| `--md-pass PASS` | | MangaDex password |
| `--import-status` | off | Map MangaDex statuses to Suwayomi categories |
| `--import-read` | off | Sync MangaDex read progress |
| `--status-map MAP` | | Status→category mapping: `reading=2,completed=5` |

---

### `seiyomi import ids`

Import specific MangaDex manga from a text file (one ID or URL per line).

```powershell
seiyomi import ids FILE [options]
```

---

### `seiyomi prune duplicates`

Remove library entries with zero chapters when a better copy of the same title exists.

```powershell
seiyomi prune duplicates [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--threshold N` | `0` | Remove entries with fewer than N chapters |
| `--filter TEXT` | | Only consider titles matching this substring |

---

### `seiyomi prune languages`

Remove entries that have no chapters in your preferred language.

```powershell
seiyomi prune languages [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--lang LANGS` | `en` | Languages to keep (comma-separated) |
| `--min-chapters N` | `1` | Min preferred-language chapters required |
| `--filter TEXT` | | Only consider titles matching this substring |

---

### `seiyomi list`

```powershell
seiyomi list categories                   # Show category IDs and names
seiyomi list library                      # Print all library entries (id: title)
seiyomi list library --filter "berserk"   # Filter by substring
seiyomi list sources                      # Show installed source extensions
```

---

### `seiyomi sync reads`

Sync MangaDex read progress into Suwayomi.

```powershell
seiyomi sync reads --md-user USER --md-pass PASS [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--only-if-ahead` | off | Only mark chapters when MangaDex is ahead of Suwayomi |

---

### `seiyomi gui`

Launch the graphical interface. See [GUI_README.md](GUI_README.md).

---

## Backward Compatibility

Old flat-flag commands still work automatically:

| Old syntax | New equivalent |
|------------|----------------|
| `--migrate-library` | `migrate` |
| `--prune-zero-duplicates` | `prune duplicates` |
| `--prune-nonpreferred-langs` | `prune languages` |
| `--list-categories` | `list categories` |
| `--list-library-titles` | `list library` |
| `--from-follows` | `import follows` |
| `--from-csv FILE` | `import csv --file FILE` |

A deprecation notice is logged when the old format is detected. Update your scripts at your convenience.

---

## GUI

The GUI provides the same operations through a tabbed interface:

| Tab | What it does |
|-----|-------------|
| Home | Connection status and quick-start workflow cards |
| Migrate | Source migration with live output |
| Import CSV | CSV file import with format auto-detection |
| Import MangaDex | Follows, statuses, and read chapter sync |
| Cleanup | Prune duplicates and language variants |
| Settings | Connection config, auth mode, presets |
| Advanced | Full flag access for power users |

All mutations run through the CLI subprocess — the GUI never modifies your library directly.

See [GUI_README.md](GUI_README.md) for the full guide.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Auth fails | Try `--auth basic` or `--auth simple` |
| Migration finds few results | Increase `--candidates` and `--timeout`; add more sources to `--to` |
| Wrong title matched | Lower `--threshold` or use `--strict` |
| Chapters not marking as read | Ensure GraphQL is enabled on your server |
| `--dry-run` looks good but real run fails | Check connectivity; use `-v` for debug output |

---

## Project Structure

```
seiyomi/
├── cli.py              # Subcommand entry point
├── config.py           # Config dataclasses
├── compat.py           # Old-flag translation layer
├── clients/
│   ├── suwayomi.py     # Suwayomi REST/GraphQL client
│   └── mangadex.py     # MangaDex API client
├── importers/
│   └── csv_import.py   # CSV parsing (Comick, Manganato, custom)
├── matching/
│   └── titles.py       # Title similarity (rapidfuzz / Jaccard fallback)
├── operations/
│   ├── migrate.py      # Library migration
│   ├── prune.py        # Duplicate & language pruning
│   ├── read_sync.py    # Read-progress sync
│   ├── import_csv.py   # CSV import operation
│   ├── import_follows.py
│   └── rehome.py
├── utils/
│   ├── rate_limiter.py # Thread-safe rate limiter
│   └── checkpoint.py   # Resumable operation state
└── gui/                # Tkinter GUI
```

---

## Safety

- **Non-destructive by default.** No entry is removed unless you explicitly pass `--remove-old` or similar.
- **Always dry-run first.** Every command supports `--dry-run`.
- Destructive options in the GUI are marked in red.

---

## Web UI Userscripts

See `userscripts/README.md` for a Tampermonkey script that adds "Sort by Publish Date" to the Suwayomi web UI.

---

## Why "Seiyomi"?

Seiyomi (整読み) = 整 (sei, "organize") + 読み (yomi, "reading"). Following the tradition of Tachiyomi (立ち読み, "stand and read") and Suwayomi (座り読み, "sit and read").

---

## License

MIT. Respect site policies and support manga authors and artists.

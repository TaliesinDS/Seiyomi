# Seiyomi GUI Guide

The Seiyomi GUI is a Tkinter desktop interface that wraps the CLI. Every operation runs as a CLI subprocess — the GUI never modifies your Suwayomi library directly.

---

## Launching

```powershell
# Via subcommand
seiyomi gui

# Or directly
python gui_launcher_tk.py

# Or with venv
.venv\Scripts\python.exe gui_launcher_tk.py
```

---

## Tabs

### Home

Landing screen with workflow summary cards. Shows connection status and quick links to common tasks.

### Import CSV

Import manga from Comick or Manganato CSV exports.

- **File picker** — select one or more CSV files
- **Status map** — map CSV status columns to Suwayomi category IDs (e.g. `Reading=2,Completed=5`)
- **Threshold** — title match similarity (default 0.6)
- **Strict** — require near-exact title matches only
- **Apply progress** — mark chapters read up to the CSV's last-read hint
- **Prefer existing** — skip rows when the title is already in your library

### Import Follows (MangaDex)

Import your MangaDex followed manga.

- **MangaDex credentials** — username and password
- **Import statuses** — map MangaDex reading statuses to Suwayomi categories
- **Import read chapters** — sync your MangaDex read progress
- **Status map** — `reading=2,completed=5,on_hold=7,...`

### Migrate Library

Find better sources for zero/low-chapter entries.

- **Target sources** — comma-separated source name fragments (e.g. `bato.to,mangabuddy`)
- **Exclude sources** — skip these (default: `comick,hitomi`)
- **Language** — preferred language codes (default: `en`)
- **Threshold** — only migrate entries with fewer than N chapters
- **Remove old** — delete the original entry after migration (destructive, marked in red)
- **Interactive** — prompt before each migration commit
- **Resume** — continue from a previous interrupted run

### Prune Library (Cleanup)

Remove unwanted entries.

- **Prune duplicates** — remove entries with zero chapters when a better copy exists
- **Prune languages** — remove entries with no chapters in your preferred language
- **Filter** — target a specific title by substring match

### Settings

- **Server URL** — Suwayomi base URL (default: `http://127.0.0.1:4567`)
- **Auth mode** — none, basic, bearer, simple, auto
- **Credentials** — username, password, or bearer token
- **Test connection** — verify connectivity before running operations

### Advanced

Full CLI argument builder for power users. Type any combination of flags and the GUI builds the command for you. This is the escape hatch for flags not exposed in the other tabs.

---

## Controls

The bottom bar is shared across all tabs:

| Control | What it does |
|---------|-------------|
| **Dry Run** | Toggle to simulate without making changes |
| **Run** | Execute the current operation |
| **Cancel** | Stop a running operation (sends SIGTERM) |
| **Output panel** | Shows live CLI output as lines stream in |

---

## Destructive Actions

- Marked in **red** with "(destructive)" label
- First use triggers a confirmation dialog with "Don't show again" option
- Reset confirmations by deleting the config file (see below)

---

## Config Location

Settings are stored in:

- Windows: `%APPDATA%\Seiyomi\config.json`
- macOS/Linux: `~/.config/Seiyomi/config.json`

On first launch, if an old `MangaDex_Suwayomi` config directory is found, settings are automatically migrated.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Commands don't run | Check server URL and auth in Settings tab |
| No output appears | Make sure your venv is activated; check Python is 3.10+ |
| Markdown doesn't render | Install `markdown` and `tkhtmlview` (`pip install markdown tkhtmlview`) |
| Connection test fails | Verify Suwayomi is running and the URL is correct |

Use **Dry Run** first. Enable `-v` (verbose) in Advanced tab for debug output.

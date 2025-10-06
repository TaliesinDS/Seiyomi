# Seiyomi GUI — Quick Guide

This is a short guide for the desktop GUI that ships with Seiyomi. For the full project documentation, see `README.md` and `USER_MANUAL.md`.

---

## What the GUI does

- Import from MangaDex (follows, statuses, read chapters, custom lists)
- Migrate within your Suwayomi library (rehoming and best-source picking)
- Prune duplicates and non‑preferred languages
- Run general Suwayomi utilities (auth, list categories, open UI)

All options generate an exact command in the Command Preview so you can run the same task from the CLI later.

---

## Launching

- With Python:

```powershell
.\.venv\Scripts\python.exe .\gui_launcher_tk.py
```

- Packaged EXE (if present): `MangaDex_Suwayomi_ControlPanel.exe`

---

## Tabs at a glance

- MangaDex Import: log in and pull follows/statuses/read markers
- CSV Import: add Comick/Manganato CSV files, set per-file options, and everything auto-matches directly against Suwayomi sources (MangaDex lookup is always skipped)
- Migrate: add better sources for thin/zero‑chapter entries; title matching and language preferences supported
	- Tip: list a few high-quality sites in “Preferred sources” (and optionally enable “Preferred only”) so migrations stay focused and skip the long tail of low-quality mirrors.
- Prune: clean duplicates and non‑preferred‑language entries
- Suwayomi Database: base URL, auth, list categories, open UI
- Settings: presets and debug output
- About: app info, links, environment details

Each tab has a “Help” button to open the relevant section in the user manual.

---

## Command Preview & Run

- The bottom panel shows the exact command that will run
- Toggle `Dry run` to simulate without changing your library
- `Save log to file` tees the output to a chosen path
- By default, runs quietly without opening a PowerShell window
- Check `Open in external terminal` to watch live output in a PowerShell window

---

## Presets

- Prefer English Migration
- Cleanup Non‑English
- Keep Both (Quality+Coverage)

Use Settings → Apply Preset to quickly prime common workflows.

---

## Title Matching (for migration & rehoming)

- `Similarity threshold (0..1)`: minimum score (default 0.6)
- `Strict` mode: accept only normalized exact/containment matches

These settings are used when Migrate or Rehoming is enabled.

---

## About panel

- Shows version, license, author, environment
- Buttons to open: GUI README (viewer), full README, Manual, Project Folder, LICENSE, Repository

---

## Troubleshooting

- If commands don’t run, check Base URL and auth in Suwayomi Database tab
- Use `Dry run` first; enable `Debug output` (Settings) for verbose logs
- If markdown doesn’t render in viewers, ensure `markdown` and `tkhtmlview` are installed (bundled via `requirements.txt`)

---

## Safety & Defaults

- Non-destructive by default: migration keeps the original entry unless you explicitly enable removal.
- Destructive actions are labeled “(destructive)” in red throughout the GUI.
- When a destructive action is enabled, a confirmation dialog appears (once) with an option to “Don’t show again”.

---

## System Requirements

- Windows 10/11 (official support; packaged EXE available)
- Suwayomi server reachable (e.g., `http://127.0.0.1:4567`)
- Either Python 3.11+ (to run the script) or the packaged EXE
- Markdown viewer uses `markdown` + `tkhtmlview` (included via `requirements.txt`/EXE)
- macOS/Linux: works with Python 3.11+ and Tkinter; the optional `Open in external terminal` feature requires PowerShell 7 (`pwsh`), otherwise run quietly and use logs

---

## Settings & Data

- Config: `%APPDATA%\MangaDex_Suwayomi\config.json`
- Reset config: close the app and delete that file
- Logs: when “Save log to file” is enabled, output is written to the chosen path

---

## Privacy & Security

- Credentials/tokens are used only to talk to Suwayomi/MangaDex and aren’t stored
- Logs may include titles/URLs but never passwords—review before sharing

---

## Extra Troubleshooting

- Windows SmartScreen: packaged EXE is unsigned; click “More info → Run anyway” (or build locally)
- Markdown not rendering: toggle “Rendered Markdown” off in the viewer if needed
- Networking: if requests time out, raise “Request timeout (s)” or add a small `Throttle` in the Suwayomi Database tab
- Collect info for issues: use About → “Copy Environment Info”, include Command Preview + last 50 log lines

---

## Support / Issues

- Open an issue: https://github.com/TaliesinDS/Seiyomi/issues
- Please attach: the Command Preview command, last ~50 lines of the log, and the About environment string

---

## What’s New (GUI)

- In‑app Markdown viewer for Manual/README with dark mode and search
- Title Matching controls for migration/rehoming (threshold, strict)
- About tab shows version/license/author and has quick links (GUI README, Manual, Repo, LICENSE)

---

## Known Limitations

- Windows‑first UI; portable mode not supported (config stored in AppData)
- Markdown renderer is simple; complex HTML/CSS may not render perfectly
- Opening external files uses your OS default app (e.g., VS Code if set for `.md`)

MIT License. Respect site policies and support authors/artists.

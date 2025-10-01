# Seiyomi — MangaDex → Suwayomi Import & Library Tools (Beginner Friendly Guide)

This guide shows you how to move ("import") your MangaDex followed manga, reading statuses, and read chapter progress into a Suwayomi (Tachidesk) server **even if you have never used the command line before**.

For a feature overview and quick-start summary, see the README in this repository.

---

> **Heads-up:** The refactored command-line entry point is `import_mangadex_bookmarks_to_suwayomi_refactored.py`. If you are still running the legacy `import_mangadex_bookmarks_to_suwayomi.py`, the arguments are identical—just swap the filename in the examples below.

## 1. What This Tool Does

It can:

- Add every manga you follow on MangaDex into your Suwayomi library
- (Optional) Put each manga into categories based on your MangaDex reading status (Reading, Completed, Dropped, etc.)
- (Optional) Mark chapters as read in Suwayomi to match what you have already read on MangaDex
- (Optional) Use a local bookmarks/list file instead of live follows (txt/csv/xlsx/json/html)
- Migrate entries already in your Suwayomi library to alternative sources (e.g., MangaPark, Weeb Central) when the original source has 0 or very few chapters

### CSV Bookmark Imports (Comick / Manganato)

- Open the new **CSV Import** tab in the GUI to add one or more bookmarks CSV exports alongside MangaDex data. Use **Add...** to load files and the check-box to enable or disable the batch.
- Optional controls let you override column names (`--csv-col-map`), map CSV reading statuses to Suwayomi categories (`--csv-status-to-category`), adjust title matching (`--csv-title-threshold`, `--csv-title-strict`), prefer existing library copies (`--csv-prefer-existing`), and apply per-title read hints from the CSV (`--csv-apply-read-progress`).
- The GUI mirrors the CLI flags: each CSV file results in a `--from-csv <path>` argument. Kind detection matches automatically, but you can force `comick` or `manganato` via the drop-down (`--csv-kind`). Separate multiple column overrides with semicolons or newlines (each becomes its own `--csv-col-map` argument).
- CSV progress hints target the Suwayomi library both for newly added entries and ones you already have; skipped rows report to the console so you can adjust mappings if needed.

It does **not**:

- Create categories automatically (please create them in Suwayomi first and note their numeric IDs)
- Recover chapters that have been DMCA removed or delisted from MangaDex
- Sync continuously (this is a one‑time or occasional run tool)

Notes about connections/authentication:

- The tool talks to your Suwayomi server using its REST API and, if needed, GraphQL
- If your server requires authentication for the endpoints this tool needs, pass `--username/--password` or `--token`; otherwise you can leave auth out

---

## Safety & Defaults

- Non‑destructive by default: migration keeps the original entry unless you explicitly enable removal
- Destructive actions are labeled “(destructive)” in red throughout the GUI
- The first time you enable a destructive action, a confirmation dialog appears with a “Don’t show again” option (re‑enable by deleting `%APPDATA%\MangaDex_Suwayomi\config.json`)



## 2. Prerequisites (What You Need First)
## 3. Chapter Read Sync (MangaDex → Suwayomi)

This tool can import your MangaDex read progress into Suwayomi in two ways:

1) Direct UUID match (recommended when the entry is from the MangaDex source)
- `--import-read-chapters`: fetch the list of read chapter UUIDs from MangaDex and mark the same UUIDs as read in Suwayomi.
- Works only when the Suwayomi entry is the MangaDex source (UUIDs exist on that entry).

2) Cross‑source by chapter number (for migrated titles)
- `--read-sync-number-fallback`: when UUIDs don’t match (e.g., title migrated to a different source), match by chapter number instead.
- `--read-sync-across-sources`: apply the read marks to same‑title entries under other sources (normalized title match).
- `--read-sync-only-if-ahead`: only mark if your MangaDex progress is ahead of the current read position of the target entry.

Supporting options
- `--read-sync-delay <sec>`: wait after adding a manga before syncing reads to give Suwayomi time to fetch chapters.
- `--max-read-requests-per-minute <n>`: rate limit chapter mark calls.
- `--missing-report <path.csv>`: write a CSV listing titles with missing read chapters or where chapters weren’t loaded yet (recorded as `unknown`). The file is created immediately with a header and updated live as the run progresses.

Fractional chapter rules (canonical counting)
- `.1–.4` are canonical (count toward progress and inclusion).
- `.5` is canonical only if other split parts exist for that base chapter (.1–.4 or .6+); isolated `.5` is treated as extra and excluded from progress.
- `.6+` are canonical when present.
- Title hints like “extra”, “omake”, “special”, “side story” cause exclusion even when the number looks canonical.

Examples

Import reads on MangaDex source entries only (UUID match):
```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --from-follows `
   --md-username USER `
   --md-password PASS `
   --import-read-chapters `
   --read-sync-delay 2 `
   --max-read-requests-per-minute 240
```

Import and apply by number across sources (only when ahead), write live missing report:
```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --from-follows `
   --md-username USER `
   --md-password PASS `
   --import-read-chapters `
   --read-sync-number-fallback `
   --read-sync-across-sources `
   --read-sync-only-if-ahead `
   --read-sync-delay 2 `
   --max-read-requests-per-minute 240 `
   --missing-report .\reports\md_missing_reads.csv
```
> Cross-source syncing is opt-in. Include `--read-sync-across-sources` (and usually `--read-sync-number-fallback`) when you want chapter progress mirrored onto other sources.

Quiet read-sync (no extra logging)

```powershell
# Sync all follows quietly
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --from-follows `
   --md-username USER `
   --md-password PASS `
   --no-add-library `
   --import-read-chapters `
   --read-sync-number-fallback `
   --read-sync-across-sources `
   --max-read-requests-per-minute 240 `
   --no-progress

# Or: sync a list of specific IDs (one per line)
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   .\ids.txt `
   --md-login-only `
   --md-username USER `
   --md-password PASS `
   --no-add-library `
   --import-read-chapters `
   --read-sync-number-fallback `
   --read-sync-across-sources `
   --max-read-requests-per-minute 240 `
   --no-progress
```

Implementation note

- Read flags are applied using GraphQL mutations (`updateChapters` and `updateChapter`), matching the Suwayomi WebUI behavior.
- REST write endpoints may return 404 on some builds; this is expected. Ensure your auth mode permits GraphQL write operations.

Troubleshooting
- “WARN no chapters loaded yet …”: the tool records `unknown` to the CSV; raise `--read-sync-delay` (e.g., 3–5 s) and rerun or open the title in the Suwayomi UI to force chapter fetch.
- Missing rows don’t appear during the run: ensure the CSV isn’t open in Excel (file lock). Use `Get-Content .\reports\md_missing_reads.csv -Wait` to tail the file.
- Cross‑source matching is by normalized title; if a title was renamed substantially, consider syncing UUIDs on the MangaDex entry once to establish progress.


| Item | Why You Need It | How to Get It |
|------|-----------------|---------------|
| Windows 10/11 (official) or macOS/Linux with Python | Runs the tool/GUI | Windows EXE available; on macOS/Linux run with Python 3.11+ and Tkinter |
| Python (version 3.11 or newer recommended) | Runs the script/GUI | [Download Python](https://www.python.org/downloads/) (check "Add python.exe to PATH" during install) |
| Suwayomi (Tachidesk) server running | Destination library | Start your server (default often `http://localhost:4567`) |
| MangaDex account credentials | To fetch your follows & read markers | Use your normal username and password |
| Categories in Suwayomi (optional) | For mapping statuses | Create them in Suwayomi UI first |

### How to Check Python Installed

1. Press the Windows key.
2. Type: `cmd` and press Enter.
3. In the black window type: `python --version` and press Enter. (On macOS/Linux, use Terminal.)
   - If you see something like: `Python 3.12.0` you’re good.
   - If you get an error, install Python (make sure to tick **Add to PATH** during installation).

---

## 3. Download / Place the Files

1. Put the script files (`import_mangadex_bookmarks_to_suwayomi_refactored.py`, `run_importer.bat`, and this `USER_MANUAL.md`) together in a folder. If you keep the legacy `import_mangadex_bookmarks_to_suwayomi.py`, store it alongside the new file so existing shortcuts continue to work. For example: `C:\MangaDexImport`.
2. (Optional) Create a shortcut to `run_importer.bat` on your Desktop so you can double‑click it.
---

## 4. Quick Start (Easiest Path)

1. Double‑click `run_importer.bat` (on Windows). On macOS/Linux, see the Python command examples below.
2. When asked for the **Suwayomi base URL**, type: `http://localhost:4567` (change if yours differs) and press Enter.
3. For **Fetch all MangaDex follows?** press Enter to accept `Y`.
4. Enter your **MangaDex username**.
5. Enter your **MangaDex password** (it will be visible while typing—batch files cannot hide input easily). You can change your password later if concerned.
6. For **Import reading statuses** press Enter to accept `Y`.
7. When prompted for a **status map**, you can paste something like:
   `completed=5,reading=2,on_hold=7,dropped=8,plan_to_read=9`
   (Only include the statuses you actually want. Make sure those category IDs exist in Suwayomi.)
8. For **Import chapter read markers?** answer `Y` if you want your read chapter progress imported, else `N`.
9. If you said `Y`, set a delay (1 second is safe) so the server can load chapters before they are marked.
10. (Optional) Enter a single category id to force everything into it as well (e.g. a general "Imported" category). Leave blank to skip.
11. Accept the default to do a **Dry run** first (`Y`).
12. Wait—dry run shows what *would* be added (no changes yet).
13. At the end it will ask if you want to run again without dry-run. Press `Y` to perform the real import.

---

## 4.0 Common Scenarios (Copy/Paste)

These are ready-to-use commands for the most common tasks. Replace the base URL if your server isn’t on the default.

1. Upgrade zero‑chapter items by adding a better source (keep originals)

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-threshold-chapters 1 `
   --migrate-sources "bato.to,mangabuddy,weeb central,mangapark" `
   --migrate-title-threshold 0.7 `
   --migrate-preferred-only `
   --best-source `
   --best-source-canonical `
   --best-source-candidates 4 `
   --min-chapters-per-alt 5 `
   --migrate-max-sources-per-site 3 `
   --migrate-timeout 25
```

1. Remove zero‑chapter duplicates if the full/partial duplicate already exists

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-threshold-chapters 1 `
   --migrate-sources "bato.to,mangabuddy" `
   --migrate-preferred-only `
   --best-source `
   --best-source-canonical `
   --best-source-candidates 4 `
   --min-chapters-per-alt 5 `
   --migrate-max-sources-per-site 3 `
   --migrate-timeout 25 `
   --migrate-remove-if-duplicate
```

1. Do both at once: add the better source, then remove the zero‑chapter original

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-threshold-chapters 1 `
   --migrate-sources "bato.to,mangabuddy,weeb central,mangapark" `
   --migrate-title-threshold 0.7 `
   --migrate-preferred-only `
   --best-source `
   --best-source-canonical `
   --best-source-candidates 4 `
   --min-chapters-per-alt 5 `
   --migrate-max-sources-per-site 3 `
   --migrate-timeout 25 `
   --migrate-remove
```

1. Hard prune (no searching): keep the best entry per title, remove the rest with 0 chapters

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --prune-zero-duplicates `
   --prune-threshold-chapters 1 `
   --dry-run
```

Tip: Remove `--dry-run` to actually delete. Add `--prune-filter-title "substring"` to target one series.

1. Prefer English when migrating (avoid other languages where possible)

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-threshold-chapters 1 `
   --migrate-sources "bato.to,mangabuddy,weeb central,mangapark" `
   --migrate-title-threshold 0.7 `
   --migrate-preferred-only `
   --best-source `
   --best-source-canonical `
   --preferred-langs "en,en-us" `
   --lang-fallback `
   --migrate-remove
```

This scores candidates by English chapters first; if a site has zero English chapters, it will fall back to total chapters only if `--lang-fallback` is present.

1. Keep both: prefer quality source but also keep the one with most chapters for coverage

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-threshold-chapters 1 `
   --migrate-sources "bato.to,mangabuddy,weeb central,mangapark" `
   --migrate-preferred-only `
   --best-source `
   --best-source-global `
   --best-source-canonical `
   --preferred-langs "en,en-us" `
   --lang-fallback `
   --prefer-sources "asura,flame,genz,utoons" `
   --prefer-boost 3 `
   --migrate-keep-both `
   --migrate-remove
```

This picks the best candidate by language + quality bias and also adds the raw max‑chapters candidate when it’s a different site, so you can read early chapters on the higher‑quality source and switch to the fuller source later.

1. Keep originals instead of removing them (optional)

By default, all examples remove the original zero/low‑chapter entry after adding the alternative. To keep your original entries, add `--no-migrate-remove`:

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-threshold-chapters 1 `
   --migrate-sources "bato.to,mangabuddy" `
   --migrate-preferred-only `
   --best-source `
   --best-source-canonical `
   --preferred-langs "en,en-us" `
   --lang-fallback `
   --no-migrate-remove `
   --dry-run
```

Important:

- The examples in this manual default to removal. If you don’t want that behavior, copy the snippet above and keep the `--no-migrate-remove` flag.
- You can always do a dry run first and remove `--dry-run` when you’re satisfied with the output.

1. Cleanup: remove non-English variants when an English one exists (no searching)

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --prune-nonpreferred-langs `
   --preferred-langs "en,en-us" `
   --prune-filter-title "Solo Leveling: Ragnarok" `
   --dry-run
```

Then re-run without `--dry-run` to actually delete the non-English duplicates.

To convert 0-chapter entries into English sources in one go: first migrate with language preference, then remove the zero-chapter originals:

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-threshold-chapters 1 `
   --migrate-sources "bato.to,mangabuddy,weeb central,mangapark" `
   --migrate-preferred-only `
   --best-source `
   --best-source-canonical `
   --preferred-langs "en,en-us" `
   --lang-fallback `
   --migrate-remove
```

1. Test on a single title first (recommended)

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-filter-title "Shinimodori Level Up" `
   --dry-run
```

Notes:

- Put your preferred site first (e.g., `bato.to`), fallback second (e.g., `mangabuddy`).
- Keep `--best-source-canonical` on so split/alt releases are counted together.
- To avoid wrong matches from certain sources, tune `--migrate-title-threshold` (0..1, default 0.6) or enforce `--migrate-title-strict`.
- Use `--migrate-remove-if-duplicate` if you want to only remove the zero‑chapter one when a duplicate already exists.
- --migrate-remove is ON by default in these examples (the script default). Use `--no-migrate-remove` if you prefer to keep the original after adding the alternative (optional).
- Add `--exclude-sources "comick,hitomi"` if you don’t want those mirrors.
- For a search-free cleanup, use the hard prune command above; it keeps the title variant with the most chapters and removes other zero-chapter variants.
- Only migrate specific categories: add `--migrate-include-categories "Reading,On Hold"` or by id `--migrate-include-categories "5,7"`. To skip categories instead use `--migrate-exclude-categories`.
- Favor likely-original scanlator sources by boosting their score: `--prefer-sources "asura,flame,genz,utoons" --prefer-boost 3`.
- Keep both when needed: add `--migrate-keep-both` with `--best-source-global` to save both quality and coverage variants.

### Title Matching (How it chooses the right result)

Some source sites return popular/new lists even when you search a specific title. Seiyomi filters candidates before picking a source using normalized title similarity:

- `--migrate-title-threshold <0..1>` Require a minimum similarity (default `0.6`). Higher = stricter.
- `--migrate-title-strict` Only accept normalized exact/containment matches (disables fuzzy-only matches).

Quick examples:

```powershell
# Stricter than default (fewer false positives)
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-title-threshold 0.75 `
   --dry-run
```

```powershell
# Near-exact matches only (best when a source is noisy)
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-title-strict `
   --dry-run
```

Basic dry run:

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --dry-run
```

## 5.0 Graphical Control Panel (optional)

Two ways to use the GUI:

- Quick run (requires Python):

```powershell
python .\gui_launcher_tk.py
```

- Standalone EXE (no Python required):

```powershell
# Build once (produces EXEs in .\dist)
.\build_exe.ps1 -Clean
# Launch the GUI
.\dist\MangaDex_Suwayomi_ControlPanel.exe
```

Notes:

- The GUI is free and open-source (Tkinter, part of Python stdlib).
- Press the “?” button in the top-right to open this manual.
- Presets are included for common tasks (Prefer English Migration, Cleanup Non-English, Keep Both).

Apply changes (remove `--dry-run`), and optionally delete the original entry when an alternative is added:

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-threshold-chapters 1 `
   --migrate-sources "weeb central,mangapark" `
   --migrate-remove
```

Avoid zero‑chapter duplicates when a full/partial duplicate already exists:

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-threshold-chapters 1 `
   --migrate-sources "bato.to,mangabuddy,weeb central,mangapark" `
   --migrate-preferred-only `
   --best-source `
   --best-source-canonical `
   --best-source-candidates 4 `
   --min-chapters-per-alt 5 `
   --exclude-sources "comick,hitomi" `
   --migrate-max-sources-per-site 3 `
   --migrate-timeout 25 `
   --migrate-remove-if-duplicate
```

Focus on one title while testing:

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --migrate-library `
   --migrate-filter-title "Shinimodori Level Up" `
   --dry-run
```

Notes:

- The tool discovers your library through GraphQL (categories first) and deduplicates across categories.
- Chapter count is computed from available endpoints; if chapter endpoints need auth on your server, the tool will fall back to GraphQL and best-effort counting.
- You can add `--debug-library` to print which endpoints and GraphQL fields were used.
- Default excluded sources: `--exclude-sources "comick,hitomi"`. Adjust if you want to exclude more.
- Put your preferred site first (e.g., `bato.to`) and the fallback next (e.g., `mangabuddy`). If two sites tie on chapters, earlier site wins.
- Keep `--best-source-canonical` on so split/alt releases count correctly.
- Limit per-site work with `--migrate-max-sources-per-site 3`; use `--migrate-try-second-page` only if a site often hides results on page 2.

---

## 5. Understanding Categories & Status Mapping

If you want statuses to map to categories, first create categories inside Suwayomi (e.g. Reading, Completed, Dropped, On Hold, Plan to Read). Each category has a numeric ID. You can usually find IDs by inspecting the UI or API; if you’re unsure, temporarily add one manga to a category and look at network calls, or keep a small note of ID order.

Example mapping string:

```text
completed=5,reading=2,on_hold=7,dropped=8,plan_to_read=9
```

If a status appears for a manga but is not in the map, that manga just won’t get a status category (unless a default category is added later).

---

## 6. Chapter Read Markers

When enabled, the script tries to:

1. Fetch which chapters you have read on MangaDex.
2. Ask Suwayomi for the list of chapters for that manga.
3. Match by internal MangaDex chapter ID hidden inside the source’s URL/key.
4. Mark them as read (unless you used `--read-chapters-dry-run`).

If you see warnings like `WARN no chapters loaded yet`, run the script again later with only the chapter sync enabled:

```text
run_importer.bat (answer only: base URL, follows Y, user/pass, chapter markers Y, delay 0, dry-run N)
```

The second pass usually catches stragglers.

Chapters that are DMCA removed or deleted cannot be re-marked—they simply don’t exist for the source anymore.

---

## 7. Safety Tips

| Situation | Recommendation |
|-----------|---------------|
| Large libraries (1000+) | Use a dry run first to spot obvious failures. |
| Slow or rate limit errors | Add a throttle (`--throttle 0.1`) or keep the 1-second read-sync delay. |
| Password safety | Change your MangaDex password after import if you typed it in and are worried about someone seeing it. |
| Interrupted run | Just re-run; already added manga will typically be skipped or harmlessly re-added. |
| Many "not found" failures | The manga may be delisted, or title matching needs improvement; rerun later or manually add. |

---

## 8. Advanced Users (Direct Python Command Examples)

Run directly (dry run):

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://localhost:4567 `
   --from-follows `
   --md-username YOURUSER `
   --md-password YOURPASS `
   --follows-json mangadex_follows.json `
   --import-reading-status `
   --status-category-map completed=5,reading=2,on_hold=7,dropped=8,plan_to_read=9 `
   --import-read-chapters `
   --read-sync-delay 1 `
   --dry-run
```

Real run (remove `--dry-run`).

Minimal just to import follows:

```powershell
python import_mangadex_bookmarks_to_suwayomi.py --base-url http://localhost:4567 --from-follows --md-username USER --md-password PASS
```

Only chapter sync (after everything already added):

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://localhost:4567 `
   --from-follows `
   --md-username USER `
   --md-password PASS `
   --import-read-chapters `
   --read-sync-delay 0
```

Diagnostics pagination (if counts look off):

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://localhost:4567 `
   --from-follows `
   --md-username USER `
   --md-password PASS `
   --debug-follows `
   --dry-run `
   --no-progress
```

---

## 8.1 Useful Utilities

- List categories (get IDs you can map to):

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --list-categories
```

- Import MangaDex custom lists and map by list name (optional):

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --from-follows `
   --md-username USER `
   --md-password PASS `
   --import-lists `
   --lists-category-map "Dropped=7,On Hold=5,Plan to Read=8,Completed=9,Reading=4"
```

- Verify specific MangaDex IDs are in scope (after filters):

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --from-follows `
   --md-username USER `
   --md-password PASS `
   --verify-id 123e4567-e89b-12d3-a456-426614174000 `
   --verify-id 765e4321-e89b-12d3-a456-426614174111 `
   --dry-run
```

- Export statuses you fetched to a JSON file (for auditing):

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://127.0.0.1:4567 `
   --from-follows `
   --md-username USER `
   --md-password PASS `
   --import-reading-status `
   --export-statuses statuses.json
```

---

## 8.2 Diagnostic Flags

- `--debug-login` Show MangaDex login flow details (never prints your password).
- `--debug-follows` Show MangaDex follows pagination.
- `--debug-status` Print a sample of fetched statuses.
- `--status-endpoint-raw` Dump raw JSON from the MangaDex status endpoint(s).
- `--status-map-debug` Explain status->category mapping decisions.
- `--debug-library` Show Suwayomi library/chapters endpoint attempts and GraphQL choices.

---

## 8.3 Flag Reference (Quick)

- Core: `--base-url`, `--dry-run`, `--no-progress`, `--throttle`, `--category-id`, `--no-title-fallback`
- Suwayomi auth (only if needed): `--auth-mode auto|basic|simple|bearer`, `--username`, `--password`, `--token`, `--insecure`
- MangaDex auth: `--md-username`, `--md-password`, `--md-client-id`, `--md-client-secret`, `--md-2fa`
- Follows: `--from-follows`, `--follows-json`, `--max-follows`, `--debug-follows`
- Reading status: `--import-reading-status`, `--status-category-map`, `--status-default-category`, `--assume-missing-status`, `--ignore-statuses`, `--print-status-summary`, `--debug-status`, `--status-endpoint-raw`, `--status-fallback-single`, `--status-fallback-throttle`, `--export-statuses`, `--include-library-statuses`, `--library-statuses-only`
- Chapter progress: `--import-read-chapters`, `--read-chapters-dry-run`, `--read-sync-delay`, `--max-read-requests-per-minute`
- Lists: `--import-lists`, `--list-lists`, `--lists-category-map`, `--lists-ignore`, `--debug-lists`
- Migration/Rehoming (existing library): `--migrate-library`, `--migrate-threshold-chapters`, `--migrate-sources`, `--migrate-remove`, `--migrate-remove-if-duplicate`, `--migrate-filter-title`, `--migrate-max-sources-per-site`, `--migrate-try-second-page`, `--migrate-timeout`, `--best-source`, `--best-source-global`, `--best-source-candidates`, `--best-source-canonical`, `--min-chapters-per-alt`, `--debug-library`
- Title matching (Migration & Rehoming): `--migrate-title-threshold`, `--migrate-title-strict`
- Migration filtering: `--migrate-include-categories`, `--migrate-exclude-categories`
- Prune (no searching): `--prune-zero-duplicates`, `--prune-threshold-chapters`, `--prune-filter-title`
- Language cleanup: `--prune-nonpreferred-langs`, `--prune-lang-threshold`
- Language preference: `--preferred-langs`, `--lang-fallback`
- Rehoming during import (optional path used when MangaDex has 0 chapters): `--rehoming-enabled`, `--rehoming-sources`, `--rehoming-skip-if-chapters-ge`, `--rehoming-remove-mangadex`

Tip: When using PowerShell, line continuation is the backtick (`). In cmd.exe use ^ instead, or put the whole command on one line.

---

## 8.4 Flag Glossary (Plain English)

Short, non-technical explanations of the most-used flags. Use the examples first; check this list only when you’re curious what a flag means.

- --base-url: Where your Suwayomi server is. On your own PC: <http://127.0.0.1:4567>
- --dry-run: Test only. Shows what would happen—no changes made.
- --no-progress: Make the output quieter (fewer lines printed).
- --throttle N: Wait N seconds between items (helps slow servers).
- --category-id N: Also add each imported manga to category N (optional).
- --no-title-fallback: Don’t try searching by title if searching by ID fails.

Suwayomi login (only if needed)

- --auth-mode: How to log in (auto is fine). Options: auto, basic, simple, bearer
- --username / --password: Your Suwayomi sign-in
- --token: A Suwayomi API token (alternative to user/pass)
- --insecure: Skip HTTPS checks (only for trusted/local setups)

MangaDex login (for getting your follows / read markers)

- --md-username / --md-password: Your MangaDex sign-in
- --md-client-id / --md-client-secret: Advanced keys (usually not needed)
- --md-2fa: Your 2FA code, if you have two-factor enabled

Follows input

- --from-follows: Fetch your followed manga directly from MangaDex
- --follows-json FILE: Use a saved file instead of live MangaDex
- --max-follows N: Only process the first N follows (good for testing)
- --debug-follows: Show detailed loading steps (for troubleshooting)

Reading status mapping (optional)

- --import-reading-status: Put manga into categories that match your MD status
- --status-category-map: Tell the tool which category equals which status (e.g., reading=2)
- --status-default-category N: If a status isn’t mapped, put it in category N
- --assume-missing-status NAME: If missing, pretend the status is NAME (e.g., reading)
- --ignore-statuses LIST: Don’t apply statuses for these (e.g., dropped,on_hold)
- --print-status-summary: Print a short count of statuses found
- --status-endpoint-raw / --debug-status: Extra detail to debug status fetching
- --status-fallback-single / --status-fallback-throttle: Advanced, slower fallback
- --export-statuses FILE: Save fetched statuses to a file for your records
- --include-library-statuses / --library-statuses-only: Include or limit to what’s already in Suwayomi

Chapter progress (optional)

- --import-read-chapters: Mark chapters as read to match MangaDex
- --read-chapters-dry-run: Test chapter marking without saving
- --read-sync-delay N: Wait N seconds so chapters load before marking
- --max-read-requests-per-minute N: Slow down to avoid overloading the server

Lists (optional)

- --import-lists: Import your MangaDex custom lists
- --list-lists: Show your list names
- --lists-category-map: Put items from a given list into a specific category
- --lists-ignore: Skip certain list names
- --debug-lists: Print details while loading lists

Migration/Rehoming (fix 0- or low-chapter entries already in Suwayomi)

- --migrate-library: Scan your current Suwayomi library to add a better source
- --migrate-threshold-chapters N: Only migrate items with fewer than N chapters (1 = only zero-chapter)
- --migrate-sources "A,B,C": Sites to try, in order of preference (earlier wins ties)
- --migrate-preferred-only: Only try the sites you listed
- --exclude-sources "X,Y": Never use sites whose names include these
- --best-source: On each site, pick the candidate with the most chapters
- --best-source-canonical: Count split/alt releases together when comparing
- --best-source-global: Compare across all sites (slower but thorough)
- --best-source-candidates N: Only inspect the first N results per site
- --min-chapters-per-alt N: Require at least N chapters to consider a candidate
- --migrate-max-sources-per-site N: Only try N candidates per site (faster)
- --migrate-try-second-page: Also check page 2 (use only if needed; slower)
- --migrate-timeout N: Give up on a single title after N seconds (keeps run going)
- --migrate-filter-title "text": Only process titles containing this text (great for testing)
- --migrate-title-threshold N.N: Only accept candidates whose normalized title similarity meets N.N (0..1, default 0.6)
- --migrate-title-strict: Require normalized exact/containment matches; disables purely fuzzy matches
- --migrate-include-categories "A,B" or "1,2": Only migrate items in these categories (names or numeric IDs)
- --migrate-exclude-categories "A,B" or "1,2": Skip items in these categories (names or numeric IDs)
- --migrate-remove: After adding a good alternative, delete the original entry
- --migrate-remove-if-duplicate: If the chosen alternative already exists in your library and has chapters, delete the zero/low-chapter original instead of adding another copy
- --debug-library: Show searches and candidate scores for troubleshooting

Language preference (scoring)

- --preferred-langs "A,B,C": Comma-separated language codes to prefer when counting chapters (e.g., en,en-us,id). Matches exact or base (en matches en-us).
- --lang-fallback: If a candidate has zero chapters in preferred languages, allow scoring by total chapters as a fallback.

Rehoming during import (advanced, optional)

- --rehoming-enabled: While importing a MangaDex item with 0 chapters, also try a preferred site
- --rehoming-sources "A,B,C": Which sites to try for rehoming
- --rehoming-skip-if-chapters-ge N: Skip if MangaDex already has at least N chapters
- --rehoming-remove-mangadex: If rehoming worked, remove the MangaDex entry

---

Prune-only (no searching)

- --prune-zero-duplicates: Remove zero/low-chapter entries when another entry with the same title has chapters.
- --prune-threshold-chapters N: Consider entries with >= N chapters as the “keepers” (default 1). Others get removed.
- --prune-filter-title "text": Only act on titles containing this text.
- --prune-nonpreferred-langs: Remove entries whose chapters do not match preferred languages when a same-title entry has preferred-language chapters.
- --prune-lang-threshold N: Minimum preferred-language chapters to treat an entry as keepable (default 1).

## 9. Troubleshooting

| Problem | What You See | Fix |
|---------|--------------|-----|
| Wrong credentials | HTTP 401 / login failed | Re-enter username/password carefully (case-sensitive). |
| Script seems stuck early | No per-item lines yet | It’s still fetching follows; try with `--debug-follows`. |
| Many "WARN no chapters loaded yet" | Chapter sync too early | Re-run only chapter sync later with zero delay. |
| Count mismatch vs MangaDex | WARNING collected X < reported total Y | Update to latest script (pagination fix). |
| Lots of "not found" | Title fallback failing | Manga may be delisted; retry later or manual add. |
| Chapter read markers low | Marked far fewer than expected | Run another chapter-only pass after allowing caching. |
| Batch file closes instantly | Python not installed / crash | Open `cmd`, `cd` to folder, run same command to read the error. |

---

## 10. FAQ

**Q: Will this overwrite anything?**  
No—worst case it re-calls add-to-library on a series already added (harmless).

**Q: Can I stop and resume?**  
Yes. Just run again; already imported series are fine. Read markers will be re-applied to any newly loaded chapters.

**Q: Do I have to share my password?**  
It stays local on your computer. Change it afterward if you’re uneasy.

**Q: Can I map multiple statuses to one category?**  
Yes—just set the same category id for each status in the map.

**Q: How do I find category IDs?**  
Easiest: run the tool with `--list-categories`:

```powershell
python import_mangadex_bookmarks_to_suwayomi.py `
   --base-url http://localhost:4567 `
   --list-categories
```

This prints something like:

```text
Available Categories:
   1: Default
   5: Reading
   7: On Hold
   8: Dropped
   9: Plan to Read
```

Use those numeric IDs in your `--status-category-map`. If that fails, ensure you can access the server and that categories exist.

> NOTE: The PowerShell backtick (`) is the line continuation character in PowerShell. If you are using the older Command Prompt (cmd.exe) instead, replace each backtick with a caret (^) or put the whole command on one line.

---

## 11. Next Improvements (Planned / Optional)

- Session token login (`--md-session`).
- Retry pass for manga whose chapters weren’t loaded in time.
- Export a report file summarizing per-manga chapter sync results.
- GUI wrapper (.exe) version for completely click‑based use.

If you need any of these sooner, ask and they can be added.

---

## 12. Getting Help

If something still doesn’t work:

1. Take a screenshot or copy the last 10 lines of the console (hide your password!).
2. Note the command you ran (again, hide password).
3. Share those details with the maintainer / issue tracker.

---

**You’re done!** Enjoy having your MangaDex library and progress inside Suwayomi.

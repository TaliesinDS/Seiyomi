# Read Ledger — Implementation Plan

## Problem

Suwayomi tracks read progress per manga entry, but entries are keyed by
source-specific IDs.  When an extension dies or you migrate to a new source the
read state becomes orphaned — chapters are still marked `isRead=true` in the DB
but there is no way to automatically transfer that to the replacement entry.
With 3 500+ library entries and frequent source churn this means constantly
losing track of what you've read.

Suwayomi's built-in tracker integration (MAL, AniList, MangaUpdates) requires
**manually binding each title** through the web UI, which is impractical at
scale.

## Solution: Local Read Ledger

A lightweight SQLite database owned by seiyomi that acts as the **single source
of truth** for "which chapter of each title have I read up to?".  It syncs
bidirectionally with Suwayomi and optionally pushes/pulls progress to
MyAnimeList and MangaUpdates.

```
┌───────────────┐      snapshot       ┌──────────────┐
│   Suwayomi    │ ──────────────────► │              │
│ (3500 entries │                     │  Read Ledger │
│  + orphans)   │ ◄────────────────── │  (SQLite)    │
└───────────────┘      apply          │              │
                                      └──────┬───────┘
                                       push │ │ pull
                                      ┌─────▼─┴──────┐
                                      │  MAL / MU     │
                                      │  (optional)   │
                                      └───────────────┘
```

---

## Schema

### `titles` — Canonical title registry

| Column            | Type     | Description                                          |
|-------------------|----------|------------------------------------------------------|
| `id`              | INTEGER  | Auto-increment primary key                           |
| `normalized_key`  | TEXT     | Lowercased token-joined key (unique, indexed)        |
| `display_title`   | TEXT     | Best human-readable title seen                       |
| `mal_id`          | INTEGER  | MyAnimeList manga ID (nullable)                      |
| `mu_id`           | INTEGER  | MangaUpdates series ID (nullable)                    |
| `created_at`      | TEXT     | ISO-8601 timestamp                                   |
| `updated_at`      | TEXT     | ISO-8601 timestamp                                   |

### `alt_titles` — Alternative names for the same title

| Column     | Type    | Description                                 |
|------------|---------|---------------------------------------------|
| `id`       | INTEGER | Auto-increment primary key                  |
| `title_id` | INTEGER | FK → `titles.id`                            |
| `alt_name` | TEXT    | Alternative title string                    |
| `source`   | TEXT    | Where this name came from (suwayomi/mal/mu) |

### `read_progress` — The core ledger

| Column              | Type    | Description                                          |
|---------------------|---------|------------------------------------------------------|
| `id`                | INTEGER | Auto-increment primary key                           |
| `title_id`          | INTEGER | FK → `titles.id`                                     |
| `max_chapter`       | REAL    | Highest chapter number confirmed read                |
| `max_volume`        | INTEGER | Highest volume number (for MAL/MU, nullable)         |
| `status`            | TEXT    | reading / completed / on_hold / dropped / plan_to_read |
| `last_synced_suwa`  | TEXT    | Last time synced from/to Suwayomi                    |
| `last_synced_mal`   | TEXT    | Last time synced to/from MAL                         |
| `last_synced_mu`    | TEXT    | Last time synced to/from MangaUpdates                |
| `updated_at`        | TEXT    | ISO-8601 timestamp                                   |

### `suwayomi_entries` — Maps Suwayomi manga IDs to ledger titles

| Column           | Type    | Description                                 |
|------------------|---------|---------------------------------------------|
| `id`             | INTEGER | Auto-increment primary key                  |
| `title_id`       | INTEGER | FK → `titles.id`                            |
| `suwayomi_id`    | INTEGER | Suwayomi manga internal ID                  |
| `source_id`      | TEXT    | Suwayomi source ID string                   |
| `source_name`    | TEXT    | Human-readable source name                  |
| `in_library`     | INTEGER | 1 = currently in library, 0 = orphaned      |
| `chapter_count`  | INTEGER | Last known chapter count from this source    |

---

## CLI Commands

All under `seiyomi ledger`:

### `seiyomi ledger snapshot`
Scan Suwayomi library + orphaned entries, update the ledger with the highest
chapter read per title.  Creates new title entries as needed.

```
seiyomi ledger snapshot [--include-orphans] [--base-url ...] [--auth ...]
```

- Fetches library via GQL
- Fetches orphaned manga IDs (entries with read chapters not in library)
- For each manga: get chapters, find `max(chapterNumber where isRead)`
- Group by normalized title
- Upsert into `titles` + `read_progress` (only raises, never lowers)
- Upserts into `suwayomi_entries`
- Upserts any new title strings into `alt_titles`

### `seiyomi ledger apply`
Push ledger progress to Suwayomi library entries that are behind.

```
seiyomi ledger apply [--dry-run] [--filter TITLE] [--base-url ...] [--auth ...]
```

- For each current library entry: look up normalized title in ledger
- If ledger `max_chapter` > entry's current progress → mark chapters read
- Uses GQL `updateChapter` mutation (no more 404 spam)
- Respects `--dry-run`

### `seiyomi ledger auto`
Shorthand: runs `snapshot` then `apply`.

```
seiyomi ledger auto [--dry-run] [--base-url ...] [--auth ...]
```

### `seiyomi ledger show [TITLE]`
Display ledger entries.  Without argument, shows summary stats.  With a title
substring, shows matching entries and their progress.

```
seiyomi ledger show "defense game"
```

### `seiyomi ledger export`
Export the ledger to CSV for backup/inspection.

```
seiyomi ledger export [--output ledger.csv]
```

### `seiyomi ledger push mal`
Push read progress to MyAnimeList for all titles that have a `mal_id`.

```
seiyomi ledger push mal [--dry-run] [--resolve-ids]
```

- `--resolve-ids` searches MAL API to find `mal_id` for titles that don't have
  one yet (rate-limited)

### `seiyomi ledger pull mal`
Pull read progress from MyAnimeList into the ledger (raises only).

```
seiyomi ledger pull mal
```

### `seiyomi ledger push mu`
Push to MangaUpdates for titles with `mu_id`.

```
seiyomi ledger push mu [--dry-run] [--resolve-ids]
```

### `seiyomi ledger pull mu`
Pull from MangaUpdates into the ledger.

```
seiyomi ledger pull mu
```

---

## Implementation Phases

### Phase L1 — SQLite core + snapshot + apply

**Files:**

| File                                | Purpose                              |
|-------------------------------------|--------------------------------------|
| `seiyomi/ledger/db.py`             | SQLite connection, schema, migrations |
| `seiyomi/ledger/models.py`         | Dataclasses for title, progress      |
| `seiyomi/ledger/snapshot.py`       | Suwayomi → ledger                    |
| `seiyomi/ledger/apply.py`          | Ledger → Suwayomi                    |
| `seiyomi/ledger/__init__.py`       | Package init                         |
| `tests/test_ledger_db.py`          | Schema + CRUD tests                  |
| `tests/test_ledger_snapshot.py`    | Snapshot logic tests                 |
| `tests/test_ledger_apply.py`       | Apply logic tests                    |

**Config:**

- DB location: `~/.seiyomi/read_ledger.db` (or `--ledger-db PATH`)
- Schema auto-created on first use
- All writes inside transactions

**Dependencies:** None (stdlib `sqlite3`).

**What this replaces:** `sync reads-across` becomes a thin wrapper around
`ledger auto` — snapshot from donors, apply to recipients.

### Phase L2 — MyAnimeList sync

**Files:**

| File                                | Purpose                              |
|-------------------------------------|--------------------------------------|
| `seiyomi/clients/mal.py`           | MAL API v2 client (OAuth2 PKCE)      |
| `seiyomi/ledger/sync_mal.py`       | push/pull logic                      |
| `tests/test_mal_client.py`         | MAL client tests                     |
| `tests/test_ledger_mal.py`         | MAL sync tests                       |

**MAL API v2 endpoints:**

| Action              | Endpoint                                    | Method |
|---------------------|---------------------------------------------|--------|
| Search manga        | `/v2/manga?q={title}&fields=...`            | GET    |
| Get manga detail    | `/v2/manga/{id}?fields=...`                 | GET    |
| Get user manga list | `/v2/users/@me/mangalist?fields=...`        | GET    |
| Update list entry   | `/v2/manga/{id}/my_list_status`             | PATCH  |

**Auth:** OAuth2 with PKCE (no client secret needed for public clients).
MAL requires a registered application; the user provides their Client ID.
Token stored in `~/.seiyomi/mal_token.json`.  Refresh handled automatically.

**ID resolution:** For titles without `mal_id`:
1. Search MAL API with display title → pick best match by title similarity
2. User can confirm/reject via `--interactive` flag
3. Confirmed IDs stored in `titles.mal_id`
4. Rate limit: 1 req/sec (MAL enforced)

**Push logic:**
1. For each ledger entry with `mal_id`:
   - PATCH `/v2/manga/{mal_id}/my_list_status` with
     `num_chapters_read`, `status`
   - Only push if ledger is ahead of MAL
2. ~1 request per title (batching not supported by MAL API)

**Pull logic:**
1. Paginate `/v2/users/@me/mangalist` (100 per page)
2. For each entry: match to ledger by `mal_id`
3. If MAL `num_chapters_read` > ledger `max_chapter` → update ledger

### Phase L3 — MangaUpdates sync

**Files:**

| File                                | Purpose                              |
|-------------------------------------|--------------------------------------|
| `seiyomi/clients/mangaupdates.py`  | MU API v1 client (session token)     |
| `seiyomi/ledger/sync_mu.py`        | push/pull logic                      |
| `tests/test_mu_client.py`          | MU client tests                      |
| `tests/test_ledger_mu.py`          | MU sync tests                        |

**MangaUpdates API v1 endpoints:**

| Action            | Endpoint                          | Method |
|-------------------|-----------------------------------|--------|
| Login             | `/v1/account/login`               | PUT    |
| Refresh           | `/v1/account/refresh`             | PUT    |
| Search series     | `/v1/series/search`               | POST   |
| Get series detail | `/v1/series/{id}`                 | GET    |
| Get user lists    | `/v1/lists/series`                | POST   |
| Add to list       | `/v1/lists/series`                | POST   |
| Update list entry | `/v1/lists/series/update`         | POST   |
| Delete from list  | `/v1/lists/series/delete`         | POST   |

**Auth:** Username/password → session token + refresh cookie.  Already
implemented in `scripts/mangaupdates_list.py` — extract and reuse.

**ID resolution:** MU's search API is quite good for manga titles.
1. POST `/v1/series/search` with `{ "search": title }`
2. Pick best match by title similarity
3. Store in `titles.mu_id`

**Push/Pull logic:** Same pattern as MAL — compare chapter numbers, only raise.
MU uses list IDs: Reading=0, Complete=2, On Hold=4, Dropped=3.

**Batch support:** MU allows up to 25 series per batch add — leverage this.

### Phase L4 — Quality-of-life

- **Auto-link at import time:** When `seiyomi import csv` or `seiyomi migrate`
  adds a new entry, automatically check the ledger and apply progress
- **Comick ID cross-reference:** Comick CSVs contain `mal_url` and `mu_url`
  columns — use these to pre-populate `mal_id` and `mu_id` during CSV import
- **`seiyomi ledger resolve`:** Batch-resolve missing MAL/MU IDs via API search
  with interactive confirmation
- **`seiyomi ledger merge`:** Manually merge two ledger entries that are the
  same title (e.g. different translations)

---

## DB Location & Portability

| Platform | Default path                             |
|----------|------------------------------------------|
| Windows  | `%USERPROFILE%\.seiyomi\read_ledger.db`  |
| Linux    | `~/.seiyomi/read_ledger.db`              |
| macOS    | `~/.seiyomi/read_ledger.db`              |

Overridable with `--ledger-db /path/to/file.db` or env var `SEIYOMI_LEDGER_DB`.

The DB is a single portable file — back it up, copy between machines, check
into a private repo.

---

## Interaction with Existing Features

| Feature                | Before ledger                          | After ledger                                  |
|------------------------|----------------------------------------|-----------------------------------------------|
| `sync reads-across`    | Scans library + orphans in-memory      | `ledger auto` does the same, persists result  |
| `migrate --sync-reads` | Copies read from old→new entry inline  | Also writes to ledger as side-effect          |
| `import csv`           | No read progress                       | Checks ledger, applies if known title         |
| Extension dies         | Progress lost unless orphan still in DB | Ledger has it permanently                     |
| New source added       | Manual `sync reads-across` needed      | `ledger apply` catches it automatically       |

---

## Rate Limits & Safety

| Service       | Rate limit             | Our approach                        |
|---------------|------------------------|-------------------------------------|
| Suwayomi GQL  | Local, no limit        | Batch mutations where possible      |
| MAL API v2    | ~1 req/sec enforced    | 1.2s delay between requests         |
| MangaUpdates  | ~300 req/min           | 0.5s delay, 25-item batches         |

All external syncs respect `--dry-run`.  Push operations only **raise** progress
(never lower, never delete).  The ledger itself uses WAL mode for safe
concurrent reads.

---

## Phase Priority

| Phase | Effort   | Value | Notes                                    |
|-------|----------|-------|------------------------------------------|
| L1    | Medium   | High  | Core value — survives extension churn     |
| L2    | Medium   | Med   | MAL coverage is weak for webtoons/manhwa  |
| L3    | Medium   | High  | MU has best coverage for your library     |
| L4    | Low each | Med   | Quality-of-life, can add incrementally    |

**Recommended order:** L1 → L3 → L2 → L4

MangaUpdates first because it has far better coverage of Korean/Chinese
webtoons than MAL (which is anime-focused).  Your MU account is already
connected and the API client is partially written in `scripts/mangaupdates_list.py`.

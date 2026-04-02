"""SQLite database layer for the read ledger.

Schema is auto-created on first use.  All writes are transactional.
The DB file defaults to ``~/.seiyomi/read_ledger.db`` but can be overridden
via the ``SEIYOMI_LEDGER_DB`` env var or ``--ledger-db`` CLI flag.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from seiyomi.ledger.models import AltTitle, LedgerTitle, ReadProgress, SuwayomiEntry

logger = logging.getLogger("seiyomi.ledger.db")

_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS titles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    normalized_key  TEXT    NOT NULL UNIQUE,
    display_title   TEXT    NOT NULL,
    mal_id          INTEGER,
    mu_id           INTEGER,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS alt_titles (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    title_id  INTEGER NOT NULL REFERENCES titles(id),
    alt_name  TEXT    NOT NULL,
    source    TEXT    NOT NULL DEFAULT 'suwayomi'
);
CREATE INDEX IF NOT EXISTS idx_alt_titles_title_id ON alt_titles(title_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alt_titles_unique ON alt_titles(title_id, alt_name);

CREATE TABLE IF NOT EXISTS read_progress (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title_id         INTEGER NOT NULL UNIQUE REFERENCES titles(id),
    max_chapter      REAL    NOT NULL DEFAULT 0.0,
    max_volume       INTEGER,
    status           TEXT    NOT NULL DEFAULT 'reading',
    last_synced_suwa TEXT    NOT NULL DEFAULT '',
    last_synced_mal  TEXT    NOT NULL DEFAULT '',
    last_synced_mu   TEXT    NOT NULL DEFAULT '',
    updated_at       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS suwayomi_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title_id      INTEGER NOT NULL REFERENCES titles(id),
    suwayomi_id   INTEGER NOT NULL UNIQUE,
    source_id     TEXT    NOT NULL DEFAULT '',
    source_name   TEXT    NOT NULL DEFAULT '',
    in_library    INTEGER NOT NULL DEFAULT 1,
    chapter_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_suwa_entries_title ON suwayomi_entries(title_id);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _default_db_path() -> Path:
    env = os.environ.get("SEIYOMI_LEDGER_DB")
    if env:
        return Path(env)
    return Path.home() / ".seiyomi" / "read_ledger.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LedgerDB:
    """Thin wrapper around a SQLite connection for the read ledger."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cur.fetchone() is None:
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.execute("INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
            self._conn.commit()
            logger.info("Ledger DB created at %s (schema v%d)", self.db_path, _SCHEMA_VERSION)
        else:
            # Ensure metadata table exists (added after initial schema)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── Title CRUD ────────────────────────────────────────────────────────

    def get_title_by_key(self, normalized_key: str) -> Optional[LedgerTitle]:
        row = self._conn.execute(
            "SELECT * FROM titles WHERE normalized_key = ?", (normalized_key,)
        ).fetchone()
        return _row_to_title(row) if row else None

    def get_title_by_id(self, title_id: int) -> Optional[LedgerTitle]:
        row = self._conn.execute(
            "SELECT * FROM titles WHERE id = ?", (title_id,)
        ).fetchone()
        return _row_to_title(row) if row else None

    def upsert_title(self, normalized_key: str, display_title: str,
                     mal_id: Optional[int] = None, mu_id: Optional[int] = None) -> int:
        """Insert or update a title row.  Returns the title id."""
        now = _now_iso()
        existing = self.get_title_by_key(normalized_key)
        if existing:
            # Update display_title if the new one is longer (more complete)
            new_display = display_title if len(display_title) > len(existing.display_title) else existing.display_title
            new_mal = mal_id if mal_id else existing.mal_id
            new_mu = mu_id if mu_id else existing.mu_id
            self._conn.execute(
                "UPDATE titles SET display_title=?, mal_id=?, mu_id=?, updated_at=? WHERE id=?",
                (new_display, new_mal, new_mu, now, existing.id),
            )
            self._conn.commit()
            return existing.id
        self._conn.execute(
            "INSERT INTO titles (normalized_key, display_title, mal_id, mu_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (normalized_key, display_title, mal_id, mu_id, now, now),
        )
        self._conn.commit()
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def all_titles(self) -> List[LedgerTitle]:
        rows = self._conn.execute("SELECT * FROM titles ORDER BY display_title").fetchall()
        return [_row_to_title(r) for r in rows]

    # ── Alt titles ────────────────────────────────────────────────────────

    def add_alt_title(self, title_id: int, alt_name: str, source: str = "suwayomi") -> None:
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO alt_titles (title_id, alt_name, source) VALUES (?, ?, ?)",
                (title_id, alt_name, source),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            pass

    def get_alt_titles(self, title_id: int) -> List[AltTitle]:
        rows = self._conn.execute(
            "SELECT * FROM alt_titles WHERE title_id = ?", (title_id,)
        ).fetchall()
        return [_row_to_alt(r) for r in rows]

    # ── Read progress ─────────────────────────────────────────────────────

    def get_progress(self, title_id: int) -> Optional[ReadProgress]:
        row = self._conn.execute(
            "SELECT * FROM read_progress WHERE title_id = ?", (title_id,)
        ).fetchone()
        return _row_to_progress(row) if row else None

    def raise_progress(self, title_id: int, max_chapter: float,
                       status: str = "", source_tag: str = "suwa") -> bool:
        """Update progress only if the new chapter is higher.  Returns True if raised."""
        now = _now_iso()
        existing = self.get_progress(title_id)
        if existing:
            if max_chapter <= existing.max_chapter:
                return False
            sync_field = f"last_synced_{source_tag}" if source_tag in ("suwa", "mal", "mu") else ""
            sets = ["max_chapter=?", "updated_at=?"]
            params: list = [max_chapter, now]
            if status:
                sets.append("status=?")
                params.append(status)
            if sync_field:
                sets.append(f"{sync_field}=?")
                params.append(now)
            params.append(title_id)
            self._conn.execute(
                f"UPDATE read_progress SET {', '.join(sets)} WHERE title_id=?",
                params,
            )
            self._conn.commit()
            return True
        # Insert new
        self._conn.execute(
            "INSERT INTO read_progress (title_id, max_chapter, status, last_synced_suwa, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (title_id, max_chapter, status or "reading", now if source_tag == "suwa" else "", now),
        )
        self._conn.commit()
        return True

    def all_progress(self) -> List[Tuple[LedgerTitle, ReadProgress]]:
        """Return all (title, progress) pairs ordered by display_title."""
        rows = self._conn.execute(
            "SELECT t.*, p.id AS p_id, p.title_id AS p_title_id, p.max_chapter, "
            "p.max_volume, p.status, p.last_synced_suwa, p.last_synced_mal, "
            "p.last_synced_mu, p.updated_at AS p_updated_at "
            "FROM titles t JOIN read_progress p ON t.id = p.title_id "
            "ORDER BY t.display_title"
        ).fetchall()
        result = []
        for r in rows:
            title = LedgerTitle(
                id=r["id"], normalized_key=r["normalized_key"],
                display_title=r["display_title"], mal_id=r["mal_id"],
                mu_id=r["mu_id"], created_at=r["created_at"], updated_at=r["updated_at"],
            )
            prog = ReadProgress(
                id=r["p_id"], title_id=r["p_title_id"], max_chapter=r["max_chapter"],
                max_volume=r["max_volume"], status=r["status"],
                last_synced_suwa=r["last_synced_suwa"], last_synced_mal=r["last_synced_mal"],
                last_synced_mu=r["last_synced_mu"], updated_at=r["p_updated_at"],
            )
            result.append((title, prog))
        return result

    # ── Suwayomi entries ──────────────────────────────────────────────────

    def upsert_suwayomi_entry(self, title_id: int, suwayomi_id: int,
                              source_id: str = "", source_name: str = "",
                              in_library: bool = True, chapter_count: int = 0) -> None:
        existing = self._conn.execute(
            "SELECT id FROM suwayomi_entries WHERE suwayomi_id = ?", (suwayomi_id,)
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE suwayomi_entries SET title_id=?, source_id=?, source_name=?, "
                "in_library=?, chapter_count=? WHERE suwayomi_id=?",
                (title_id, source_id, source_name, int(in_library), chapter_count, suwayomi_id),
            )
        else:
            self._conn.execute(
                "INSERT INTO suwayomi_entries (title_id, suwayomi_id, source_id, source_name, in_library, chapter_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (title_id, suwayomi_id, source_id, source_name, int(in_library), chapter_count),
            )
        self._conn.commit()

    def get_suwayomi_entries(self, title_id: int) -> List[SuwayomiEntry]:
        rows = self._conn.execute(
            "SELECT * FROM suwayomi_entries WHERE title_id = ?", (title_id,)
        ).fetchall()
        return [_row_to_suwa(r) for r in rows]

    def get_suwayomi_entry_by_mid(self, suwayomi_id: int) -> Optional[SuwayomiEntry]:
        row = self._conn.execute(
            "SELECT * FROM suwayomi_entries WHERE suwayomi_id = ?", (suwayomi_id,)
        ).fetchone()
        return _row_to_suwa(row) if row else None

    # ── Metadata / snapshot times ─────────────────────────────────────────

    def get_last_snapshot_time(self) -> str:
        """Return the ISO timestamp of the last snapshot, or '' if never run."""
        row = self._conn.execute(
            "SELECT value FROM metadata WHERE key = 'last_snapshot_time'"
        ).fetchone()
        return row[0] if row else ""

    def set_last_snapshot_time(self) -> None:
        """Record the current time as the last snapshot time."""
        now = _now_iso()
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_snapshot_time', ?)",
            (now,),
        )
        self._conn.commit()

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        titles = self._conn.execute("SELECT COUNT(*) FROM titles").fetchone()[0]
        with_progress = self._conn.execute(
            "SELECT COUNT(*) FROM read_progress WHERE max_chapter > 0"
        ).fetchone()[0]
        suwa_entries = self._conn.execute("SELECT COUNT(*) FROM suwayomi_entries").fetchone()[0]
        alt_count = self._conn.execute("SELECT COUNT(*) FROM alt_titles").fetchone()[0]
        return {
            "titles": titles,
            "with_progress": with_progress,
            "suwayomi_entries": suwa_entries,
            "alt_titles": alt_count,
        }


# ── Row converters ────────────────────────────────────────────────────────

def _row_to_title(row: sqlite3.Row) -> LedgerTitle:
    return LedgerTitle(
        id=row["id"], normalized_key=row["normalized_key"],
        display_title=row["display_title"], mal_id=row["mal_id"],
        mu_id=row["mu_id"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_alt(row: sqlite3.Row) -> AltTitle:
    return AltTitle(
        id=row["id"], title_id=row["title_id"],
        alt_name=row["alt_name"], source=row["source"],
    )


def _row_to_progress(row: sqlite3.Row) -> ReadProgress:
    return ReadProgress(
        id=row["id"], title_id=row["title_id"],
        max_chapter=row["max_chapter"], max_volume=row["max_volume"],
        status=row["status"], last_synced_suwa=row["last_synced_suwa"],
        last_synced_mal=row["last_synced_mal"], last_synced_mu=row["last_synced_mu"],
        updated_at=row["updated_at"],
    )


def _row_to_suwa(row: sqlite3.Row) -> SuwayomiEntry:
    return SuwayomiEntry(
        id=row["id"], title_id=row["title_id"],
        suwayomi_id=row["suwayomi_id"], source_id=row["source_id"],
        source_name=row["source_name"], in_library=bool(row["in_library"]),
        chapter_count=row["chapter_count"],
    )

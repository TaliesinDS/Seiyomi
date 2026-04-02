"""Tests for seiyomi.ledger.db — schema, CRUD, monotonic raise."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from seiyomi.ledger.db import LedgerDB


@pytest.fixture
def db(tmp_path):
    """Create a fresh in-memory-like ledger DB in a temp directory."""
    db = LedgerDB(tmp_path / "test_ledger.db")
    yield db
    db.close()


# ── Schema creation ────────────────────────────────────────────────────────

class TestSchema:
    def test_tables_exist(self, db: LedgerDB):
        tables = {
            r[0]
            for r in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "titles" in tables
        assert "alt_titles" in tables
        assert "read_progress" in tables
        assert "suwayomi_entries" in tables
        assert "schema_version" in tables
        assert "metadata" in tables

    def test_schema_version_is_1(self, db: LedgerDB):
        row = db._conn.execute("SELECT version FROM schema_version").fetchone()
        assert row[0] == 1

    def test_double_init_is_idempotent(self, tmp_path):
        db1 = LedgerDB(tmp_path / "dup.db")
        db2 = LedgerDB(tmp_path / "dup.db")
        assert db1.stats()["titles"] == 0
        assert db2.stats()["titles"] == 0
        db1.close()
        db2.close()


# ── Title CRUD ─────────────────────────────────────────────────────────────

class TestTitles:
    def test_upsert_creates_title(self, db: LedgerDB):
        tid = db.upsert_title("solo leveling", "Solo Leveling")
        assert tid > 0
        t = db.get_title_by_key("solo leveling")
        assert t is not None
        assert t.display_title == "Solo Leveling"

    def test_upsert_updates_longer_display(self, db: LedgerDB):
        db.upsert_title("solo leveling", "Solo Leveling")
        db.upsert_title("solo leveling", "Solo Leveling: Arise from the Shadow")
        t = db.get_title_by_key("solo leveling")
        assert t is not None
        assert t.display_title == "Solo Leveling: Arise from the Shadow"

    def test_upsert_keeps_longer_existing(self, db: LedgerDB):
        db.upsert_title("solo leveling", "Solo Leveling: Arise from the Shadow")
        db.upsert_title("solo leveling", "Solo Leveling")
        t = db.get_title_by_key("solo leveling")
        assert t is not None
        assert t.display_title == "Solo Leveling: Arise from the Shadow"

    def test_upsert_merges_mal_mu_ids(self, db: LedgerDB):
        db.upsert_title("test", "Test", mal_id=123)
        db.upsert_title("test", "Test", mu_id=456)
        t = db.get_title_by_key("test")
        assert t is not None
        assert t.mal_id == 123
        assert t.mu_id == 456

    def test_get_by_id(self, db: LedgerDB):
        tid = db.upsert_title("test title", "Test Title")
        t = db.get_title_by_id(tid)
        assert t is not None
        assert t.normalized_key == "test title"

    def test_all_titles_sorted(self, db: LedgerDB):
        db.upsert_title("zzz", "ZZZ Title")
        db.upsert_title("aaa", "AAA Title")
        titles = db.all_titles()
        assert titles[0].display_title == "AAA Title"
        assert titles[1].display_title == "ZZZ Title"


# ── Alt titles ─────────────────────────────────────────────────────────────

class TestAltTitles:
    def test_add_and_retrieve(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.add_alt_title(tid, "Test (Official)", source="suwayomi")
        db.add_alt_title(tid, "Testo", source="mal")
        alts = db.get_alt_titles(tid)
        assert len(alts) == 2
        names = {a.alt_name for a in alts}
        assert "Test (Official)" in names
        assert "Testo" in names

    def test_duplicate_ignored(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.add_alt_title(tid, "Test Alt")
        db.add_alt_title(tid, "Test Alt")  # duplicate
        assert len(db.get_alt_titles(tid)) == 1


# ── Read progress ──────────────────────────────────────────────────────────

class TestReadProgress:
    def test_initial_raise(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        assert db.raise_progress(tid, 10.0) is True
        p = db.get_progress(tid)
        assert p is not None
        assert p.max_chapter == 10.0

    def test_raise_higher(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.raise_progress(tid, 10.0)
        assert db.raise_progress(tid, 20.0) is True
        p = db.get_progress(tid)
        assert p is not None
        assert p.max_chapter == 20.0

    def test_no_lower(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.raise_progress(tid, 20.0)
        assert db.raise_progress(tid, 10.0) is False
        p = db.get_progress(tid)
        assert p is not None
        assert p.max_chapter == 20.0

    def test_no_equal(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.raise_progress(tid, 15.0)
        assert db.raise_progress(tid, 15.0) is False

    def test_status_update(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.raise_progress(tid, 10.0, status="reading")
        db.raise_progress(tid, 20.0, status="completed")
        p = db.get_progress(tid)
        assert p is not None
        assert p.status == "completed"

    def test_all_progress(self, db: LedgerDB):
        t1 = db.upsert_title("aaa", "AAA")
        t2 = db.upsert_title("bbb", "BBB")
        db.raise_progress(t1, 5.0)
        db.raise_progress(t2, 10.0)
        pairs = db.all_progress()
        assert len(pairs) == 2
        assert pairs[0][0].display_title == "AAA"
        assert pairs[0][1].max_chapter == 5.0
        assert pairs[1][0].display_title == "BBB"


# ── Suwayomi entries ──────────────────────────────────────────────────────

class TestSuwayomiEntries:
    def test_upsert_and_retrieve(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.upsert_suwayomi_entry(tid, suwayomi_id=42, source_name="MangaDex",
                                 in_library=True, chapter_count=100)
        entries = db.get_suwayomi_entries(tid)
        assert len(entries) == 1
        assert entries[0].suwayomi_id == 42
        assert entries[0].source_name == "MangaDex"
        assert entries[0].chapter_count == 100

    def test_upsert_updates_existing(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.upsert_suwayomi_entry(tid, suwayomi_id=42, chapter_count=50)
        db.upsert_suwayomi_entry(tid, suwayomi_id=42, chapter_count=100)
        entries = db.get_suwayomi_entries(tid)
        assert len(entries) == 1
        assert entries[0].chapter_count == 100

    def test_multiple_entries_per_title(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.upsert_suwayomi_entry(tid, suwayomi_id=1, source_name="MangaDex")
        db.upsert_suwayomi_entry(tid, suwayomi_id=2, source_name="Bato.to")
        assert len(db.get_suwayomi_entries(tid)) == 2

    def test_get_by_suwayomi_id(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.upsert_suwayomi_entry(tid, suwayomi_id=99)
        e = db.get_suwayomi_entry_by_mid(99)
        assert e is not None
        assert e.title_id == tid

    def test_get_missing_returns_none(self, db: LedgerDB):
        assert db.get_suwayomi_entry_by_mid(999) is None


# ── Stats ──────────────────────────────────────────────────────────────────

class TestStats:
    def test_empty_stats(self, db: LedgerDB):
        s = db.stats()
        assert s["titles"] == 0
        assert s["with_progress"] == 0

    def test_populated_stats(self, db: LedgerDB):
        t1 = db.upsert_title("a", "A")
        t2 = db.upsert_title("b", "B")
        db.raise_progress(t1, 5.0)
        db.add_alt_title(t1, "Alt A")
        db.upsert_suwayomi_entry(t1, suwayomi_id=1)
        s = db.stats()
        assert s["titles"] == 2
        assert s["with_progress"] == 1
        assert s["alt_titles"] == 1
        assert s["suwayomi_entries"] == 1


# ── Metadata / snapshot times ─────────────────────────────────────────────

class TestMetadata:
    def test_no_snapshot_time_initially(self, db: LedgerDB):
        assert db.get_last_snapshot_time() == ""

    def test_set_and_get_snapshot_time(self, db: LedgerDB):
        db.set_last_snapshot_time()
        ts = db.get_last_snapshot_time()
        assert ts != ""
        assert "T" in ts  # ISO format

    def test_set_overwrites_previous(self, db: LedgerDB):
        db.set_last_snapshot_time()
        first = db.get_last_snapshot_time()
        import time; time.sleep(0.01)
        db.set_last_snapshot_time()
        second = db.get_last_snapshot_time()
        assert second >= first

"""Tests for ledger show and export helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from seiyomi.ledger.db import LedgerDB
from seiyomi.ledger.show import show_stats, show_title, export_csv


@pytest.fixture
def db(tmp_path):
    db = LedgerDB(tmp_path / "test_ledger.db")
    yield db
    db.close()


class TestShow:
    def test_stats_empty(self, db: LedgerDB):
        out = show_stats(db)
        assert "Titles:" in out
        assert "0" in out

    def test_stats_populated(self, db: LedgerDB):
        tid = db.upsert_title("test", "Test")
        db.raise_progress(tid, 5.0)
        out = show_stats(db)
        assert "1" in out

    def test_show_title_match(self, db: LedgerDB):
        tid = db.upsert_title("solo leveling", "Solo Leveling")
        db.raise_progress(tid, 50.0)
        db.add_alt_title(tid, "Na Honjaman Level Up", source="mal")
        db.upsert_suwayomi_entry(tid, suwayomi_id=42, source_name="MangaDex", chapter_count=200)

        out = show_title(db, "solo")
        assert "Solo Leveling" in out
        assert "50.0" in out
        assert "Na Honjaman Level Up" in out
        assert "MangaDex" in out
        assert "id=42" in out

    def test_show_title_no_match(self, db: LedgerDB):
        out = show_title(db, "nonexistent")
        assert "No ledger entries" in out


class TestExport:
    def test_export_creates_csv(self, db: LedgerDB, tmp_path):
        tid = db.upsert_title("test", "Test Title")
        db.raise_progress(tid, 25.0)

        out_path = tmp_path / "export.csv"
        result = export_csv(db, out_path)
        assert Path(result).exists()

        content = Path(result).read_text(encoding="utf-8")
        assert "Test Title" in content
        assert "25.0" in content

    def test_export_empty(self, db: LedgerDB, tmp_path):
        out_path = tmp_path / "empty.csv"
        export_csv(db, out_path)
        content = out_path.read_text(encoding="utf-8")
        # Should have header row only
        assert "title" in content
        lines = [l for l in content.strip().splitlines() if l]
        assert len(lines) == 1

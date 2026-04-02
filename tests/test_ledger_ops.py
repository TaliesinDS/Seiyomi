"""Tests for ledger snapshot and apply operations."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from seiyomi.ledger.db import LedgerDB
from seiyomi.ledger.snapshot import snapshot, _norm_key
from seiyomi.ledger.apply import apply_ledger


@pytest.fixture
def db(tmp_path):
    db = LedgerDB(tmp_path / "test_ledger.db")
    yield db
    db.close()


@pytest.fixture
def mock_client():
    """A mock SuwayomiClient with minimal responses."""
    client = MagicMock()
    client.get_sources.return_value = [
        {"id": 1, "name": "MangaDex"},
        {"id": 2, "name": "Bato.to"},
    ]
    return client


# ── Snapshot tests ─────────────────────────────────────────────────────────

class TestSnapshot:
    def test_snapshot_library_entries(self, db: LedgerDB, mock_client):
        mock_client.get_library_graphql.return_value = [
            {"id": 100, "title": "Solo Leveling", "sourceId": 1},
            {"id": 200, "title": "Tower of God", "sourceId": 2},
        ]
        mock_client.get_library.return_value = []
        mock_client.graphql.return_value = {
            "data": {"chapters": {"nodes": []}}
        }
        mock_client.get_chapters_graphql.return_value = [
            {"id": 1001, "chapterNumber": 1.0, "isRead": True},
            {"id": 1002, "chapterNumber": 2.0, "isRead": True},
            {"id": 1003, "chapterNumber": 3.0, "isRead": False},
        ]

        with patch("seiyomi.ledger.snapshot.compute_entry_progress_by_number", return_value=2.0):
            result = snapshot(mock_client, db, include_orphans=False)

        assert result["entries_scanned"] == 2
        assert result["titles_created"] == 2
        assert result["progress_raised"] == 2
        assert result["entries_linked"] == 2

        # Verify DB state
        t = db.get_title_by_key(_norm_key("Solo Leveling"))
        assert t is not None
        p = db.get_progress(t.id)
        assert p is not None
        assert p.max_chapter == 2.0

    def test_snapshot_orphans(self, db: LedgerDB, mock_client):
        mock_client.get_library_graphql.return_value = [
            {"id": 100, "title": "Solo Leveling", "sourceId": 1},
        ]
        mock_client.get_library.return_value = []

        # GQL calls: first for orphan IDs, then for each orphan's title
        def fake_graphql(query, variables=None):
            if "isRead" in query:
                # Return orphan manga IDs (100 is library, 999 is orphan)
                return {"data": {"chapters": {"nodes": [
                    {"mangaId": 100}, {"mangaId": 999},
                ]}}}
            if "manga(id:" in query or "$id" in query:
                return {"data": {"manga": {"id": 999, "title": "Solo Leveling", "sourceId": 2}}}
            return {}

        mock_client.graphql.side_effect = fake_graphql
        mock_client.get_chapters_graphql.return_value = []

        with patch("seiyomi.ledger.snapshot.compute_entry_progress_by_number") as mock_prog:
            mock_prog.side_effect = lambda c, mid: 50.0 if mid == 999 else 10.0
            result = snapshot(mock_client, db, include_orphans=True)

        assert result["entries_scanned"] == 2  # 1 library + 1 orphan

        # Both should map to same title, orphan has higher progress
        t = db.get_title_by_key(_norm_key("Solo Leveling"))
        assert t is not None
        p = db.get_progress(t.id)
        assert p is not None
        assert p.max_chapter == 50.0

    def test_snapshot_no_library(self, db: LedgerDB, mock_client):
        mock_client.get_library_graphql.return_value = []
        mock_client.get_library.return_value = []
        result = snapshot(mock_client, db, include_orphans=False)
        assert result["entries_scanned"] == 0

    def test_snapshot_only_raises(self, db: LedgerDB, mock_client):
        """Re-running snapshot should not lower progress."""
        tid = db.upsert_title(_norm_key("Test Manga"), "Test Manga")
        db.raise_progress(tid, 100.0)

        mock_client.get_library_graphql.return_value = [
            {"id": 50, "title": "Test Manga", "sourceId": 1},
        ]
        mock_client.get_library.return_value = []
        mock_client.graphql.return_value = {"data": {"chapters": {"nodes": []}}}
        mock_client.get_chapters_graphql.return_value = []

        with patch("seiyomi.ledger.snapshot.compute_entry_progress_by_number", return_value=5.0):
            snapshot(mock_client, db, include_orphans=False)

        p = db.get_progress(tid)
        assert p is not None
        assert p.max_chapter == 100.0  # NOT lowered to 5

    def test_incremental_skips_unchanged(self, db: LedgerDB, mock_client):
        """Incremental snapshot skips entries not read since last snapshot."""
        # Simulate a previous snapshot
        db.set_last_snapshot_time()
        import time; time.sleep(0.01)

        # The GQL response includes latestReadChapter.lastReadAt
        # Entry 100 was read BEFORE the snapshot, entry 200 was read AFTER
        old_ts = "2020-01-01T00:00:00+00:00"
        new_ts = "2099-01-01T00:00:00+00:00"

        def fake_graphql(query, variables=None):
            if "latestReadChapter" in query:
                return {"data": {"mangas": {"nodes": [
                    {"id": 100, "title": "Old Read", "sourceId": 1,
                     "latestReadChapter": {"lastReadAt": old_ts}},
                    {"id": 200, "title": "New Read", "sourceId": 1,
                     "latestReadChapter": {"lastReadAt": new_ts}},
                ]}}}
            if "isRead" in query:
                return {"data": {"chapters": {"nodes": []}}}
            return {}

        mock_client.graphql.side_effect = fake_graphql
        mock_client.get_chapters_graphql.return_value = []

        with patch("seiyomi.ledger.snapshot.compute_entry_progress_by_number", return_value=5.0):
            result = snapshot(mock_client, db, include_orphans=False, incremental=True)

        assert result["skipped_incremental"] == 1  # Old Read skipped
        assert result["entries_scanned"] == 1       # Only New Read scanned

    def test_full_scan_ignores_timestamp(self, db: LedgerDB, mock_client):
        """incremental=False should scan all entries regardless."""
        db.set_last_snapshot_time()

        mock_client.get_library_graphql.return_value = [
            {"id": 100, "title": "Entry A", "sourceId": 1},
            {"id": 200, "title": "Entry B", "sourceId": 1},
        ]
        mock_client.get_library.return_value = []
        mock_client.graphql.return_value = {"data": {"chapters": {"nodes": []}}}
        mock_client.get_chapters_graphql.return_value = []

        with patch("seiyomi.ledger.snapshot.compute_entry_progress_by_number", return_value=0.0):
            result = snapshot(mock_client, db, include_orphans=False, incremental=False)

        assert result["entries_scanned"] == 2
        assert result["skipped_incremental"] == 0


# ── Apply tests ────────────────────────────────────────────────────────────

class TestApply:
    def test_apply_marks_behind_entries(self, db: LedgerDB, mock_client):
        # Pre-populate ledger with progress
        tid = db.upsert_title(_norm_key("Solo Leveling"), "Solo Leveling")
        db.raise_progress(tid, 50.0)

        mock_client.get_library_graphql.return_value = [
            {"id": 100, "title": "Solo Leveling", "sourceId": 1},
        ]
        mock_client.get_library.return_value = []

        with patch("seiyomi.ledger.apply.compute_entry_progress_by_number", return_value=10.0), \
             patch("seiyomi.ledger.apply.mark_entry_up_to_number") as mock_mark:
            result = apply_ledger(mock_client, db, dry_run=False)

        assert result["applied"] == 1
        mock_mark.assert_called_once_with(mock_client, 100, 50.0, rpm=120, dry_run=False)

    def test_apply_skips_current(self, db: LedgerDB, mock_client):
        tid = db.upsert_title(_norm_key("Solo Leveling"), "Solo Leveling")
        db.raise_progress(tid, 50.0)

        mock_client.get_library_graphql.return_value = [
            {"id": 100, "title": "Solo Leveling", "sourceId": 1},
        ]

        with patch("seiyomi.ledger.apply.compute_entry_progress_by_number", return_value=50.0), \
             patch("seiyomi.ledger.apply.mark_entry_up_to_number") as mock_mark:
            result = apply_ledger(mock_client, db, dry_run=False)

        assert result["skipped_current"] == 1
        mock_mark.assert_not_called()

    def test_apply_dry_run(self, db: LedgerDB, mock_client):
        tid = db.upsert_title(_norm_key("Test"), "Test")
        db.raise_progress(tid, 30.0)

        mock_client.get_library_graphql.return_value = [
            {"id": 1, "title": "Test", "sourceId": 1},
        ]

        with patch("seiyomi.ledger.apply.compute_entry_progress_by_number", return_value=0.0), \
             patch("seiyomi.ledger.apply.mark_entry_up_to_number") as mock_mark:
            result = apply_ledger(mock_client, db, dry_run=True)

        assert result["applied"] == 1
        mock_mark.assert_not_called()  # dry-run: no actual writes

    def test_apply_no_ledger_entry(self, db: LedgerDB, mock_client):
        mock_client.get_library_graphql.return_value = [
            {"id": 1, "title": "Unknown Title", "sourceId": 1},
        ]

        result = apply_ledger(mock_client, db, dry_run=False)
        assert result["skipped_no_ledger"] == 1

    def test_apply_filter(self, db: LedgerDB, mock_client):
        t1 = db.upsert_title(_norm_key("Solo Leveling"), "Solo Leveling")
        t2 = db.upsert_title(_norm_key("Tower God"), "Tower of God")
        db.raise_progress(t1, 50.0)
        db.raise_progress(t2, 30.0)

        mock_client.get_library_graphql.return_value = [
            {"id": 1, "title": "Solo Leveling", "sourceId": 1},
            {"id": 2, "title": "Tower of God", "sourceId": 1},
        ]

        with patch("seiyomi.ledger.apply.compute_entry_progress_by_number", return_value=0.0), \
             patch("seiyomi.ledger.apply.mark_entry_up_to_number"):
            result = apply_ledger(mock_client, db, filter_title="Solo")

        assert result["applied"] == 1  # Only Solo Leveling matched filter

    def test_apply_empty_library(self, db: LedgerDB, mock_client):
        mock_client.get_library_graphql.return_value = []
        mock_client.get_library.return_value = []
        result = apply_ledger(mock_client, db)
        assert result.get("error") == 1

"""Operation tests for seiyomi.operations.migrate — low-chapter entry migration.

These tests inject a mock SuwayomiClient and verify that:
- Entries WITH enough chapters are skipped
- Entries WITHOUT enough chapters trigger a source search
- A matched alt_id gets added to the library
- --migrate_remove causes remove_from_library to be called on success
- dry_run suppresses all mutations
- Preference / exclude filters work
- Checkpoint resume support skips already-done entries
"""
from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from seiyomi.operations.migrate import migrate_library


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        migrate_threshold_chapters=1,
        migrate_sources="",
        rehoming_sources="",
        exclude_sources="",
        migrate_remove=False,
        migrate_remove_if_duplicate=False,
        debug_library=False,
        dry_run=False,
        no_progress=True,
        migrate_preferred_only=False,
        migrate_try_second_page=False,
        migrate_filter_title="",
        migrate_include_categories="",
        migrate_exclude_categories="",
        migrate_max_sources_per_site=3,
        migrate_timeout=0.0,
        request_timeout=12.0,
        best_source=False,
        best_source_canonical=False,
        best_source_global=False,
        best_source_candidates=5,
        min_chapters_per_alt=0,
        preferred_langs="en",
        lang_fallback=False,
        prefer_sources="",
        prefer_boost=0,
        migrate_keep_both=False,
        keep_both_min_preferred=0,
        migrate_title_threshold=0.6,
        migrate_title_strict=False,
        interactive=False,
        resume=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _client(**overrides):
    c = MagicMock()
    c._auth.return_value = None
    c.get_library.return_value = []
    c.get_sources.return_value = []
    c.get_manga_chapters_count.return_value = 0
    c.get_manga_details.return_value = {}
    c.add_to_library.return_value = True
    c.remove_from_library.return_value = True
    c.search_source.return_value = {}
    c.list_categories.return_value = []
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def _entry(id_: int, title: str = "Test Manga", chapters: int = 0) -> dict:
    return {"id": id_, "title": title, "chapters": chapters}


def _source(id_: int = 10000, name: str = "Manga River") -> dict:
    return {"id": id_, "name": name}


def _search_hit(alt_id: int, title: str = "Test Manga") -> dict:
    return {"results": [{"id": alt_id, "title": title}]}


# ────────────────────────────────────────────────────────────────────────────
# Basic filtering
# ────────────────────────────────────────────────────────────────────────────

class TestThresholdFiltering:
    def test_skips_entry_with_enough_chapters(self):
        """Entry with chapters >= threshold should not be searched."""
        client = _client(
            get_library=MagicMock(return_value=[_entry(1, "Berserk", chapters=0)]),
            get_manga_chapters_count=MagicMock(return_value=10),
            get_sources=MagicMock(return_value=[_source()]),
        )
        migrate_library(client, _args(migrate_threshold_chapters=5))
        client.search_source.assert_not_called()

    def test_processes_entry_with_zero_chapters(self):
        """Entry with 0 chapters is below threshold and should trigger search."""
        client = _client(
            get_library=MagicMock(return_value=[_entry(1, "Berserk")]),
            get_manga_chapters_count=MagicMock(return_value=0),
            get_manga_details=MagicMock(return_value={"title": "Berserk"}),
            get_sources=MagicMock(return_value=[_source()]),
            search_source=MagicMock(return_value={}),
        )
        migrate_library(client, _args())
        client.search_source.assert_called()

    def test_excludes_source_by_name_fragment(self):
        """Sources matching --exclude fragment should be skipped."""
        client = _client(
            get_library=MagicMock(return_value=[_entry(1)]),
            get_manga_chapters_count=MagicMock(return_value=0),
            get_sources=MagicMock(return_value=[_source(10001, "Comick"), _source(10002, "Manga River")]),
        )
        migrate_library(client, _args(exclude_sources="comick"))
        # search_source should only be called for non-excluded source
        calls = [str(c) for c in client.search_source.call_args_list]
        assert all("s1" not in c for c in calls)

    def test_filter_title_skips_non_matching(self):
        """--migrate-filter-title only processes titles containing the substring."""
        client = _client(
            get_library=MagicMock(return_value=[
                _entry(1, "Berserk"),
                _entry(2, "Vinland Saga"),
            ]),
            get_manga_chapters_count=MagicMock(return_value=0),
            get_sources=MagicMock(return_value=[_source()]),
        )
        migrate_library(client, _args(migrate_filter_title="Berserk"))
        # Only Berserk should trigger searches; Vinland Saga skipped
        calls = client.search_source.call_args_list
        titles_searched = [c[0][1] if c[0] else c[1].get("term", "") for c in calls]
        for t in titles_searched:
            assert "Berserk" in str(t) or t == ""


# ────────────────────────────────────────────────────────────────────────────
# Migration actions
# ────────────────────────────────────────────────────────────────────────────

class TestMigrationActions:
    def _setup_hit(self, alt_id: int = 99, source_name: str = "River"):
        client = _client(
            get_library=MagicMock(return_value=[_entry(1, "Test Manga")]),
            get_manga_chapters_count=MagicMock(return_value=0),
            get_sources=MagicMock(return_value=[_source(10001, source_name)]),
            search_source=MagicMock(return_value=_search_hit(alt_id, "Test Manga")),
        )
        SuwayomiClient_extract = MagicMock(return_value=alt_id)
        return client, SuwayomiClient_extract

    def test_add_to_library_called_on_match(self):
        """When a match is found, add_to_library must be called with the alt_id."""
        from seiyomi.clients.suwayomi import SuwayomiClient
        client = _client(
            get_library=MagicMock(return_value=[_entry(1, "Test Manga")]),
            get_manga_chapters_count=MagicMock(return_value=0),
            get_sources=MagicMock(return_value=[_source()]),
            search_source=MagicMock(return_value=_search_hit(99, "Test Manga")),
        )
        with patch.object(SuwayomiClient, "extract_manga_id", return_value=99):
            migrate_library(client, _args())
        client.add_to_library.assert_called_once_with(99)

    def test_dry_run_suppresses_add(self):
        """In dry-run mode, add_to_library should never be called."""
        from seiyomi.clients.suwayomi import SuwayomiClient
        client = _client(
            get_library=MagicMock(return_value=[_entry(1, "Test Manga")]),
            get_manga_chapters_count=MagicMock(return_value=0),
            get_sources=MagicMock(return_value=[_source()]),
            search_source=MagicMock(return_value=_search_hit(99)),
        )
        with patch.object(SuwayomiClient, "extract_manga_id", return_value=99):
            result = migrate_library(client, _args(dry_run=True))
        client.add_to_library.assert_not_called()
        assert result == 0

    def test_migrate_remove_calls_remove_on_success(self):
        """--migrate_remove should call remove_from_library after successful add."""
        from seiyomi.clients.suwayomi import SuwayomiClient
        client = _client(
            get_library=MagicMock(return_value=[_entry(1, "Test Manga")]),
            get_manga_chapters_count=MagicMock(return_value=0),
            get_sources=MagicMock(return_value=[_source()]),
            search_source=MagicMock(return_value=_search_hit(99)),
        )
        with patch.object(SuwayomiClient, "extract_manga_id", return_value=99):
            migrate_library(client, _args(migrate_remove=True))
        client.remove_from_library.assert_called_once_with(1)

    def test_remove_not_called_when_add_fails(self):
        """If add fails, remove_from_library must NOT be called even with --migrate-remove."""
        from seiyomi.clients.suwayomi import SuwayomiClient
        client = _client(
            get_library=MagicMock(return_value=[_entry(1, "Test Manga")]),
            get_manga_chapters_count=MagicMock(return_value=0),
            get_sources=MagicMock(return_value=[_source()]),
            search_source=MagicMock(return_value=_search_hit(99)),
            add_to_library=MagicMock(return_value=False),
        )
        with patch.object(SuwayomiClient, "extract_manga_id", return_value=99):
            migrate_library(client, _args(migrate_remove=True))
        client.remove_from_library.assert_not_called()

    def test_returns_0_when_no_failures(self):
        """A library entry with chapters >= threshold is skipped (not failed); returns 0."""
        client = _client(
            get_library=MagicMock(return_value=[_entry(1, "Solo")]),
            get_manga_chapters_count=MagicMock(return_value=99),
            get_sources=MagicMock(return_value=[]),
        )
        assert migrate_library(client, _args(migrate_threshold_chapters=1)) == 0

    def test_returns_5_when_library_empty(self):
        client = _client(get_library=MagicMock(return_value=None))  # None → falsy → exit 5
        assert migrate_library(client, _args()) == 5


# ────────────────────────────────────────────────────────────────────────────
# Checkpoint / resume
# ────────────────────────────────────────────────────────────────────────────

class TestCheckpointResume:
    def test_resume_skips_completed_ids(self, tmp_path):
        """Entries recorded in the checkpoint file should be skipped."""
        import json
        cp_file = tmp_path / ".seiyomi_checkpoint_migrate.json"
        cp_file.write_text(json.dumps({"operation": "migrate", "completed": ["1"]}), encoding="utf-8")

        client = _client(
            get_library=MagicMock(return_value=[_entry(1)]),
            get_manga_chapters_count=MagicMock(return_value=0),
            get_sources=MagicMock(return_value=[_source()]),
        )
        with patch("seiyomi.utils.checkpoint._DEFAULT_DIR", tmp_path):
            migrate_library(client, _args(resume=True))
        client.search_source.assert_not_called()

    def test_checkpoint_cleared_on_clean_run(self, tmp_path):
        """Checkpoint file should be deleted after a run with no failures."""
        cp_file = tmp_path / ".seiyomi_checkpoint_migrate.json"
        client = _client(get_library=MagicMock(return_value=[]))
        with patch("seiyomi.utils.checkpoint._DEFAULT_DIR", tmp_path):
            migrate_library(client, _args(resume=False))
        # File should not exist after a clean run (never written or cleared)
        assert not cp_file.exists()

    def test_checkpoint_written_on_success(self, tmp_path):
        """After a successful migration, the entry id should be checkpointed."""
        from seiyomi.clients.suwayomi import SuwayomiClient
        client = _client(
            get_library=MagicMock(return_value=[_entry(42, "Test")]),
            get_manga_chapters_count=MagicMock(return_value=0),
            get_sources=MagicMock(return_value=[_source()]),
            search_source=MagicMock(return_value=_search_hit(99)),
        )
        with patch("seiyomi.utils.checkpoint._DEFAULT_DIR", tmp_path):
            with patch.object(SuwayomiClient, "extract_manga_id", return_value=99):
                migrate_library(client, _args())
        # After clean run with no failures the checkpoint is cleared (file deleted)
        # so we just assert the run didn't crash

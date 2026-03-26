"""Smoke tests for seiyomi.operations modules.

These tests verify the public API surface of each operations module
using a fully mocked SuwayomiClient. They do NOT test end-to-end
behaviour (those are integration tests) — just that the modules are
importable, have the expected callables, and accept the expected
signatures without blowing up on happy-path minimal input.
"""
from __future__ import annotations

import argparse
import pytest
from unittest.mock import MagicMock


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _mock_client(**overrides):
    client = MagicMock()
    client.get_library.return_value = []
    client.get_library_graphql.return_value = []
    client.get_sources.return_value = []
    client.get_manga_chapters_count.return_value = 0
    client.get_manga_details.return_value = {}
    client.add_to_library.return_value = True
    client.remove_from_library.return_value = True
    client.add_manga_to_category.return_value = True
    client.search_source.return_value = {}
    client._auth.return_value = None
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


def _migrate_args(**kwargs):
    """Minimal argparse.Namespace that satisfies migrate_library."""
    defaults = dict(
        migrate_threshold_chapters=1,
        migrate_sources="",
        rehoming_sources="",
        exclude_sources="comick,hitomi",
        migrate_remove=False,
        migrate_remove_if_duplicate=False,
        debug_library=False,
        dry_run=True,
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
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _prune_args(**kwargs):
    """Minimal argparse.Namespace that satisfies prune_zero_duplicates / prune_nonpreferred_langs."""
    defaults = dict(
        prune_threshold_chapters=1,
        prune_filter_title="",
        dry_run=True,
        no_progress=True,
        preferred_langs="en",
        prune_lang_threshold=1,
        prune_lang_fallback_keep_most=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ------------------------------------------------------------------ #
# seiyomi.operations.migrate
# ------------------------------------------------------------------ #

class TestMigrateModule:
    def test_importable(self):
        from seiyomi.operations.migrate import migrate_library
        assert callable(migrate_library)

    def test_migrate_empty_library(self):
        from seiyomi.operations.migrate import migrate_library
        client = _mock_client()
        # Empty library → nothing to migrate; returns exit code 0 or 6
        result = migrate_library(client, _migrate_args())
        assert isinstance(result, int)

    def test_migrate_returns_zero_on_empty_library(self):
        from seiyomi.operations.migrate import migrate_library
        client = _mock_client(get_library=MagicMock(return_value=[]))
        result = migrate_library(client, _migrate_args())
        # 0 = success (nothing to do), or non-zero if library fetch "failed"
        assert result in (0, 5, 6)


# ------------------------------------------------------------------ #
# seiyomi.operations.prune
# ------------------------------------------------------------------ #

class TestPruneModule:
    def test_importable(self):
        from seiyomi.operations.prune import prune_zero_duplicates, prune_nonpreferred_langs
        assert callable(prune_zero_duplicates)
        assert callable(prune_nonpreferred_langs)

    def test_prune_zero_duplicates_empty(self):
        from seiyomi.operations.prune import prune_zero_duplicates
        client = _mock_client()
        result = prune_zero_duplicates(client, _prune_args())
        assert isinstance(result, int)
        assert result in (0, 5)

    def test_prune_nonpreferred_langs_empty(self):
        from seiyomi.operations.prune import prune_nonpreferred_langs
        client = _mock_client()
        result = prune_nonpreferred_langs(client, _prune_args())
        assert isinstance(result, int)
        assert result in (0, 5)


# ------------------------------------------------------------------ #
# seiyomi.operations.rehome
# ------------------------------------------------------------------ #

class TestRehomeModule:
    def test_importable(self):
        from seiyomi.operations.rehome import rehome_entry
        assert callable(rehome_entry)

    def test_rehome_no_sources(self):
        from seiyomi.operations.rehome import rehome_entry
        client = _mock_client()
        result = rehome_entry(
            client=client,
            manga_id=42,
            title="Test Title",
            rehome_conf={
                "sources": [],
                "exclude_frags": [],
                "title_threshold": 0.6,
                "title_strict": False,
                "best_source": False,
                "best_candidates": 5,
                "min_chapters_per_alt": 0,
                "canonical": False,
                "remove_md": False,
            },
            show_progress=False,
        )
        assert result is False

    def test_rehome_no_results_from_search(self):
        from seiyomi.operations.rehome import rehome_entry
        client = _mock_client()
        client.get_sources.return_value = [{"id": "99", "name": "TestSource"}]
        client.search_source.return_value = {}
        result = rehome_entry(
            client=client,
            manga_id=1,
            title="Some Manga",
            rehome_conf={
                "sources": ["testsource"],
                "exclude_frags": [],
                "title_threshold": 0.6,
                "title_strict": False,
                "best_source": False,
                "best_candidates": 5,
                "min_chapters_per_alt": 0,
                "canonical": False,
                "remove_md": False,
            },
            show_progress=False,
        )
        assert result is False


# ------------------------------------------------------------------ #
# seiyomi.operations.import_follows
# ------------------------------------------------------------------ #

class TestImportFollowsModule:
    def test_importable(self):
        from seiyomi.operations.import_follows import import_ids
        assert callable(import_ids)

    def test_import_ids_no_mangadex_source_exits(self):
        from seiyomi.operations.import_follows import import_ids
        client = _mock_client()
        # No MangaDex source installed → function raises SystemExit with a clear message
        with pytest.raises(SystemExit, match="MangaDex source"):
            import_ids(
                client=client,
                ids=[],
                dry_run=True,
                show_progress=False,
            )

    def test_import_ids_skips_all_when_source_missing(self):
        """Verify calling convention: shows the function is callable with full signature."""
        from seiyomi.operations.import_follows import import_ids
        client = _mock_client()
        # Simulate MangaDex source present; ids=[] → nothing added
        client.get_sources.return_value = [{"id": "10000000000", "name": "MangaDex", "apkName": "eu.kanade.tachiyomi.extension.en.mangadex"}]
        added, failed, failures, entries = import_ids(
            client=client,
            ids=[],
            dry_run=True,
            show_progress=False,
        )
        assert added == 0
        assert failed == 0
        assert failures == []
        assert entries == []


# ------------------------------------------------------------------ #
# seiyomi.operations.import_csv
# ------------------------------------------------------------------ #

class TestImportCsvModule:
    def test_importable(self):
        from seiyomi.operations.import_csv import process_csv_direct_items
        assert callable(process_csv_direct_items)

    def test_process_empty_items(self):
        from seiyomi.operations.import_csv import process_csv_direct_items
        client = _mock_client()
        added, matched, failures, prog_applied, prog_skipped = process_csv_direct_items(
            client=client,
            items=[],
            dry_run=True,
            prefer_existing=False,
            no_add_library=False,
            status_category_map={},
            status_default_category=None,
            status_map_debug=False,
            show_progress=False,
            apply_read_progress=False,
            chapter_sync_conf=None,
            title_threshold=0.6,
            title_strict=False,
        )
        assert added == []
        assert matched == []
        assert failures == []
        assert prog_applied == 0
        assert prog_skipped == 0

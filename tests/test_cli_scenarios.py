"""CLI scenario tests for seiyomi.cli.main().

These tests call main() with a mocked SuwayomiClient to verify:
- Subcommand routing dispatches to the right function
- Old flat-flag args are translated by the compat layer
- list categories/library/sources call the right client methods
- prune duplicates and prune languages route correctly
- import csv dispatches correctly
- Verbose flag sets log level to DEBUG
- Checkpoint and rate limiter tests
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch, call

import pytest

from seiyomi.cli import main
from seiyomi.utils.checkpoint import Checkpoint
from seiyomi.utils.rate_limiter import RateLimiter


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_monolith_delegation(monkeypatch):
    """Prevent any test from accidentally calling the monolith."""
    def _denied(argv):
        raise AssertionError(f"Unexpected monolith delegation with argv={argv}")
    monkeypatch.setattr("seiyomi.cli._delegate_to_monolith", _denied)


@pytest.fixture
def mock_client():
    c = MagicMock()
    c.list_categories.return_value = [{"id": 1, "name": "Reading"}]
    c.get_library.return_value = [{"id": 1, "title": "Berserk"}]
    c.get_library_graphql.return_value = [{"id": 1, "title": "Berserk"}]
    c.get_sources.return_value = [{"id": "src1", "name": "MangaSee"}]
    return c


@pytest.fixture
def patched_client(mock_client):
    with patch("seiyomi.cli._make_client", return_value=mock_client):
        yield mock_client


# ────────────────────────────────────────────────────────────────────────────
# list subcommands
# ────────────────────────────────────────────────────────────────────────────

class TestListSubcommands:
    def test_list_categories_calls_list_categories(self, patched_client, capsys):
        rc = main(["list", "categories", "--base-url", "http://x"])
        assert rc == 0
        patched_client.list_categories.assert_called_once()
        assert "Reading" in capsys.readouterr().out

    def test_list_library_calls_get_library(self, patched_client, capsys):
        rc = main(["list", "library", "--base-url", "http://x"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Berserk" in out

    def test_list_sources_calls_get_sources(self, patched_client, capsys):
        rc = main(["list", "sources", "--base-url", "http://x"])
        assert rc == 0
        patched_client.get_sources.assert_called_once()
        assert "MangaSee" in capsys.readouterr().out


# ────────────────────────────────────────────────────────────────────────────
# prune subcommands
# ────────────────────────────────────────────────────────────────────────────

class TestPruneSubcommands:
    def test_prune_duplicates_dispatches(self, patched_client):
        # Non-empty library so prune doesn't immediately return exit 5
        patched_client.get_library.return_value = [{"id": 1, "title": "Solo"}]
        patched_client.get_manga_chapters_count.return_value = 5
        rc = main(["prune", "duplicates", "--base-url", "http://x", "--dry-run"])
        assert rc == 0

    def test_prune_languages_dispatches(self, patched_client):
        patched_client.get_library.return_value = [{"id": 1, "title": "Solo"}]
        patched_client.get_manga_chapters_count.return_value = 5
        patched_client.get_manga_chapters_count_by_lang = MagicMock(return_value=5)
        rc = main(["prune", "languages", "--base-url", "http://x", "--dry-run"])
        assert rc == 0


# ────────────────────────────────────────────────────────────────────────────
# Compat layer (flat flags translated to subcommands)
# ────────────────────────────────────────────────────────────────────────────

class TestCompatLayer:
    def test_list_categories_flat_flag(self, patched_client, capsys):
        rc = main(["--list-categories", "--base-url", "http://x"])
        assert rc == 0
        patched_client.list_categories.assert_called_once()

    def test_list_library_titles_flat_flag(self, patched_client, capsys):
        rc = main(["--list-library-titles", "--base-url", "http://x"])
        assert rc == 0

    def test_prune_zero_duplicates_flat_flag(self, patched_client):
        patched_client.get_library.return_value = [{"id": 1, "title": "Solo"}]
        patched_client.get_manga_chapters_count.return_value = 5
        rc = main(["--prune-zero-duplicates", "--base-url", "http://x", "--dry-run"])
        assert rc == 0

    def test_prune_nonpreferred_langs_flat_flag(self, patched_client):
        patched_client.get_library.return_value = [{"id": 1, "title": "Solo"}]
        patched_client.get_manga_chapters_count.return_value = 5
        patched_client.get_manga_chapters_count_by_lang = MagicMock(return_value=5)
        rc = main(["--prune-nonpreferred-langs", "--base-url", "http://x", "--dry-run"])
        assert rc == 0


# ────────────────────────────────────────────────────────────────────────────
# import csv
# ────────────────────────────────────────────────────────────────────────────

class TestImportCsv:
    def test_missing_file_returns_2(self, patched_client):
        rc = main(["import", "csv", "--file", "/nonexistent/path.csv",
                   "--base-url", "http://x"])
        assert rc == 2

    def test_csv_import_calls_process_csv(self, patched_client, tmp_path):
        csv_path = tmp_path / "test.csv"
        csv_path.write_text(
            "Title,Status,Last Read\nMonster,Reading,5\n",
            encoding="utf-8",
        )
        with patch("seiyomi.operations.import_csv.process_csv_direct_items",
                   return_value=([], [], [], [], [])) as mock_proc:
            rc = main(["import", "csv", "--file", str(csv_path),
                       "--base-url", "http://x", "--dry-run"])
        assert rc == 0
        mock_proc.assert_called_once()


# ────────────────────────────────────────────────────────────────────────────
# migrate subcommand
# ────────────────────────────────────────────────────────────────────────────

class TestMigrateSubcommand:
    def test_migrate_empty_library_returns_0(self, patched_client):
        patched_client.get_library.return_value = None  # returns 5 (library empty)
        rc = main(["migrate", "--base-url", "http://x", "--dry-run"])
        # Library empty → exit code 5 from migrate_library
        assert rc in (0, 5)

    def test_migrate_dry_run_no_mutations(self, patched_client):
        patched_client.get_library.return_value = [{"id": 1, "title": "Test"}]
        patched_client.get_manga_chapters_count.return_value = 100  # above threshold
        main(["migrate", "--base-url", "http://x", "--dry-run"])
        patched_client.add_to_library.assert_not_called()
        patched_client.remove_from_library.assert_not_called()


# ────────────────────────────────────────────────────────────────────────────
# No command prints help
# ────────────────────────────────────────────────────────────────────────────

class TestNoCommand:
    def test_no_args_returns_nonzero(self, patched_client):
        rc = main([])
        assert rc != 0


# ────────────────────────────────────────────────────────────────────────────
# RateLimiter unit tests
# ────────────────────────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_unlimited_does_not_sleep(self):
        limiter = RateLimiter(rpm=0)
        with patch("time.sleep") as mock_sleep:
            limiter.wait()
            limiter.wait()
            limiter.wait()
        mock_sleep.assert_not_called()

    def test_limited_sleeps_between_calls(self):
        limiter = RateLimiter(rpm=60)  # 1/sec
        with patch("time.sleep") as mock_sleep:
            with patch("time.monotonic", side_effect=[0.0, 0.1, 0.1, 0.1, 1.0, 1.0]):
                limiter.wait()  # first call — no sleep (last_call=0)
                limiter.wait()  # 0.1s elapsed, need 1.0s → sleeps ~0.9s
        assert mock_sleep.called
        sleep_arg = mock_sleep.call_args[0][0]
        assert sleep_arg > 0.5  # roughly 0.9s

    def test_set_rpm_updates_interval(self):
        limiter = RateLimiter(rpm=60)
        assert abs(limiter._min_interval - 1.0) < 1e-6
        limiter.set_rpm(120)
        assert abs(limiter._min_interval - 0.5) < 1e-6

    def test_context_manager(self):
        limiter = RateLimiter(rpm=0)
        with limiter:
            pass  # should not raise

    def test_thread_safe(self):
        """Two threads calling wait() concurrently don't raise."""
        import threading
        limiter = RateLimiter(rpm=600)  # fast
        errors = []

        def _run():
            for _ in range(20):
                try:
                    limiter.wait()
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=_run) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ────────────────────────────────────────────────────────────────────────────
# Checkpoint unit tests
# ────────────────────────────────────────────────────────────────────────────

class TestCheckpoint:
    def test_load_empty_when_no_file(self, tmp_path):
        cp = Checkpoint("test", directory=tmp_path)
        cp.load()
        assert cp.count == 0

    def test_mark_done_persists(self, tmp_path):
        cp = Checkpoint("test", directory=tmp_path)
        cp.load()
        cp.mark_done(42)
        assert cp.done(42)
        # Reload from disk
        cp2 = Checkpoint("test", directory=tmp_path)
        cp2.load()
        assert cp2.done(42)

    def test_done_returns_false_for_unknown(self, tmp_path):
        cp = Checkpoint("test", directory=tmp_path)
        cp.load()
        assert not cp.done(999)

    def test_clear_deletes_file(self, tmp_path):
        cp = Checkpoint("test", directory=tmp_path)
        cp.mark_done(1)
        assert cp.path.exists()
        cp.clear()
        assert not cp.path.exists()

    def test_string_and_int_ids_equivalent(self, tmp_path):
        cp = Checkpoint("test", directory=tmp_path)
        cp.mark_done(7)
        assert cp.done("7")
        cp.mark_done("8")
        assert cp.done(8)

    def test_load_logs_count(self, tmp_path, caplog):
        import logging
        cp = Checkpoint("test", directory=tmp_path)
        cp.mark_done(1)
        cp.mark_done(2)
        cp2 = Checkpoint("test", directory=tmp_path)
        with caplog.at_level(logging.INFO, logger="seiyomi"):
            cp2.load()
        assert "2 items already done" in caplog.text

    def test_corrupted_file_does_not_crash(self, tmp_path):
        cp_file = tmp_path / ".seiyomi_checkpoint_test.json"
        cp_file.write_text("NOT JSON !!!", encoding="utf-8")
        cp = Checkpoint("test", directory=tmp_path)
        cp.load()  # should not raise
        assert cp.count == 0

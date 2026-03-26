"""Seiyomi CLI entry point.

This module owns the ``main()`` function that ``python -m seiyomi`` invokes.
Currently it delegates to the monolith while Phase 1 extraction is in progress.
Phase 1.6 goal: this file shrinks to ~200 lines of pure dispatch logic.

Architecture note: do NOT import from seiyomi.operations here yet.  The monolith
still owns the argparse definition; seiyomi/cli.py will own it once the
full rewrite lands (Phase 1.6 completion / Phase 2).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for ``python -m seiyomi``."""
    # Ensure repo root is on sys.path so the monolith is importable even when
    # seiyomi is installed as a package (e.g. via pip install -e .).
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    from import_mangadex_bookmarks_to_suwayomi_refactored import main as _monolith_main  # noqa: PLC0415

    return _monolith_main(argv)

"""Backward-compatibility shim for old flat-flag CLI invocations.

Translates the pre-Phase-2 flat-flag interface into the new subcommand form
so existing scripts and shell aliases keep working during the transition.

**Scope is intentionally narrow** — only the ~80% common case is handled.
Unmapped flags pass through unchanged; argparse will error on them, which
tells the user to update their command.

**Removal trigger:** Delete this file when Phase 3 (GUI rebuild) is complete
and the new GUI generates subcommand-style args directly.  Do NOT extend
this map for any new flag added in Phase 2+.
"""
from __future__ import annotations

import logging
import sys
from typing import List, Optional

logger = logging.getLogger("seiyomi.compat")

# Maps a single old-style mode flag to the subcommand words that replace it.
_MODE_FLAG_MAP: dict[str, list[str]] = {
    "--migrate-library":         ["migrate"],
    "--prune-zero-duplicates":   ["prune", "duplicates"],
    "--prune-nonpreferred-langs":["prune", "languages"],
    "--list-categories":         ["list", "categories"],
    "--list-library-titles":     ["list", "library"],
    "--list-lists":              ["list", "sources"],
    "--from-follows":            ["import", "follows"],
    "--import-ids":              ["import", "ids"],
}

# Old flags that map directly to shared parent-level flags.
_FLAG_RENAMES: dict[str, str] = {
    "--md-username": "--md-user",
    "--md-password": "--md-pass",
    "--username":    "--user",
    "--insecure":    "--insecure",  # unchanged, just kept for doc
}


def translate_old_args(argv: List[str]) -> List[str]:
    """Convert pre-Phase-2 flat-flag argv into subcommand form.

    Rules:
    - If the first non-flag argument is already a known subcommand word
      (``migrate``, ``import``, ``prune``, ``list``, ``sync``), return
      unchanged — caller already uses new syntax.
    - Otherwise scan for the first matching mode flag, remove it, and
      prepend the corresponding subcommand.
    - CSV import is detected via ``--from-csv``.
    - A positional that looks like a file path triggers ``import ids``.
    - Logs a deprecation warning (INFO) when translation fires so users
      know to update their scripts.

    Returns the (possibly mutated) argv.
    """
    if not argv:
        return argv

    _SUBCOMMANDS = {"migrate", "import", "prune", "list", "sync"}

    # Already subcommand-style?
    first_non_flag = next((a for a in argv if not a.startswith("-")), None)
    if first_non_flag and first_non_flag in _SUBCOMMANDS:
        return argv

    # Scan for a known mode flag.
    for old_flag, subcmd in _MODE_FLAG_MAP.items():
        if old_flag in argv:
            new_argv = subcmd + [a for a in argv if a != old_flag]
            logger.info(
                "DEPRECATED: '%s' is the old interface. "
                "Use 'seiyomi %s ...' instead.",
                old_flag,
                " ".join(subcmd),
            )
            return new_argv

    # CSV detection via --from-csv
    if "--from-csv" in argv:
        logger.info(
            "DEPRECATED: '--from-csv' is the old interface. "
            "Use 'seiyomi import csv --file ...' instead."
        )
        # Also rename every --from-csv occurrence to --file so the new parser can handle it.
        new_argv: List[str] = []
        for tok in argv:
            new_argv.append("--file" if tok == "--from-csv" else tok)
        return ["import", "csv"] + new_argv

    # Positional file argument → import ids
    if first_non_flag and "." in first_non_flag:
        logger.info(
            "DEPRECATED: positional file argument is the old interface. "
            "Use 'seiyomi import ids %s ...' instead.",
            first_non_flag,
        )
        return ["import", "ids"] + argv

    return argv

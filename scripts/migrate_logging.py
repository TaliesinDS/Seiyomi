"""
Transform print() calls to logger.xxx() calls in the monolith.
Run from the repo root: python scripts/migrate_logging.py
"""
from __future__ import annotations
import re
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "import_mangadex_bookmarks_to_suwayomi_refactored.py"

text = TARGET.read_text(encoding="utf-8")

# ── 1. Add logging import + logger after the existing imports block ──────────
# Plan: insert after the last `import requests` line at the top
OLD_IMPORTS_END = "import requests\n"
NEW_IMPORTS_END = (
    "import requests\n"
    "import logging\n"
)
# Only add once
if "import logging" not in text:
    text = text.replace(OLD_IMPORTS_END, NEW_IMPORTS_END, 1)

# Add logger definition after the module-level constants block
# Insert logger right after the MISSING_REPORT_PATH line
LOGGER_ANCHOR = "MISSING_REPORT_PATH: Optional[Path] = None\n"
LOGGER_INJECT = (
    "MISSING_REPORT_PATH: Optional[Path] = None\n"
    "\n"
    "logger = logging.getLogger(\"seiyomi\")\n"
)
if 'logger = logging.getLogger("seiyomi")' not in text:
    text = text.replace(LOGGER_ANCHOR, LOGGER_INJECT, 1)

# ── 2. Remove try/except print wrappers ─────────────────────────────────────
# Pattern: try:\n    print(...)\nexcept Exception:\n    pass
text = re.sub(
    r'''[ \t]*try:\n([ \t]+)print\(([^\n]*)\)\n\1except Exception:\n\1    pass\n''',
    lambda m: f"{m.group(1)}logger.debug({m.group(2)})\n",
    text,
)

# ── 3. Replace bare print() with logger calls ────────────────────────────────
DEBUG_MARKERS = (
    "read-debug", "csv-debug", "debug", "DEBUG",
    "[fetch", "[search",
)

def classify(args_str: str) -> str:
    """Decide which logger level based on the print content."""
    s = args_str.lower()
    if any(m.lower() in s for m in ("[read-debug]", "[csv-debug]", "[fetch", "[search", "debug")):
        return "debug"
    if any(m in s for m in ("error", "fail", "exception", "traceback", "warn", "could not")):
        if "warn" in s or "WARNING" in args_str:
            return "warning"
        return "error"
    return "info"

def replace_print(m: re.Match) -> str:
    indent = m.group(1)
    args = m.group(2)
    level = classify(args)
    return f"{indent}logger.{level}({args})\n"

# Match standalone print() lines (not inside a try/except we already handled)
text = re.sub(
    r'''^([ \t]*)print\((.+)\)\n''',
    replace_print,
    text,
    flags=re.MULTILINE,
)

# ── 4. Update main() to configure logging and add --verbose flag ─────────────
# Find the argparse setup and inject logging config at top of main()
# Look for the existing parse_args / ArgumentParser block

# Add basicConfig call right after `args = parse_args(argv)` (or equivalent)
# We look for the first `args = parser.parse_args` or similar
OLD_ARGS_PARSE = "    args = parser.parse_args(argv)\n"
NEW_ARGS_PARSE = (
    "    args = parser.parse_args(argv)\n"
    "    logging.basicConfig(\n"
    '        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,\n'
    '        format="%(message)s",\n'
    "    )\n"
)
if "logging.basicConfig" not in text:
    text = text.replace(OLD_ARGS_PARSE, NEW_ARGS_PARSE, 1)

# ── 5. Collapse debug flags into --verbose ───────────────────────────────────
# The 5 debug flags: --debug-login, --debug-follows, --debug-status, --debug-lists, --debug-read-sync
# Keep them as hidden aliases that set verbose=True via dest= pointing to same attr is tricky with argparse
# Simplest: add --verbose/-v flag and add_argument for each old flag with dest="verbose"
VERBOSE_ANCHOR = 'parser.add_argument("--dry-run"'
VERBOSE_INSERT = (
    '    parser.add_argument("--verbose", "-v", action="store_true", default=False,\n'
    '                        help="Show debug-level output.")\n'
    '    # Legacy per-domain debug flags — kept for backward compat, all alias --verbose\n'
    '    for _flag in ("--debug-login", "--debug-follows", "--debug-status", "--debug-lists", "--debug-read-sync"):\n'
    '        parser.add_argument(_flag, dest="verbose", action="store_true", default=False,\n'
    '                            help=argparse.SUPPRESS)\n'
    '    parser.add_argument("--dry-run"'
)
if "--verbose" not in text:
    text = text.replace('    parser.add_argument("--dry-run"', VERBOSE_INSERT, 1)

TARGET.write_text(text, encoding="utf-8")
print("Done.")

# Count remaining bare prints
remaining = sum(1 for line in text.splitlines() if re.match(r'\s*print\(', line))
print(f"Remaining bare print() calls: {remaining}")
logger_calls = sum(1 for line in text.splitlines() if re.match(r'\s*logger\.(info|debug|warning|error)\(', line))
print(f"logger.* calls inserted: {logger_calls}")

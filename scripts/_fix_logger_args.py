"""Fix logger calls that still use print()-style comma-separated args."""
import re
from pathlib import Path

TARGET = Path("import_mangadex_bookmarks_to_suwayomi_refactored.py")
text = TARGET.read_text(encoding="utf-8")

# 1. logger.xxx("...", var, "...") multi-arg calls → f-string
#    Special case: flush=True kwarg (not valid for logger) — strip it
def fix_logger_call(m):
    level = m.group(1)
    raw_args = m.group(2)
    # Strip flush=True / flush=False kwarg
    raw_args = re.sub(r',\s*flush\s*=\s*(True|False)', '', raw_args).strip()
    # If already an f-string or single-arg string, leave alone
    if raw_args.startswith('f"') or raw_args.startswith("f'"):
        return m.group(0)
    # Count top-level commas (skip nested parens/brackets)
    depth = 0
    top_commas = []
    for i, c in enumerate(raw_args):
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        elif c == ',' and depth == 0:
            top_commas.append(i)
    if not top_commas:
        # Single arg or already cleaned — just strip flush=True if present
        return f'logger.{level}({raw_args})'
    # Split on top-level commas
    parts = []
    prev = 0
    for idx in top_commas:
        parts.append(raw_args[prev:idx].strip())
        prev = idx + 1
    parts.append(raw_args[prev:].strip())
    # Build f-string by joining parts:
    # String literals → content; variables → {var}
    pieces = []
    for p in parts:
        if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
            pieces.append(p[1:-1])  # strip quotes
        else:
            pieces.append('{' + p + '}')
    joined = ''.join(pieces)
    return f'logger.{level}(f"{joined}")'

# Apply only to lines that have multi-arg logger calls (avoid multiline edge cases)
lines = text.splitlines(keepends=True)
fixed_count = 0
new_lines = []
for line in lines:
    if re.search(r'logger\.(info|debug|warning|error)\(', line):
        new_line = re.sub(
            r'logger\.(info|debug|warning|error)\((.+)\)',
            fix_logger_call,
            line.rstrip('\n')
        )
        if new_line != line.rstrip('\n'):
            fixed_count += 1
        new_lines.append(new_line + ('\n' if line.endswith('\n') else ''))
    else:
        new_lines.append(line)

TARGET.write_text(''.join(new_lines), encoding='utf-8')
print(f"Fixed {fixed_count} lines")

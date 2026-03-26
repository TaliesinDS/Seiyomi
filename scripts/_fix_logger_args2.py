"""
Properly fix logger() calls that have multi-arg comma-separated style (old print style)
AND fix f-strings that have unmatched parens in Python 3.9 (no nested same-quote).
"""
from __future__ import annotations
import re
from pathlib import Path

TARGET = Path("import_mangadex_bookmarks_to_suwayomi_refactored.py")
lines = TARGET.read_text(encoding="utf-8").splitlines(keepends=True)
changes = 0

def fix_line(line: str) -> str:
    """Fix a single line with a logger call."""
    # Match logger.level( ... )  — single line only
    m = re.match(r'^(\s*)(logger\.(info|debug|warning|error))\((.+)\)\s*$', line.rstrip('\n'))
    if not m:
        return line
    indent, logger_call, level, raw_args = m.group(1), m.group(2), m.group(3), m.group(4)
    
    # Remove flush=True/False kwargs (not valid for logging)
    raw_args = re.sub(r',\s*flush\s*=\s*(True|False)', '', raw_args).strip()
    
    # If already a proper f-string or percent format, leave alone
    if raw_args.startswith('f"') or raw_args.startswith("f'"):
        return line
    if re.match(r'''^["'].*%.*["']''', raw_args):
        return line
    
    # Parse top-level commas (tracking string and bracket depth)
    top_commas = []
    depth = 0
    in_str = None
    i = 0
    while i < len(raw_args):
        c = raw_args[i]
        if in_str:
            if c == '\\':
                i += 2
                continue
            if c == in_str:
                in_str = None
        else:
            if c in ('"', "'"):
                in_str = c
            elif c in '([{':
                depth += 1
            elif c in ')]}':
                depth -= 1
            elif c == ',' and depth == 0:
                top_commas.append(i)
        i += 1
    
    if not top_commas:
        # Single arg
        return f'{indent}{logger_call}({raw_args})\n'
    
    # Split on top-level commas
    parts = []
    prev = 0
    for idx in top_commas:
        parts.append(raw_args[prev:idx].strip())
        prev = idx + 1
    parts.append(raw_args[prev:].strip())
    
    # Build concatenated f-string
    # String literals → their content; everything else → {expr}
    pieces = []
    for p in parts:
        if not p:
            continue
        if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
            # Literal string — insert content directly
            inner = p[1:-1]
            pieces.append(inner)
        else:
            # Expression — wrap in {}
            # Escape any literal { } in pieces we added so far
            pieces.append('{' + p + '}')
    
    joined = ''.join(pieces)
    # Use double-quote f-string; if content has double quotes, use single-quote wrapper
    if '"' in joined and "'" not in joined:
        result = f"{indent}{logger_call}(f'{joined}')\n"
    else:
        # Escape double quotes in plain text portions to avoid syntax error
        result = f'{indent}{logger_call}(f"{joined}")\n'
    return result

# Fix remaining known bad patterns introduced by previous script
KNOWN_FIXES = [
    # f-string with unmatched parens from bad transformation
    (
        r'''logger.info(f"[status-raw] Full statuses JSON (truncated 800 chars):{js_dump[:800] + ("..." if len(js_dump) > 800 else "")}")''',
        r'''logger.info(f"[status-raw] Full statuses JSON (truncated 800 chars): {js_dump[:800] + ('...' if len(js_dump) > 800 else '')}")'''
    ),
]

# Process
new_lines = []
for ln in lines:
    stripped = ln.rstrip('\n')
    # Apply known direct fixes first
    fixed = stripped
    for bad, good in KNOWN_FIXES:
        if bad in fixed:
            fixed = fixed.replace(bad, good)
    if fixed != stripped:
        new_lines.append(fixed + '\n')
        changes += 1
        continue
    
    # Check if this is a multi-arg logger call that needs fixing
    if re.search(r'logger\.(info|debug|warning|error)\(', ln):
        new_ln = fix_line(ln)
        if new_ln != ln:
            changes += 1
            new_lines.append(new_ln)
            continue
    
    new_lines.append(ln)

TARGET.write_text(''.join(new_lines), encoding='utf-8')
print(f"Applied {changes} changes")

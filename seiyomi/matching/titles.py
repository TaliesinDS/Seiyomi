"""Title matching helpers — pure functions, no I/O, no external dependencies."""
from __future__ import annotations

import re
from typing import List

try:
    from rapidfuzz import fuzz as _rfuzz  # type: ignore[import]
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False

_STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'of', 'in', 'on', 'to', 'for',
    'by', 'with', 'as', 'at', 'from', 'now', 'i', 'you', 'we',
    'they', 'is', 'are',
}


def normalize_title_tokens(s: str) -> List[str]:
    """Normalize a title to a list of comparable tokens.

    - Lowercases
    - Strips bracketed/parenthetical noise: (Official), [Color], {whatever}
    - Removes punctuation
    - Collapses whitespace
    - Removes short/stop words
    """
    s = s or ""
    s = s.lower().strip()
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", s)
    s = s.replace("official", " ")
    s = s.replace("colored", " ")
    s = s.replace("colour", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return [t for t in s.split() if len(t) > 1 and t not in _STOPWORDS]


def title_similarity(a: str, b: str) -> float:
    """Similarity score between 0 and 1 for two title strings.

    Uses ``rapidfuzz.fuzz.token_sort_ratio`` when the library is installed
    (faster, higher quality).  Falls back to token Jaccard similarity.
    """
    if _HAS_RAPIDFUZZ:
        return _rfuzz.token_sort_ratio(a or "", b or "") / 100.0
    ta = set(normalize_title_tokens(a))
    tb = set(normalize_title_tokens(b))
    if not ta or not tb:
        return 0.0
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


def is_title_match(
    a: str,
    b: str,
    threshold: float = 0.6,
    strict_exact: bool = False,
) -> bool:
    """Return True when titles *a* and *b* are considered a match.

    With ``strict_exact=True`` only identical normalized forms match.
    Otherwise substring containment and Jaccard similarity are also tested.
    """
    na = " ".join(normalize_title_tokens(a))
    nb = " ".join(normalize_title_tokens(b))
    if not na or not nb:
        return False
    if na == nb:
        return True
    if strict_exact:
        return False
    if na in nb or nb in na:
        return True
    return title_similarity(a, b) >= max(0.0, min(1.0, threshold))


# ---------------------------------------------------------------------------
# Internal underscore aliases kept for backward-compat with the monolith
# (monolith uses _normalize_title_tokens etc.; will be cleaned up in Phase 1.6)
# ---------------------------------------------------------------------------
_normalize_title_tokens = normalize_title_tokens  # noqa: N816
_title_similarity = title_similarity               # noqa: N816
_is_title_match = is_title_match                   # noqa: N816

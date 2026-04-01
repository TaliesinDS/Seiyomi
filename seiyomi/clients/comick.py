"""Comick.dev API client — title search and canonical chapter counts."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from seiyomi.matching.titles import title_similarity

logger = logging.getLogger("seiyomi.comick")

COMICK_API = "https://api.comick.dev/v1.0"

# Comick.dev is behind Cloudflare which blocks Python's requests library based
# on TLS fingerprint.  curl_cffi impersonates a real Chrome TLS stack and
# passes through.  Fall back to plain requests if curl_cffi isn't installed
# (will likely hit 403).
try:
    from curl_cffi import requests as _http  # type: ignore[import]

    _USE_CFFI = True
except Exception:
    import requests as _http  # type: ignore[assignment]

    _USE_CFFI = False


class ComickClient:
    """Lightweight client for the public Comick.dev search API."""

    def __init__(self, timeout: float = 10.0, rpm: int = 30) -> None:
        if _USE_CFFI:
            self._sess = _http.Session(impersonate="chrome")
        else:
            self._sess = _http.Session()
            self._sess.headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
            import sys
            logger.warning(
                "curl_cffi not installed — Comick requests will be blocked by "
                "Cloudflare.  Install it with: pip install curl_cffi  "
                "(python=%s)", sys.executable
            )
        self._timeout = timeout
        self._min_interval = 60.0 / max(rpm, 1)
        self._last_request = 0.0

    def _wait(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.time()

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search Comick for a title. Returns raw result list."""
        self._wait()
        try:
            kwargs: Dict[str, Any] = {
                "params": {"q": query, "limit": limit, "tachiyomi": "true", "page": 1},
                "timeout": self._timeout,
            }
            if _USE_CFFI:
                kwargs["impersonate"] = "chrome"
            resp = self._sess.get(f"{COMICK_API}/search/", **kwargs)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.debug(f"Comick search error for '{query}': {e}")
            return []

    def best_match(
        self,
        title: str,
        threshold: float = 0.6,
    ) -> Optional[Dict[str, Any]]:
        """Find the best Comick match for a title.

        Returns a dict with keys: ``title``, ``slug``, ``last_chapter``,
        ``similarity``, ``hid``, ``status`` — or ``None`` if no match
        passes the threshold.
        """
        results = self.search(title, limit=8)
        if not results:
            return None

        best: Optional[Tuple[float, Dict[str, Any]]] = None
        for item in results:
            comick_title = item.get("title") or ""
            # Check primary title + alt titles
            scores = [title_similarity(title, comick_title)]
            for alt in item.get("md_titles") or []:
                alt_t = alt.get("title") or ""
                if alt_t:
                    scores.append(title_similarity(title, alt_t))
            top_score = max(scores)
            if top_score >= threshold and (best is None or top_score > best[0]):
                best = (top_score, item)

        if best is None:
            return None

        score, item = best
        last_ch = item.get("last_chapter")
        try:
            last_ch = float(last_ch) if last_ch is not None else None
        except (ValueError, TypeError):
            last_ch = None

        return {
            "title": item.get("title") or "",
            "slug": item.get("slug") or "",
            "hid": item.get("hid") or "",
            "last_chapter": last_ch,
            "status": item.get("status"),
            "similarity": round(score, 3),
        }

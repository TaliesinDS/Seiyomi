"""Rejects bin — append-only CSV log for titles that couldn't be matched."""
from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("seiyomi.rejects")

_FIELDNAMES = ["timestamp", "manga_id", "title", "reason", "comick_best", "similarity", "comick_chapters"]


class RejectsBin:
    """Append-only CSV writer for migration rejects.

    Each entry records *why* a title was rejected (no Comick match, low
    similarity, etc.) so the user can review and manually handle them.
    """

    def __init__(self, path: str = "rejects.csv") -> None:
        self._path = path
        self._writer: Optional[csv.DictWriter] = None
        self._file = None

    def _ensure_open(self) -> csv.DictWriter:
        if self._writer is not None:
            return self._writer
        exists = os.path.isfile(self._path) and os.path.getsize(self._path) > 0
        self._file = open(self._path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=_FIELDNAMES)
        if not exists:
            self._writer.writeheader()
        return self._writer

    def log(
        self,
        manga_id: int,
        title: str,
        reason: str,
        comick_best: str = "",
        similarity: float = 0.0,
        comick_chapters: Optional[float] = None,
    ) -> None:
        writer = self._ensure_open()
        writer.writerow({
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "manga_id": manga_id,
            "title": title,
            "reason": reason,
            "comick_best": comick_best,
            "similarity": f"{similarity:.3f}" if similarity else "",
            "comick_chapters": comick_chapters if comick_chapters is not None else "",
        })
        if self._file:
            self._file.flush()

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
            self._writer = None

    @property
    def path(self) -> str:
        return self._path

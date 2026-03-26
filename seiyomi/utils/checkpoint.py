"""Resumable operation checkpoint — JSON-backed record of completed manga IDs.

Usage::

    cp = Checkpoint("migrate")          # stored in <cwd>/.seiyomi_checkpoint_migrate.json
    cp.load()

    for entry in library:
        if cp.done(entry["id"]):
            continue                    # already processed in a previous run
        # ... do work ...
        cp.mark_done(entry["id"])       # written immediately

    cp.clear()                          # call on clean completion

The checkpoint file is intentionally a plain JSON dict so users can inspect or
edit it manually.  Concurrency is single-threaded by design; no locking needed.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set

logger = logging.getLogger("seiyomi")

_DEFAULT_DIR = Path.cwd()


class Checkpoint:
    """Persist IDs of already-completed items across interrupted runs.

    Args:
        operation: Short label used in the filename, e.g. ``"migrate"``.
        directory: Directory for the checkpoint file (default: cwd).
    """

    def __init__(self, operation: str, directory: Optional[Path] = None) -> None:
        self.operation = operation
        self._path = (directory or _DEFAULT_DIR) / f".seiyomi_checkpoint_{operation}.json"
        self._completed: Set[str] = set()
        self._meta: Dict[str, Any] = {}

    # ── Persistence ────────────────────────────────────────────────────────

    def load(self) -> "Checkpoint":
        """Load existing checkpoint from disk (no-op if file absent)."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._completed = set(str(x) for x in (data.get("completed") or []))
                self._meta = data.get("meta") or {}
                logger.info(
                    f"[checkpoint] Resuming {self.operation}: "
                    f"{len(self._completed)} items already done"
                )
            except Exception as exc:
                logger.warning(f"[checkpoint] Could not load {self._path}: {exc}")
        return self

    def _flush(self) -> None:
        try:
            payload = {
                "operation": self.operation,
                "meta": self._meta,
                "completed": sorted(self._completed),
            }
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"[checkpoint] Write failed: {exc}")

    # ── API ────────────────────────────────────────────────────────────────

    def done(self, item_id: Any) -> bool:
        """Return True if *item_id* was already completed."""
        return str(item_id) in self._completed

    def mark_done(self, item_id: Any) -> None:
        """Record *item_id* as completed and persist immediately."""
        self._completed.add(str(item_id))
        self._flush()

    def clear(self) -> None:
        """Delete the checkpoint file after a clean run."""
        self._completed.clear()
        try:
            if self._path.exists():
                self._path.unlink()
        except Exception as exc:
            logger.warning(f"[checkpoint] Could not delete {self._path}: {exc}")

    @property
    def count(self) -> int:
        return len(self._completed)

    @property
    def path(self) -> Path:
        return self._path

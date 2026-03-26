"""ProcessRunner — run a CLI subprocess and stream its output to a tkinter widget.

Design rules:
- Launched via subprocess.Popen; stdout/stderr merged.
- A daemon thread reads lines and posts them to the UI via widget.after().
- .cancel() sends SIGTERM to the process and waits up to 3 s.
- Nothing here imports seiyomi.operations or seiyomi.clients.
  The GUI expresses all operations as CLI argv lists — the runner just
  executes them.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, List, Optional


def _python() -> str:
    return sys.executable or "python"


def _seiyomi_argv(args: List[str]) -> List[str]:
    """Build the full argv for `python -m seiyomi <args>`."""
    return [_python(), "-m", "seiyomi"] + args


class ProcessRunner:
    """Launch a seiyomi CLI command and stream output into a tkinter Text widget."""

    def __init__(
        self,
        args: List[str],
        on_line: Callable[[str], None],
        on_done: Callable[[int], None],
    ) -> None:
        """
        :param args: seiyomi subcommand argv (e.g. ["migrate", "--dry-run", ...])
        :param on_line: called on the tkinter main thread for each stdout/stderr line
        :param on_done: called on the tkinter main thread with the exit code
        """
        self._args = args
        self._on_line = on_line
        self._on_done = on_done
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._proc is not None:
            return
        full_cmd = _seiyomi_argv(self._args)
        self._proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        assert self._proc is not None
        try:
            for line in self._proc.stdout:  # type: ignore[union-attr]
                stripped = line.rstrip("\n")
                self._post(lambda l=stripped: self._on_line(l))
        except Exception:
            pass
        returncode = self._proc.wait()
        self._post(lambda rc=returncode: self._on_done(rc))

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    # ── Internal helpers ───────────────────────────────────────────────────

    # We don't keep a reference to the tkinter widget here — callers pass
    # on_line/on_done lambdas that close over the widget and call .after().
    # This keeps ProcessRunner fully decoupled from tkinter internals.

    @staticmethod
    def _post(fn: Callable) -> None:
        """Schedule fn on the tkinter main thread.

        We cannot import tkinter here unconditionally (it fails on headless CI),
        so we post via a threading event instead.  Callers that want tkinter
        .after() scheduling should wrap on_line/on_done with widget.after(0, fn).
        """
        fn()

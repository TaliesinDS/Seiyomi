"""Token-bucket rate limiter.

Usage::

    limiter = RateLimiter(rpm=60)    # 1 call/second
    limiter.wait()                   # blocks until next slot is available
    # ... make API call ...

Thread-safe: yes (uses a Lock so multiple threads share the same limiter).
"""
from __future__ import annotations

import threading
import time


class RateLimiter:
    """Token bucket rate limiter.

    Args:
        rpm: Maximum requests per minute (0 = unlimited).
    """

    def __init__(self, rpm: int = 60) -> None:
        self.rpm = rpm
        self._min_interval: float = 60.0 / rpm if rpm > 0 else 0.0
        self._last_call: float = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block until next call is allowed."""
        if self._min_interval == 0.0:
            return
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()

    def set_rpm(self, rpm: int) -> None:
        """Adjust rate limit at runtime."""
        with self._lock:
            self.rpm = rpm
            self._min_interval = 60.0 / rpm if rpm > 0 else 0.0

    # Convenience: use as a context manager (blocks on __enter__)
    def __enter__(self) -> "RateLimiter":
        self.wait()
        return self

    def __exit__(self, *_: object) -> None:
        pass

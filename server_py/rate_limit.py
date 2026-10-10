"""Reusable in-memory sliding-window rate limiter.

Suitable for single-process deployments. For multi-instance deployments
replace with a Redis-backed implementation.
"""
from __future__ import annotations

import time
from typing import Dict, List


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: float, max_keys: int = 10000):
        self.max_requests = max_requests
        self.window_ms = window_seconds * 1000
        self.max_keys = max_keys
        self._log: Dict[str, List[float]] = {}

    def _prune(self, now: float) -> None:
        for key in list(self._log.keys()):
            recent = [t for t in self._log[key] if now - t < self.window_ms]
            if recent:
                self._log[key] = recent
            else:
                del self._log[key]

    def allow(self, key: str) -> bool:
        now = time.time() * 1000
        recent = [t for t in self._log.get(key, []) if now - t < self.window_ms]
        if len(recent) >= self.max_requests:
            return False
        if key not in self._log and len(self._log) >= self.max_keys:
            self._prune(now)
        recent.append(now)
        self._log[key] = recent
        return True

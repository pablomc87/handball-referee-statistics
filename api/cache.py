"""Simple thread-safe in-memory cache with optional TTL."""
import threading
import time
from typing import Any

_FOREVER = float("inf")


class _Cache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at != _FOREVER and time.monotonic() > expires_at:
            self.invalidate(key)
            return None
        return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        expires_at = _FOREVER if ttl is None else time.monotonic() + ttl
        with self._lock:
            self._store[key] = (value, expires_at)

    def invalidate(self, key: str | None = None) -> None:
        with self._lock:
            if key:
                self._store.pop(key, None)
            else:
                self._store.clear()


cache = _Cache()

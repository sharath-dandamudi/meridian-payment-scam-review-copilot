"""Small bounded TTL cache for non-authoritative, read-only workflow lookups."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Generic, TypeVar

CacheValue = TypeVar("CacheValue")


@dataclass(frozen=True)
class CacheLookup(Generic[CacheValue]):
    value: CacheValue | None
    hit: bool


class TTLCache(Generic[CacheValue]):
    """In-process cache with explicit expiry and bounded memory usage."""

    def __init__(self, max_entries: int, ttl_seconds: float) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, tuple[float, CacheValue]] = OrderedDict()

    def get(self, key: str) -> CacheLookup[CacheValue]:
        entry = self._entries.get(key)
        if entry is None:
            return CacheLookup(value=None, hit=False)
        expires_at, value = entry
        if monotonic() >= expires_at:
            del self._entries[key]
            return CacheLookup(value=None, hit=False)
        self._entries.move_to_end(key)
        return CacheLookup(value=value, hit=True)

    def put(self, key: str, value: CacheValue) -> None:
        self._entries[key] = (monotonic() + self._ttl_seconds, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

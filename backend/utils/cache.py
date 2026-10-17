import time
import threading
from collections import OrderedDict
from typing import Any, Optional, Tuple

from backend.config import CACHE_MAX_ENTRIES


# (expires_at, value) tuples. OrderedDict gives us O(1) LRU eviction.
_store: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
_lock = threading.Lock()
_hits = 0
_misses = 0


def get(key: str) -> Optional[Any]:
    global _hits, _misses
    with _lock:
        item = _store.get(key)
        if item is None:
            _misses += 1
            return None
        expires, value = item
        if time.time() > expires:
            _store.pop(key, None)
            _misses += 1
            return None
        # LRU touch
        _store.move_to_end(key)
        _hits += 1
        return value


def set(key: str, value: Any, ttl: int) -> None:
    if ttl <= 0:
        return
    with _lock:
        _store[key] = (time.time() + ttl, value)
        _store.move_to_end(key)
        while len(_store) > CACHE_MAX_ENTRIES:
            _store.popitem(last=False)


def delete(key: str) -> bool:
    with _lock:
        return _store.pop(key, None) is not None


def delete_prefix(prefix: str) -> int:
    with _lock:
        victims = [k for k in _store.keys() if k.startswith(prefix)]
        for k in victims:
            _store.pop(k, None)
        return len(victims)


def clear() -> None:
    global _hits, _misses
    with _lock:
        _store.clear()
        _hits = 0
        _misses = 0


def stats() -> dict:
    with _lock:
        total = _hits + _misses
        return {
            "entries": len(_store),
            "max_entries": CACHE_MAX_ENTRIES,
            "hits": _hits,
            "misses": _misses,
            "hit_rate": round(_hits / total, 3) if total else 0.0,
        }
import time
from typing import Any, Dict, Tuple

_store: Dict[str, Tuple[float, Any]] = {}


def get(key: str):
    item = _store.get(key)
    if not item:
        return None
    expires, value = item
    if time.time() > expires:
        _store.pop(key, None)
        return None
    return value


def set(key: str, value: Any, ttl: int):
    _store[key] = (time.time() + ttl, value)


def clear():
    _store.clear()
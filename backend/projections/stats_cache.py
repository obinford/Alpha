"""File-based cache for NBA.com stats to avoid rate limiting.

Player game logs are cached for 6 hours, season averages for 12 hours,
and team defense stats for 24 hours. Stored as JSON in projections/cache/.
"""

import hashlib
import json
import os
import time
from typing import Any

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

# Cache TTLs in seconds.
CACHE_TTL = {
    "game_log": 6 * 3600,       # 6 hours
    "season_avg": 12 * 3600,    # 12 hours
    "team_defense": 24 * 3600,  # 24 hours
    "league_avg": 24 * 3600,    # 24 hours
    "active_players": 24 * 3600,  # 24 hours
}


def _ensure_cache_dir() -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _cache_key(category: str, *args: Any) -> str:
    """Generate a deterministic cache filename."""
    raw = f"{category}:{'|'.join(str(a) for a in args)}"
    h = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"{category}_{h}.json"


def get_cached(category: str, *args: Any) -> Any | None:
    """Return cached data if fresh, else None."""
    _ensure_cache_dir()
    path = os.path.join(_CACHE_DIR, _cache_key(category, *args))
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            entry = json.load(f)
        ttl = CACHE_TTL.get(category, 3600)
        if time.time() - entry.get("ts", 0) > ttl:
            return None
        return entry.get("data")
    except (json.JSONDecodeError, OSError):
        return None


def set_cached(category: str, data: Any, *args: Any) -> None:
    """Write data to cache."""
    _ensure_cache_dir()
    path = os.path.join(_CACHE_DIR, _cache_key(category, *args))
    entry = {"ts": time.time(), "data": data}
    try:
        with open(path, "w") as f:
            json.dump(entry, f)
    except OSError:
        pass


def clear_cache(category: str | None = None) -> int:
    """Clear cache files. If category given, only clear that category."""
    _ensure_cache_dir()
    removed = 0
    for fname in os.listdir(_CACHE_DIR):
        if not fname.endswith(".json"):
            continue
        if category and not fname.startswith(category):
            continue
        try:
            os.remove(os.path.join(_CACHE_DIR, fname))
            removed += 1
        except OSError:
            pass
    return removed

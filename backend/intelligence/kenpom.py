"""KenPom API integration for college basketball intelligence.

Fetches team efficiency ratings, game predictions (fanmatch), and team
metadata from the KenPom API.  Data is cached to avoid redundant calls:
  - Ratings: 6-hour TTL (team-level stats change infrequently)
  - Fanmatch: fetched fresh each cycle for today + tomorrow
  - Teams: 24-hour TTL (roster/name data is mostly static)

The fanmatch endpoint provides KenPom's own predicted scores and win
probabilities, so we use those directly instead of recalculating from
AdjOE/AdjDE.  For games not covered by fanmatch (further out), we fall
back to a manual projection using ratings data.

Team name matching between KenPom and The Odds API uses:
  1. Manual overrides (hardcoded known mismatches)
  2. Fuzzy string matching via difflib
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API configuration
# ---------------------------------------------------------------------------

KENPOM_BASE_URL = "https://kenpom.com/api.php"
KENPOM_API_KEY = os.environ.get(
    "KENPOM_API_KEY",
    "e38e667f8b47e574d924b59965afc5def8b69c7e9b04bc5651b18490d5ba077d",
)

# Cache TTLs (seconds)
_RATINGS_TTL = 6 * 3600      # 6 hours
_TEAMS_TTL = 24 * 3600       # 24 hours

# Average D-I tempo used for fallback projections (possessions per 40 min).
_AVG_TEMPO = 67.5
# Average D-I offensive efficiency (points per 100 possessions).
_AVG_EFFICIENCY = 100.0
# Home-court advantage in efficiency points (KenPom convention).
_HOME_ADVANTAGE = 3.5


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

class _Cache:
    """Simple TTL cache for API responses."""

    def __init__(self) -> None:
        self.ratings: list[dict[str, Any]] = []
        self.ratings_ts: float = 0.0
        self.teams: list[dict[str, Any]] = []
        self.teams_ts: float = 0.0
        # Fanmatch keyed by date string "YYYY-MM-DD"
        self.fanmatch: dict[str, list[dict[str, Any]]] = {}
        self.fanmatch_ts: dict[str, float] = {}
        # Team name map: kenpom_name -> odds_api_name
        self._name_map: dict[str, str] | None = None
        self._name_map_ts: float = 0.0

    def ratings_fresh(self) -> bool:
        return bool(self.ratings) and (time.time() - self.ratings_ts) < _RATINGS_TTL

    def teams_fresh(self) -> bool:
        return bool(self.teams) and (time.time() - self.teams_ts) < _TEAMS_TTL

    def fanmatch_fresh(self, date_str: str) -> bool:
        ts = self.fanmatch_ts.get(date_str, 0.0)
        # Fanmatch is fetched fresh each scan cycle — use a 90-second TTL
        # to deduplicate within the same cycle but always refresh next cycle.
        return date_str in self.fanmatch and (time.time() - ts) < 90


_cache = _Cache()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _make_request(
    endpoint: str,
    params: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> list[dict[str, Any]] | None:
    """Make an authenticated GET request to the KenPom API.

    Returns the parsed JSON response (expected to be a list of dicts),
    or None on any failure.
    """
    if not KENPOM_API_KEY:
        logger.warning("KENPOM_API_KEY not set — skipping KenPom fetch")
        return None

    query: dict[str, str] = {"endpoint": endpoint}
    if params:
        query.update(params)

    headers = {"Authorization": f"Bearer {KENPOM_API_KEY}"}

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(KENPOM_BASE_URL, params=query, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            # Some endpoints may wrap in an object — handle gracefully.
            if isinstance(data, dict):
                # Try common wrapper keys
                for key in ("data", "results", "teams", "ratings"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
                # Single-item response — wrap in list
                return [data]
            logger.warning("KenPom %s returned unexpected type: %s", endpoint, type(data))
            return None
    except httpx.HTTPStatusError as exc:
        logger.error(
            "KenPom API %s returned HTTP %d: %s",
            endpoint, exc.response.status_code, exc.response.text[:200],
        )
        return None
    except Exception as exc:
        logger.error("KenPom API %s request failed: %s", endpoint, exc)
        return None


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_ratings(year: int | None = None) -> list[dict[str, Any]]:
    """Fetch team efficiency ratings from KenPom.

    GET /api.php?endpoint=ratings&y=YYYY
    Returns: TeamName, AdjOE, AdjDE, AdjTempo, AdjEM, RankAdjEM,
             Wins, Losses, ConfShort, etc.

    Results are cached for 6 hours.
    """
    if _cache.ratings_fresh():
        return _cache.ratings

    y = str(year or _current_season_year())
    data = _make_request("ratings", {"y": y})
    if data:
        _cache.ratings = data
        _cache.ratings_ts = time.time()
        logger.info("KenPom ratings fetched: %d teams for %s", len(data), y)
        return data

    # Return stale cache if available rather than empty.
    if _cache.ratings:
        logger.warning("KenPom ratings fetch failed — using stale cache")
        return _cache.ratings
    return []


def fetch_fanmatch(target_date: date | None = None) -> list[dict[str, Any]]:
    """Fetch game predictions from the KenPom fanmatch endpoint.

    GET /api.php?endpoint=fanmatch&d=YYYY-MM-DD
    Returns: Visitor, Home, HomePred, VisitorPred, HomeWP,
             PredTempo, ThrillScore

    These are KenPom's own predicted scores and win probabilities.
    """
    d = target_date or date.today()
    date_str = d.isoformat()

    if _cache.fanmatch_fresh(date_str):
        return _cache.fanmatch[date_str]

    data = _make_request("fanmatch", {"d": date_str})
    if data:
        _cache.fanmatch[date_str] = data
        _cache.fanmatch_ts[date_str] = time.time()
        logger.info("KenPom fanmatch fetched: %d games for %s", len(data), date_str)
        return data

    # Return stale cache if available.
    if date_str in _cache.fanmatch:
        logger.warning("KenPom fanmatch fetch failed — using stale cache for %s", date_str)
        return _cache.fanmatch[date_str]
    return []


def fetch_fanmatch_today_tomorrow() -> list[dict[str, Any]]:
    """Fetch fanmatch data for today and tomorrow, combined.

    Deduplicates games that appear on both days (shouldn't happen, but safe).
    """
    today = date.today()
    tomorrow = today + timedelta(days=1)

    today_games = fetch_fanmatch(today)
    tomorrow_games = fetch_fanmatch(tomorrow)

    # Simple dedup by (Home, Visitor) pair.
    seen: set[tuple[str, str]] = set()
    combined: list[dict[str, Any]] = []
    for game in today_games + tomorrow_games:
        key = (game.get("Home", ""), game.get("Visitor", ""))
        if key not in seen:
            seen.add(key)
            combined.append(game)

    return combined


def fetch_teams(year: int | None = None) -> list[dict[str, Any]]:
    """Fetch team metadata from KenPom.

    GET /api.php?endpoint=teams&y=YYYY
    Returns: TeamName, TeamID, ConfShort, Coach
    """
    if _cache.teams_fresh():
        return _cache.teams

    y = str(year or _current_season_year())
    data = _make_request("teams", {"y": y})
    if data:
        _cache.teams = data
        _cache.teams_ts = time.time()
        logger.info("KenPom teams fetched: %d teams for %s", len(data), y)
        return data

    if _cache.teams:
        logger.warning("KenPom teams fetch failed — using stale cache")
        return _cache.teams
    return []


# ---------------------------------------------------------------------------
# Team name matching
# ---------------------------------------------------------------------------

# Manual overrides for known name mismatches between KenPom and The Odds API.
# Format: KenPom name -> The Odds API name
_MANUAL_NAME_OVERRIDES: dict[str, str] = {
    "UConn": "Connecticut Huskies",
    "St. John's": "St. John's Red Storm",
    "Saint Mary's": "Saint Mary's Gaels",
    "Miami FL": "Miami Hurricanes",
    "Miami OH": "Miami (OH) RedHawks",
    "USC": "USC Trojans",
    "LSU": "LSU Tigers",
    "UCLA": "UCLA Bruins",
    "UNC": "North Carolina Tar Heels",
    "UNLV": "UNLV Rebels",
    "VCU": "VCU Rams",
    "UCF": "UCF Knights",
    "SMU": "SMU Mustangs",
    "BYU": "BYU Cougars",
    "TCU": "TCU Horned Frogs",
    "Ole Miss": "Ole Miss Rebels",
    "Mississippi St.": "Mississippi State Bulldogs",
    "Penn St.": "Penn State Nittany Lions",
    "Ohio St.": "Ohio State Buckeyes",
    "Michigan St.": "Michigan State Spartans",
    "Iowa St.": "Iowa State Cyclones",
    "Kansas St.": "Kansas State Wildcats",
    "Oklahoma St.": "Oklahoma State Cowboys",
    "Arizona St.": "Arizona State Sun Devils",
    "Oregon St.": "Oregon State Beavers",
    "Washington St.": "Washington State Cougars",
    "Colorado St.": "Colorado State Rams",
    "Boise St.": "Boise State Broncos",
    "Fresno St.": "Fresno State Bulldogs",
    "San Diego St.": "San Diego St Aztecs",
    "San Jose St.": "San Jose State Spartans",
    "N.C. State": "NC State Wolfpack",
    "Florida St.": "Florida State Seminoles",
    "Georgia Tech": "Georgia Tech Yellow Jackets",
    "Virginia Tech": "Virginia Tech Hokies",
    "Boston College": "Boston College Eagles",
    "Wake Forest": "Wake Forest Demon Deacons",
    "West Virginia": "West Virginia Mountaineers",
    "Pitt": "Pittsburgh Panthers",
    "Louisville": "Louisville Cardinals",
    "Gonzaga": "Gonzaga Bulldogs",
    "Villanova": "Villanova Wildcats",
    "Creighton": "Creighton Bluejays",
    "Marquette": "Marquette Golden Eagles",
    "Xavier": "Xavier Musketeers",
    # --- 20 unmatched teams from Odds API alignment ---
    "Charleston Southern": "Charleston Southern Buccaneers",
    "Buffalo": "Buffalo Bulls",
    "Central Michigan": "Central Michigan Chippewas",
    "Akron": "Akron Zips",
    "Ball State": "Ball State Cardinals",
    "Bowling Green": "Bowling Green Falcons",
    "Kent St.": "Kent State Golden Flashes",
    "Massachusetts": "Massachusetts Minutemen",
    "Saint Louis": "Saint Louis Billikens",
    "Wisconsin": "Wisconsin Badgers",
    "Southeast Missouri St.": "SE Missouri St Redhawks",
    "New Mexico": "New Mexico Lobos",
    "Air Force": "Air Force Falcons",
    "Iowa": "Iowa Hawkeyes",
    "Nebraska": "Nebraska Cornhuskers",
    "Grand Canyon": "Grand Canyon Antelopes",
    "Nevada": "Nevada Wolf Pack",
    "Minnesota": "Minnesota Golden Gophers",
}


def _normalize_name(name: str) -> str:
    """Normalize a team name for fuzzy matching."""
    return name.strip().lower().replace(".", "").replace("'", "").replace("-", " ")


def _fuzzy_match(kenpom_name: str, odds_api_names: list[str], threshold: float = 0.55) -> str | None:
    """Find the best fuzzy match for a KenPom team name among Odds API names.

    Returns the matched Odds API name, or None if no match exceeds threshold.
    """
    normalized = _normalize_name(kenpom_name)
    best_match: str | None = None
    best_score = 0.0

    for oa_name in odds_api_names:
        oa_normalized = _normalize_name(oa_name)
        score = SequenceMatcher(None, normalized, oa_normalized).ratio()
        if score > best_score:
            best_score = score
            best_match = oa_name

        # Also check if the KenPom name is a substring of the Odds API name.
        if normalized in oa_normalized or oa_normalized in normalized:
            score = max(score, 0.85)
            if score > best_score:
                best_score = score
                best_match = oa_name

    if best_score >= threshold and best_match is not None:
        return best_match
    return None


def build_name_map(odds_api_teams: list[str]) -> dict[str, str]:
    """Build a mapping from KenPom team names to The Odds API team names.

    Uses the teams endpoint for the full list of KenPom names, then
    applies manual overrides and fuzzy matching.

    Args:
        odds_api_teams: List of team names as they appear in The Odds API.

    Returns:
        Dict mapping KenPom TeamName -> Odds API team name.
    """
    # Check cache.
    if _cache._name_map is not None and (time.time() - _cache._name_map_ts) < _TEAMS_TTL:
        return _cache._name_map

    teams = fetch_teams()
    kenpom_names = [t.get("TeamName", "") for t in teams if t.get("TeamName")]

    name_map: dict[str, str] = {}

    for kp_name in kenpom_names:
        # 1. Manual override
        if kp_name in _MANUAL_NAME_OVERRIDES:
            name_map[kp_name] = _MANUAL_NAME_OVERRIDES[kp_name]
            continue

        # 2. Exact match (case-insensitive)
        kp_lower = kp_name.lower()
        exact = next((oa for oa in odds_api_teams if oa.lower() == kp_lower), None)
        if exact:
            name_map[kp_name] = exact
            continue

        # 3. Fuzzy match
        matched = _fuzzy_match(kp_name, odds_api_teams)
        if matched:
            name_map[kp_name] = matched

    _cache._name_map = name_map
    _cache._name_map_ts = time.time()
    logger.info(
        "KenPom name map built: %d/%d teams matched",
        len(name_map), len(kenpom_names),
    )
    return name_map


def resolve_team_name(kenpom_name: str, odds_api_teams: list[str] | None = None) -> str:
    """Resolve a single KenPom team name to its Odds API equivalent.

    Falls back to the original name if no match is found.
    """
    # Manual override first (fast path).
    if kenpom_name in _MANUAL_NAME_OVERRIDES:
        return _MANUAL_NAME_OVERRIDES[kenpom_name]

    # Use cached name map if available.
    if _cache._name_map is not None:
        return _cache._name_map.get(kenpom_name, kenpom_name)

    # Build map if we have odds_api_teams.
    if odds_api_teams:
        name_map = build_name_map(odds_api_teams)
        return name_map.get(kenpom_name, kenpom_name)

    return kenpom_name


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------

def get_fanmatch_prediction(
    home_team: str,
    away_team: str,
    odds_api_teams: list[str] | None = None,
) -> dict[str, Any] | None:
    """Look up KenPom's fanmatch prediction for a specific game.

    Searches today's and tomorrow's fanmatch data for a game matching
    the given team names (with name resolution applied).

    Returns a dict with:
        home_pred: float   — predicted home score
        away_pred: float   — predicted away score
        home_wp: float     — home win probability (0-1)
        pred_tempo: float  — predicted game tempo
        source: str        — "kenpom_fanmatch"
    Or None if the game is not found.
    """
    fanmatch_games = fetch_fanmatch_today_tomorrow()
    if not fanmatch_games:
        return None

    # Build name map for resolution.
    if odds_api_teams:
        build_name_map(odds_api_teams)

    # Try to match by resolving Odds API names back to KenPom names,
    # or by matching KenPom names to Odds API names.
    for game in fanmatch_games:
        kp_home = game.get("Home", "")
        kp_visitor = game.get("Visitor", "")

        # Resolve KenPom names to Odds API names.
        resolved_home = resolve_team_name(kp_home, odds_api_teams)
        resolved_visitor = resolve_team_name(kp_visitor, odds_api_teams)

        # Check for match (case-insensitive).
        home_match = (
            _normalize_name(resolved_home) == _normalize_name(home_team)
            or _normalize_name(kp_home) == _normalize_name(home_team)
        )
        away_match = (
            _normalize_name(resolved_visitor) == _normalize_name(away_team)
            or _normalize_name(kp_visitor) == _normalize_name(away_team)
        )

        if home_match and away_match:
            try:
                home_pred = float(game.get("HomePred", 0))
                away_pred = float(game.get("VisitorPred", 0))
                home_wp = float(game.get("HomeWP", 0.5))
                # HomeWP might be a percentage (e.g. 65.3) or a fraction (0.653)
                if home_wp > 1.0:
                    home_wp = home_wp / 100.0
                pred_tempo = float(game.get("PredTempo", _AVG_TEMPO))
                return {
                    "home_pred": home_pred,
                    "away_pred": away_pred,
                    "home_wp": home_wp,
                    "away_wp": 1.0 - home_wp,
                    "pred_tempo": pred_tempo,
                    "thrill_score": game.get("ThrillScore"),
                    "source": "kenpom_fanmatch",
                }
            except (ValueError, TypeError) as exc:
                logger.warning("Failed to parse fanmatch data for %s vs %s: %s", home_team, away_team, exc)
                return None

    return None


def get_ratings_projection(
    home_team: str,
    away_team: str,
    odds_api_teams: list[str] | None = None,
) -> dict[str, Any] | None:
    """Calculate a projection from KenPom ratings (fallback when fanmatch unavailable).

    Uses AdjOE/AdjDE/AdjTempo to estimate scores and win probability.
    This is less accurate than fanmatch but works for games further out.

    Formula (per KenPom methodology):
        expected_tempo = (home_tempo * away_tempo) / avg_tempo
        home_points = (home_adjoe * away_adjde / avg_eff) * (expected_tempo / 100) + hca
        away_points = (away_adjoe * home_adjde / avg_eff) * (expected_tempo / 100)
        Margin = home_points - away_points
        Win probability estimated from margin using a logistic approximation.

    Returns the same shape as get_fanmatch_prediction, or None.
    """
    ratings = fetch_ratings()
    if not ratings:
        return None

    # Build lookup by team name.
    ratings_by_name: dict[str, dict[str, Any]] = {}
    for team in ratings:
        name = team.get("TeamName", "")
        if name:
            ratings_by_name[name] = team
            # Also index by normalized name for fuzzy lookup.
            ratings_by_name[_normalize_name(name)] = team

    # Find home team ratings.
    home_ratings = _find_team_ratings(home_team, ratings_by_name, odds_api_teams)
    away_ratings = _find_team_ratings(away_team, ratings_by_name, odds_api_teams)

    if home_ratings is None or away_ratings is None:
        return None

    try:
        home_adjoe = float(home_ratings.get("AdjOE", _AVG_EFFICIENCY))
        home_adjde = float(home_ratings.get("AdjDE", _AVG_EFFICIENCY))
        home_tempo = float(home_ratings.get("AdjTempo", _AVG_TEMPO))
        away_adjoe = float(away_ratings.get("AdjOE", _AVG_EFFICIENCY))
        away_adjde = float(away_ratings.get("AdjDE", _AVG_EFFICIENCY))
        away_tempo = float(away_ratings.get("AdjTempo", _AVG_TEMPO))
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to parse ratings for %s vs %s: %s", home_team, away_team, exc)
        return None

    # Expected game tempo.
    expected_tempo = (home_tempo * away_tempo) / _AVG_TEMPO

    # Expected points (per 100 possessions, scaled to game tempo).
    possessions = expected_tempo / 100.0
    home_points = (home_adjoe * away_adjde / _AVG_EFFICIENCY) * possessions + _HOME_ADVANTAGE
    away_points = (away_adjoe * home_adjde / _AVG_EFFICIENCY) * possessions

    # Margin and win probability via logistic approximation.
    margin = home_points - away_points
    # KenPom-style: ~11 points of margin ≈ 1 standard deviation
    # Using logistic function with scale factor.
    home_wp = _margin_to_win_prob(margin)

    return {
        "home_pred": round(home_points, 1),
        "away_pred": round(away_points, 1),
        "home_wp": round(home_wp, 4),
        "away_wp": round(1.0 - home_wp, 4),
        "pred_tempo": round(expected_tempo, 1),
        "margin": round(margin, 1),
        "source": "kenpom_ratings",
    }


def get_projection(
    home_team: str,
    away_team: str,
    odds_api_teams: list[str] | None = None,
) -> dict[str, Any] | None:
    """Get the best available KenPom projection for a game.

    Tries fanmatch first (direct KenPom predictions), then falls back
    to calculating from ratings.

    Returns a projection dict or None if no data is available.
    """
    # Try fanmatch first — it has KenPom's own predictions.
    prediction = get_fanmatch_prediction(home_team, away_team, odds_api_teams)
    if prediction is not None:
        return prediction

    # Fall back to ratings-based projection.
    return get_ratings_projection(home_team, away_team, odds_api_teams)


def get_team_rating(team_name: str, odds_api_teams: list[str] | None = None) -> dict[str, Any] | None:
    """Get KenPom ratings for a single team.

    Returns a dict with AdjOE, AdjDE, AdjTempo, AdjEM, RankAdjEM, etc.
    or None if the team is not found.
    """
    ratings = fetch_ratings()
    if not ratings:
        return None

    ratings_by_name: dict[str, dict[str, Any]] = {}
    for team in ratings:
        name = team.get("TeamName", "")
        if name:
            ratings_by_name[name] = team
            ratings_by_name[_normalize_name(name)] = team

    return _find_team_ratings(team_name, ratings_by_name, odds_api_teams)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _current_season_year() -> int:
    """Return the current CBB season year.

    The season spans two calendar years (e.g. 2025-26 season).
    KenPom uses the later year (2026) as the season identifier.
    Before August, it's the current year; August onward, it's next year.
    """
    today = date.today()
    if today.month >= 8:
        return today.year + 1
    return today.year


def _find_team_ratings(
    team_name: str,
    ratings_by_name: dict[str, dict[str, Any]],
    odds_api_teams: list[str] | None = None,
) -> dict[str, Any] | None:
    """Find ratings for a team by name, trying various resolution strategies."""
    # Direct lookup.
    if team_name in ratings_by_name:
        return ratings_by_name[team_name]

    # Normalized lookup.
    normalized = _normalize_name(team_name)
    if normalized in ratings_by_name:
        return ratings_by_name[normalized]

    # Try reverse name map: odds_api_name -> kenpom_name.
    if _cache._name_map:
        reverse_map = {v: k for k, v in _cache._name_map.items()}
        kp_name = reverse_map.get(team_name)
        if kp_name and kp_name in ratings_by_name:
            return ratings_by_name[kp_name]

    # Try manual overrides in reverse.
    reverse_overrides = {v: k for k, v in _MANUAL_NAME_OVERRIDES.items()}
    kp_name = reverse_overrides.get(team_name)
    if kp_name and kp_name in ratings_by_name:
        return ratings_by_name[kp_name]

    # Fuzzy match against all KenPom names in the ratings.
    kp_names = [n for n in ratings_by_name if not n.islower() or " " in n]
    matched = _fuzzy_match(team_name, kp_names, threshold=0.6)
    if matched and matched in ratings_by_name:
        return ratings_by_name[matched]

    return None


def _margin_to_win_prob(margin: float) -> float:
    """Convert a point margin to a win probability using logistic function.

    Calibrated to KenPom's typical spread-to-probability relationship:
    ~11 points ≈ 1 standard deviation in CBB.
    """
    import math
    # Logistic function: P = 1 / (1 + exp(-k * margin))
    # k chosen so that margin=11 gives ~84% win prob (1 SD).
    k = 0.1475
    try:
        return 1.0 / (1.0 + math.exp(-k * margin))
    except OverflowError:
        return 1.0 if margin > 0 else 0.0


def clear_cache() -> None:
    """Clear all cached KenPom data. Useful for testing."""
    global _cache
    _cache = _Cache()

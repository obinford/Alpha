"""MLB stats scraper using pybaseball."""


def fetch_pitcher_stats(season: int) -> list[dict]:
    """Fetch pitcher stats for a given season.

    Args:
        season: MLB season year.

    Returns:
        List of pitcher stat dicts.
    """
    raise NotImplementedError


def fetch_team_stats(season: int) -> list[dict]:
    """Fetch team-level stats for a given season.

    Args:
        season: MLB season year.

    Returns:
        List of team stat dicts.
    """
    raise NotImplementedError

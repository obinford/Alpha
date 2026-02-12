/** Shared configuration constants for the RTM Picks Platform. */

export const SUPPORTED_SPORTS = [
  "MLB",
  "NBA",
  "NFL",
  "NHL",
  "CFB",
  "CBB",
] as const;

export type Sport = (typeof SUPPORTED_SPORTS)[number];

export const ODDS_API_SPORT_KEYS: Record<Sport, string> = {
  MLB: "baseball_mlb",
  NBA: "basketball_nba",
  NFL: "americanfootball_nfl",
  NHL: "icehockey_nhl",
  CFB: "americanfootball_ncaaf",
  CBB: "basketball_ncaab",
};

export const SHARP_BOOKS = ["pinnacle", "circa"] as const;

export const MARKETS = ["h2h", "spreads", "totals"] as const;

/** Fractional Kelly multiplier (0.25 = quarter Kelly) */
export const DEFAULT_KELLY_FRACTION = 0.25;

/** Minimum EV threshold to surface a pick (percentage) */
export const MIN_EV_THRESHOLD = 2.0;

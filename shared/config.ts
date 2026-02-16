/** Shared configuration constants for the RTM Picks Platform. */

export const SUPPORTED_SPORTS = [
  "MLB",
  "NBA",
  "NFL",
  "NHL",
  "CFB",
  "CBB",
  "WNBA",
  "ATP_AUS_OPEN",
  "ATP_FRENCH_OPEN",
  "ATP_WIMBLEDON",
  "ATP_US_OPEN",
  "WTA_AUS_OPEN",
  "WTA_FRENCH_OPEN",
  "WTA_WIMBLEDON",
  "WTA_US_OPEN",
] as const;

export type Sport = (typeof SUPPORTED_SPORTS)[number];

export const ODDS_API_SPORT_KEYS: Record<Sport, string> = {
  MLB: "baseball_mlb",
  NBA: "basketball_nba",
  NFL: "americanfootball_nfl",
  NHL: "icehockey_nhl",
  CFB: "americanfootball_ncaaf",
  CBB: "basketball_ncaab",
  WNBA: "basketball_wnba",
  ATP_AUS_OPEN: "tennis_atp_aus_open",
  ATP_FRENCH_OPEN: "tennis_atp_french_open",
  ATP_WIMBLEDON: "tennis_atp_wimbledon",
  ATP_US_OPEN: "tennis_atp_us_open",
  WTA_AUS_OPEN: "tennis_wta_aus_open",
  WTA_FRENCH_OPEN: "tennis_wta_french_open",
  WTA_WIMBLEDON: "tennis_wta_wimbledon",
  WTA_US_OPEN: "tennis_wta_us_open",
};

export const SHARP_BOOKS = ["pinnacle", "circa", "bookmaker"] as const;

export const MARKETS = ["h2h", "spreads", "totals"] as const;

/** Fractional Kelly multiplier (0.25 = quarter Kelly) */
export const DEFAULT_KELLY_FRACTION = 0.25;

/** Minimum EV threshold to surface a pick (percentage) */
export const MIN_EV_THRESHOLD = 2.0;

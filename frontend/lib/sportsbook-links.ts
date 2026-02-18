/**
 * Sportsbook deep-link URLs.
 * Used to generate "Bet →" buttons on book rows across all pages.
 *
 * Sport-specific pages take the user to the right league page instead of
 * a generic homepage.  When a sport-specific page isn't mapped, falls
 * back to the homepage.
 */

/** Homepage fallbacks — used when no sport-specific page is available. */
const SPORTSBOOK_URLS: Record<string, string> = {
  draftkings: "https://sportsbook.draftkings.com",
  fanduel: "https://sportsbook.fanduel.com",
  betmgm: "https://sports.betmgm.com",
  betrivers: "https://www.betrivers.com",
  bovada: "https://www.bovada.lv",
  betonlineag: "https://www.betonline.ag",
  fanatics: "https://sportsbook.fanatics.com",
  espnbet: "https://espnbet.com",
  hardrockbet: "https://www.hardrock.bet",
  ballybet: "https://www.ballybet.com",
  fliff: "https://www.getfliff.com",
  mybookieag: "https://www.mybookie.ag",
  betus: "https://www.betus.com.pa",
  novig: "https://www.novig.com",
  rebet: "https://rebet.app",
  pinnacle: "https://www.pinnacle.com",
  kalshi: "https://kalshi.com",
  polymarket: "https://polymarket.com",
};

/**
 * Sport-specific pages per sportsbook.
 * Keys are Odds API sport keys (e.g. "basketball_ncaab").
 */
const SPORT_PAGES: Record<string, Record<string, string>> = {
  draftkings: {
    basketball_nba: "https://sportsbook.draftkings.com/leagues/basketball/nba",
    basketball_ncaab: "https://sportsbook.draftkings.com/leagues/basketball/ncaab",
    icehockey_nhl: "https://sportsbook.draftkings.com/leagues/hockey/nhl",
    americanfootball_nfl: "https://sportsbook.draftkings.com/leagues/football/nfl",
    americanfootball_ncaaf: "https://sportsbook.draftkings.com/leagues/football/college-football",
    baseball_mlb: "https://sportsbook.draftkings.com/leagues/baseball/mlb",
  },
  fanduel: {
    basketball_nba: "https://sportsbook.fanduel.com/basketball",
    basketball_ncaab: "https://sportsbook.fanduel.com/college-basketball",
    icehockey_nhl: "https://sportsbook.fanduel.com/hockey",
    americanfootball_nfl: "https://sportsbook.fanduel.com/football",
    americanfootball_ncaaf: "https://sportsbook.fanduel.com/college-football",
    baseball_mlb: "https://sportsbook.fanduel.com/baseball",
  },
  betmgm: {
    basketball_nba: "https://sports.betmgm.com/en/sports/basketball-7/betting/usa-9/nba-6004",
    basketball_ncaab: "https://sports.betmgm.com/en/sports/basketball-7/betting/usa-9/college-basketball-264",
    icehockey_nhl: "https://sports.betmgm.com/en/sports/ice-hockey-12/betting/usa-9/nhl-34",
    americanfootball_nfl: "https://sports.betmgm.com/en/sports/football-11/betting/usa-9/nfl-35",
    americanfootball_ncaaf: "https://sports.betmgm.com/en/sports/football-11/betting/usa-9/college-football-211",
    baseball_mlb: "https://sports.betmgm.com/en/sports/baseball-23/betting/usa-9/mlb-75",
  },
  espnbet: {
    basketball_nba: "https://espnbet.com/sport/basketball/organization/nba",
    basketball_ncaab: "https://espnbet.com/sport/basketball/organization/ncaab",
    icehockey_nhl: "https://espnbet.com/sport/hockey/organization/nhl",
    americanfootball_nfl: "https://espnbet.com/sport/football/organization/nfl",
    americanfootball_ncaaf: "https://espnbet.com/sport/football/organization/ncaaf",
    baseball_mlb: "https://espnbet.com/sport/baseball/organization/mlb",
  },
  fanatics: {
    basketball_nba: "https://sportsbook.fanatics.com/basketball/nba",
    basketball_ncaab: "https://sportsbook.fanatics.com/basketball/college-basketball",
    icehockey_nhl: "https://sportsbook.fanatics.com/hockey/nhl",
    americanfootball_nfl: "https://sportsbook.fanatics.com/football/nfl",
    americanfootball_ncaaf: "https://sportsbook.fanatics.com/football/college-football",
    baseball_mlb: "https://sportsbook.fanatics.com/baseball/mlb",
  },
  betrivers: {
    basketball_nba: "https://www.betrivers.com/sports/basketball/nba",
    basketball_ncaab: "https://www.betrivers.com/sports/basketball/ncaab",
    icehockey_nhl: "https://www.betrivers.com/sports/ice-hockey/nhl",
    americanfootball_nfl: "https://www.betrivers.com/sports/football/nfl",
    americanfootball_ncaaf: "https://www.betrivers.com/sports/football/ncaaf",
    baseball_mlb: "https://www.betrivers.com/sports/baseball/mlb",
  },
  hardrockbet: {
    basketball_nba: "https://www.hardrock.bet/sports/basketball/nba",
    basketball_ncaab: "https://www.hardrock.bet/sports/basketball/ncaab",
    icehockey_nhl: "https://www.hardrock.bet/sports/hockey/nhl",
    americanfootball_nfl: "https://www.hardrock.bet/sports/football/nfl",
    americanfootball_ncaaf: "https://www.hardrock.bet/sports/football/ncaaf",
    baseball_mlb: "https://www.hardrock.bet/sports/baseball/mlb",
  },
  bovada: {
    basketball_nba: "https://www.bovada.lv/sports/basketball/nba",
    basketball_ncaab: "https://www.bovada.lv/sports/basketball/college-basketball",
    icehockey_nhl: "https://www.bovada.lv/sports/hockey",
    americanfootball_nfl: "https://www.bovada.lv/sports/football/nfl",
    americanfootball_ncaaf: "https://www.bovada.lv/sports/football/college-football",
    baseball_mlb: "https://www.bovada.lv/sports/baseball",
  },
  pinnacle: {
    basketball_nba: "https://www.pinnacle.com/basketball/nba/matchups",
    basketball_ncaab: "https://www.pinnacle.com/basketball/ncaa/matchups",
    icehockey_nhl: "https://www.pinnacle.com/hockey/nhl/matchups",
    americanfootball_nfl: "https://www.pinnacle.com/football/nfl/matchups",
    americanfootball_ncaaf: "https://www.pinnacle.com/football/ncaa/matchups",
    baseball_mlb: "https://www.pinnacle.com/baseball/mlb/matchups",
  },
};

/**
 * Get the best available URL for a sportsbook.
 *
 * If a sport key is provided, returns the sport-specific page for that book.
 * Falls back to the sportsbook homepage if no sport-specific page exists.
 */
export function getSportsbookUrl(bookKey: string, sport?: string): string | null {
  const key = bookKey.toLowerCase();

  // Try sport-specific page first.
  if (sport) {
    const sportUrl = SPORT_PAGES[key]?.[sport];
    if (sportUrl) return sportUrl;
  }

  return SPORTSBOOK_URLS[key] ?? null;
}

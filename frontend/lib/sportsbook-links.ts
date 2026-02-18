/**
 * Sportsbook deep-link URLs.
 * Used to generate "Bet →" buttons on book rows across all pages.
 */

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
};

/** Get the sportsbook homepage URL, or null if not mapped. */
export function getSportsbookUrl(bookKey: string): string | null {
  return SPORTSBOOK_URLS[bookKey.toLowerCase()] ?? null;
}

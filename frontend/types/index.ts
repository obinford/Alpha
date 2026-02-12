export interface Pick {
  id: string;
  sport: string;
  game: string;
  market: string;
  selection: string;
  odds: number;
  ev_percentage: number;
  units: number;
  timestamp: string;
  result?: "win" | "loss" | "push" | "pending";
}

export interface OddsLine {
  id: string;
  sport: string;
  game: string;
  market: string;
  sportsbook: string;
  selection: string;
  odds: number;
  timestamp: string;
}

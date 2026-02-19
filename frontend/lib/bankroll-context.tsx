"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type KellyMultiplier = 1.0 | 0.5 | 0.25 | 0.125;

export interface BankrollSettings {
  bankroll: number | null; // dollar amount, null = not set
  kellyMultiplier: KellyMultiplier;
}

interface BankrollContextValue extends BankrollSettings {
  /** 1 unit = 1% of bankroll */
  unitSize: number | null;
  setBankroll: (amount: number | null) => void;
  setKellyMultiplier: (m: KellyMultiplier) => void;
  /** Calculate kelly bet size: kelly_fraction * kellyMultiplier * bankroll */
  kellyBetSize: (kellyFraction: number) => number | null;
  kellyLabel: string;
}

const STORAGE_KEY = "rtm_bankroll";

const KELLY_LABELS: Record<number, string> = {
  1.0: "Full Kelly",
  0.5: "Half Kelly",
  0.25: "Quarter Kelly",
  0.125: "Eighth Kelly",
};

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const BankrollContext = createContext<BankrollContextValue>({
  bankroll: 1000,
  kellyMultiplier: 0.5,
  unitSize: 10,
  setBankroll: () => {},
  setKellyMultiplier: () => {},
  kellyBetSize: () => null,
  kellyLabel: "Half Kelly",
});

export function useBankroll() {
  return useContext(BankrollContext);
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

/** Default bankroll used when user hasn't configured one. */
const DEFAULT_BANKROLL = 1000;

function loadFromStorage(): BankrollSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        bankroll: typeof parsed.bankroll === "number" ? parsed.bankroll : DEFAULT_BANKROLL,
        kellyMultiplier:
          [1.0, 0.5, 0.25, 0.125].includes(parsed.kellyMultiplier)
            ? parsed.kellyMultiplier
            : 0.5,
      };
    }
  } catch {
    // localStorage unavailable or corrupt
  }
  return { bankroll: DEFAULT_BANKROLL, kellyMultiplier: 0.5 };
}

function saveToStorage(settings: BankrollSettings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // localStorage unavailable
  }
}

export function BankrollProvider({ children }: { children: ReactNode }) {
  const [bankroll, setBankrollState] = useState<number | null>(DEFAULT_BANKROLL);
  const [kellyMultiplier, setKellyMultiplierState] = useState<KellyMultiplier>(0.5);
  const [hydrated, setHydrated] = useState(false);

  // Hydrate from localStorage on mount
  useEffect(() => {
    const saved = loadFromStorage();
    setBankrollState(saved.bankroll);
    setKellyMultiplierState(saved.kellyMultiplier);
    setHydrated(true);
  }, []);

  // Persist on change (after hydration)
  useEffect(() => {
    if (hydrated) {
      saveToStorage({ bankroll, kellyMultiplier });
    }
  }, [bankroll, kellyMultiplier, hydrated]);

  const unitSize = bankroll != null ? bankroll * 0.01 : null;

  function kellyBetSize(kellyFraction: number): number | null {
    if (bankroll == null) return null;
    return kellyFraction * kellyMultiplier * bankroll;
  }

  return (
    <BankrollContext.Provider
      value={{
        bankroll,
        kellyMultiplier,
        unitSize,
        setBankroll: setBankrollState,
        setKellyMultiplier: setKellyMultiplierState,
        kellyBetSize,
        kellyLabel: KELLY_LABELS[kellyMultiplier] ?? "Half Kelly",
      }}
    >
      {children}
    </BankrollContext.Provider>
  );
}

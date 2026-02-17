"""Clean up stale/invalid signals from the rtm_signals table.

Deletes active signals matching ANY of these conditions:
  1. sportsbook = 'betopenly'
  2. book_odds < -160  (below min odds range)
  3. book_odds > 150   (above max odds range)
  4. sport IN ('basketball_nba', 'icehockey_nhl') with no Pinnacle-sourced devig

Also updates remaining active signals to strip 'betopenly' entries
from the other_books JSONB column.
"""

import os
import sys

# Load .env from backend directory or project root.
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
for env_candidate in [
    os.path.join(project_root, "backend", ".env"),
    os.path.join(project_root, ".env"),
]:
    if os.path.exists(env_candidate):
        with open(env_candidate) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        break

import httpx

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")
    print("       Checked: backend/.env and project root .env")
    sys.exit(1)

BASE = f"{SUPABASE_URL}/rest/v1"
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def count_rows(client: httpx.Client, table: str, filters: dict[str, str] | None = None) -> int:
    """Count rows in a table with optional filters."""
    params: dict[str, str] = {"select": "id"}
    headers = {**HEADERS, "Prefer": "count=exact", "Range": "0-0"}
    if filters:
        params.update(filters)
    resp = client.get(f"{BASE}/{table}", headers=headers, params=params)
    resp.raise_for_status()
    # Count is in the Content-Range header: "0-0/123"
    cr = resp.headers.get("content-range", "")
    if "/" in cr:
        total = cr.split("/")[-1]
        return int(total) if total != "*" else 0
    return 0


def delete_rows(client: httpx.Client, table: str, filters: dict[str, str]) -> int:
    """Delete rows matching filters. Returns count deleted."""
    headers = {**HEADERS, "Prefer": "return=representation"}
    params = {"select": "id", **filters}
    resp = client.delete(f"{BASE}/{table}", headers=headers, params=params)
    resp.raise_for_status()
    deleted = resp.json()
    return len(deleted) if isinstance(deleted, list) else 0


def fetch_rows(client: httpx.Client, table: str, filters: dict[str, str],
               select: str = "*") -> list[dict]:
    """Fetch rows matching filters."""
    params: dict[str, str] = {"select": select}
    params.update(filters)
    resp = client.get(f"{BASE}/{table}", headers={**HEADERS}, params=params)
    resp.raise_for_status()
    rows = resp.json()
    return rows if isinstance(rows, list) else []


def patch_row_by_id(client: httpx.Client, table: str, row_id: str, data: dict) -> bool:
    """Patch a single row by its id. Returns True on success."""
    headers = {**HEADERS, "Prefer": "return=representation"}
    params = {"id": f"eq.{row_id}"}
    resp = client.patch(f"{BASE}/{table}", headers=headers, params=params, json=data)
    resp.raise_for_status()
    result = resp.json()
    return len(result) > 0 if isinstance(result, list) else False


def main() -> None:
    print("=" * 60)
    print("RTM Picks — Stale Signal Cleanup")
    print("=" * 60)
    print(f"Supabase: {SUPABASE_URL}")
    print()

    client = httpx.Client(timeout=30)

    # ── Step 1: Count active signals matching each stale condition ─

    print("Scanning active signals for stale/invalid entries...")
    print()

    total_active = count_rows(client, "rtm_signals", {"status": "eq.active"})

    # Condition 1: sportsbook = 'betopenly'
    betopenly_count = count_rows(client, "rtm_signals", {
        "status": "eq.active",
        "sportsbook": "eq.betopenly",
    })

    # Condition 2: book_odds < -160
    odds_too_low_count = count_rows(client, "rtm_signals", {
        "status": "eq.active",
        "book_odds": "lt.-160",
    })

    # Condition 3: book_odds > 150
    odds_too_high_count = count_rows(client, "rtm_signals", {
        "status": "eq.active",
        "book_odds": "gt.150",
    })

    # Condition 4: NBA/NHL with no Pinnacle devig
    # These are signals for NBA or NHL that lack Pinnacle-sourced devigging.
    # We use devig_source to check — signals without Pinnacle devig will have
    # devig_source != 'pinnacle' or devig_source is null.
    nba_nhl_no_pinnacle_count = count_rows(client, "rtm_signals", {
        "status": "eq.active",
        "sport": "in.(basketball_nba,icehockey_nhl)",
        "devig_source": "neq.pinnacle",
    })
    nba_nhl_null_devig_count = count_rows(client, "rtm_signals", {
        "status": "eq.active",
        "sport": "in.(basketball_nba,icehockey_nhl)",
        "devig_source": "is.null",
    })

    # Count active signals with other_books containing betopenly entries
    # (these will be updated, not deleted)
    other_books_betopenly_rows = fetch_rows(client, "rtm_signals", {
        "status": "eq.active",
        "other_books": "cs.[{\"sportsbook\":\"betopenly\"}]",
    }, select="id,other_books")
    other_books_update_count = len(other_books_betopenly_rows)

    print(f"Total active signals:                        {total_active}")
    print()
    print("Will DELETE active signals matching:")
    print(f"  1. sportsbook = 'betopenly':               {betopenly_count}")
    print(f"  2. book_odds < -160 (below min range):     {odds_too_low_count}")
    print(f"  3. book_odds > 150 (above max range):      {odds_too_high_count}")
    print(f"  4. NBA/NHL with no Pinnacle devig:         {nba_nhl_no_pinnacle_count + nba_nhl_null_devig_count}")
    print(f"       (devig_source != pinnacle:             {nba_nhl_no_pinnacle_count})")
    print(f"       (devig_source is null:                 {nba_nhl_null_devig_count})")
    print()
    print("Will UPDATE (strip 'betopenly' from other_books):")
    print(f"  Active signals with betopenly in other_books: {other_books_update_count}")
    print()

    total_deletes = (betopenly_count + odds_too_low_count + odds_too_high_count
                     + nba_nhl_no_pinnacle_count + nba_nhl_null_devig_count)

    if total_deletes == 0 and other_books_update_count == 0:
        print("Nothing to clean up. All signals look good.")
        client.close()
        return

    confirm = input("Proceed with cleanup? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        client.close()
        return

    print()
    total_deleted = 0

    # ── Step 2: Delete stale signals ──────────────────────────────

    # Condition 1: sportsbook = 'betopenly'
    if betopenly_count > 0:
        n = delete_rows(client, "rtm_signals", {
            "status": "eq.active",
            "sportsbook": "eq.betopenly",
        })
        print(f"  Deleted {n} signals with sportsbook='betopenly'")
        total_deleted += n

    # Condition 2: book_odds < -160
    if odds_too_low_count > 0:
        n = delete_rows(client, "rtm_signals", {
            "status": "eq.active",
            "book_odds": "lt.-160",
        })
        print(f"  Deleted {n} signals with book_odds < -160")
        total_deleted += n

    # Condition 3: book_odds > 150
    if odds_too_high_count > 0:
        n = delete_rows(client, "rtm_signals", {
            "status": "eq.active",
            "book_odds": "gt.150",
        })
        print(f"  Deleted {n} signals with book_odds > 150")
        total_deleted += n

    # Condition 4: NBA/NHL with no Pinnacle devig (devig_source != 'pinnacle')
    if nba_nhl_no_pinnacle_count > 0:
        n = delete_rows(client, "rtm_signals", {
            "status": "eq.active",
            "sport": "in.(basketball_nba,icehockey_nhl)",
            "devig_source": "neq.pinnacle",
        })
        print(f"  Deleted {n} NBA/NHL signals with devig_source != pinnacle")
        total_deleted += n

    # Condition 4 continued: NBA/NHL with null devig_source
    if nba_nhl_null_devig_count > 0:
        n = delete_rows(client, "rtm_signals", {
            "status": "eq.active",
            "sport": "in.(basketball_nba,icehockey_nhl)",
            "devig_source": "is.null",
        })
        print(f"  Deleted {n} NBA/NHL signals with devig_source=null")
        total_deleted += n

    # ── Step 3: Update other_books to remove betopenly entries ────

    if other_books_update_count > 0:
        # Re-fetch after deletions — some rows may have been deleted above
        remaining_rows = fetch_rows(client, "rtm_signals", {
            "status": "eq.active",
            "other_books": "cs.[{\"sportsbook\":\"betopenly\"}]",
        }, select="id,other_books")

        updated_count = 0
        for row in remaining_rows:
            row_id = row.get("id")
            other_books = row.get("other_books")
            if not row_id or not isinstance(other_books, list):
                continue

            filtered = [
                entry for entry in other_books
                if not (isinstance(entry, dict) and entry.get("sportsbook") == "betopenly")
            ]

            if len(filtered) != len(other_books):
                if patch_row_by_id(client, "rtm_signals", str(row_id), {"other_books": filtered}):
                    updated_count += 1

        print(f"  Updated {updated_count} signals to remove 'betopenly' from other_books")

    # ── Step 4: Verify ────────────────────────────────────────────

    print()
    print("Verifying...")
    remaining_active = count_rows(client, "rtm_signals", {"status": "eq.active"})
    remaining_betopenly = count_rows(client, "rtm_signals", {
        "status": "eq.active",
        "sportsbook": "eq.betopenly",
    })
    remaining_low_odds = count_rows(client, "rtm_signals", {
        "status": "eq.active",
        "book_odds": "lt.-160",
    })
    remaining_high_odds = count_rows(client, "rtm_signals", {
        "status": "eq.active",
        "book_odds": "gt.150",
    })
    remaining_nba_nhl_no_pin = count_rows(client, "rtm_signals", {
        "status": "eq.active",
        "sport": "in.(basketball_nba,icehockey_nhl)",
        "devig_source": "neq.pinnacle",
    })
    remaining_nba_nhl_null = count_rows(client, "rtm_signals", {
        "status": "eq.active",
        "sport": "in.(basketball_nba,icehockey_nhl)",
        "devig_source": "is.null",
    })

    print(f"  Active signals remaining:          {remaining_active}")
    print(f"  betopenly sportsbook remaining:    {remaining_betopenly}")
    print(f"  book_odds < -160 remaining:        {remaining_low_odds}")
    print(f"  book_odds > 150 remaining:         {remaining_high_odds}")
    print(f"  NBA/NHL no-pinnacle remaining:     {remaining_nba_nhl_no_pin + remaining_nba_nhl_null}")
    print()
    print(f"Done. Deleted {total_deleted} stale signals total.")

    client.close()


if __name__ == "__main__":
    main()

"""Reset polluted performance/grading data from Supabase.

Deletes:
  - bet_results        (all rows — graded EV opportunity outcomes)
  - clv_records        (all rows — closing line value tracking)
  - rtm_signals        (only graded signals, keeps active ones)
  - ev_opportunities   (resets graded status back to 'closed')

Does NOT delete:
  - Active signals (status='active')
  - Current/open EV opportunities
  - Games, odds snapshots, line movements, steam alerts
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


def patch_rows(client: httpx.Client, table: str, filters: dict[str, str], data: dict) -> int:
    """Patch rows matching filters. Returns count updated."""
    headers = {**HEADERS, "Prefer": "return=representation"}
    params = {"select": "id", **filters}
    resp = client.patch(f"{BASE}/{table}", headers=headers, params=params, json=data)
    resp.raise_for_status()
    updated = resp.json()
    return len(updated) if isinstance(updated, list) else 0


def main() -> None:
    print("=" * 60)
    print("RTM Picks — Performance Data Reset")
    print("=" * 60)
    print(f"Supabase: {SUPABASE_URL}")
    print()

    client = httpx.Client(timeout=30)

    # ── Step 1: Count what we're about to delete ──────────────
    print("Scanning tables...")
    bet_results_count = count_rows(client, "bet_results")
    clv_count = count_rows(client, "clv_records")
    graded_signals_count = count_rows(client, "rtm_signals", {"status": "eq.graded"})
    active_signals_count = count_rows(client, "rtm_signals", {"status": "eq.active"})
    graded_ev_count = count_rows(client, "ev_opportunities", {"status": "eq.graded"})
    open_ev_count = count_rows(client, "ev_opportunities", {"status": "eq.open"})

    print()
    print("Will DELETE:")
    print(f"  bet_results:           {bet_results_count} rows (all graded outcomes)")
    print(f"  clv_records:           {clv_count} rows (all CLV tracking)")
    print(f"  rtm_signals (graded):  {graded_signals_count} rows")
    print()
    print("Will UPDATE:")
    print(f"  ev_opportunities:      {graded_ev_count} rows (graded -> closed)")
    print()
    print("Will NOT touch:")
    print(f"  rtm_signals (active):  {active_signals_count} rows (kept)")
    print(f"  ev_opportunities:      {open_ev_count} rows (open, kept)")
    print()

    total_deletes = bet_results_count + clv_count + graded_signals_count
    if total_deletes == 0 and graded_ev_count == 0:
        print("Nothing to reset. All clean.")
        return

    confirm = input("Proceed? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # ── Step 2: Delete (order matters — bet_results references ev_opportunities) ──
    print()

    # bet_results first (FK to ev_opportunities)
    if bet_results_count > 0:
        n = delete_rows(client, "bet_results", {"id": "not.is.null"})
        print(f"  Deleted {n} rows from bet_results")

    # clv_records
    if clv_count > 0:
        n = delete_rows(client, "clv_records", {"id": "not.is.null"})
        print(f"  Deleted {n} rows from clv_records")

    # rtm_signals — only graded
    if graded_signals_count > 0:
        n = delete_rows(client, "rtm_signals", {"status": "eq.graded"})
        print(f"  Deleted {n} graded rows from rtm_signals")

    # ev_opportunities — reset graded -> closed
    if graded_ev_count > 0:
        n = patch_rows(
            client,
            "ev_opportunities",
            {"status": "eq.graded"},
            {"status": "closed"},
        )
        print(f"  Reset {n} ev_opportunities from 'graded' -> 'closed'")

    # ── Step 3: Verify ───────────────────────────────────────
    print()
    print("Verifying...")
    print(f"  bet_results:    {count_rows(client, 'bet_results')} rows remaining")
    print(f"  clv_records:    {count_rows(client, 'clv_records')} rows remaining")
    print(f"  rtm_signals:    {count_rows(client, 'rtm_signals')} rows remaining "
          f"({count_rows(client, 'rtm_signals', {'status': 'eq.active'})} active)")
    print(f"  ev_opportunities (graded): {count_rows(client, 'ev_opportunities', {'status': 'eq.graded'})} rows remaining")
    print()
    print("Done. Performance data reset.")

    client.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Create the kenpom_snapshots table in Supabase.

Safe to run multiple times — uses IF NOT EXISTS for all objects.
Tries multiple approaches (SDK RPC, raw HTTP, manual instructions).

Usage (from project root):
    python scripts/create_kenpom_table.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def _read_sql() -> list[str]:
    """Read and parse the SQL migration file into individual statements."""
    sql_path = os.path.join(os.path.dirname(__file__), "008_kenpom_snapshots.sql")
    if not os.path.exists(sql_path):
        print(f"Error: SQL file not found at {sql_path}")
        sys.exit(1)

    with open(sql_path) as f:
        sql = f.read()

    return [
        s.strip()
        for s in sql.split(";")
        if s.strip() and not s.strip().startswith("--")
    ]


def _try_sdk_rpc(url: str, key: str, statements: list[str]) -> bool:
    """Approach A: Supabase Python SDK's postgrest.rpc('exec_sql')."""
    try:
        from supabase import create_client
        client = create_client(url, key)
        print("Approach A: Supabase SDK rpc('exec_sql')...")
        for i, stmt in enumerate(statements, 1):
            preview = stmt[:80].replace("\n", " ")
            print(f"  [{i}/{len(statements)}] {preview}...")
            try:
                client.postgrest.rpc("exec_sql", {"query": stmt}).execute()
            except Exception as e:
                if "already exists" in str(e).lower():
                    print("    (already exists, skipping)")
                else:
                    raise
        return True
    except Exception as e:
        print(f"  Approach A failed: {e}\n")
        return False


def _try_http_rpc(url: str, key: str, statements: list[str]) -> bool:
    """Approach B: raw HTTP POST to /rest/v1/rpc/exec_sql."""
    try:
        import httpx
        print("Approach B: HTTP POST to /rest/v1/rpc/exec_sql...")
        for i, stmt in enumerate(statements, 1):
            preview = stmt[:80].replace("\n", " ")
            print(f"  [{i}/{len(statements)}] {preview}...")
            resp = httpx.post(
                f"{url}/rest/v1/rpc/exec_sql",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={"query": stmt},
                timeout=15,
            )
            if resp.status_code >= 400:
                if "already exists" in resp.text.lower():
                    print("    (already exists, skipping)")
                else:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return True
    except Exception as e:
        print(f"  Approach B failed: {e}\n")
        return False


def _print_manual_instructions(statements: list[str]) -> None:
    """Print SQL for manual execution in Supabase dashboard."""
    print("\n" + "=" * 60)
    print("MANUAL SETUP REQUIRED")
    print("=" * 60)
    print(
        "\nAutomatic table creation failed. Please create the table manually:\n"
        "\n1. Go to your Supabase Dashboard → SQL Editor"
        "\n2. Create a 'New Query'"
        "\n3. Paste the following SQL and click 'Run':\n"
    )
    print("-" * 60)
    for stmt in statements:
        print(f"{stmt};")
    print("-" * 60)
    print(
        "\n4. Verify the table exists: SELECT COUNT(*) FROM kenpom_snapshots;"
        "\n5. Restart the scanner — snapshots will start saving automatically."
        "\n"
    )


def main() -> None:
    statements = _read_sql()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")
        print("  → Check your .env file at the project root.")
        _print_manual_instructions(statements)
        sys.exit(1)

    print(f"Creating kenpom_snapshots table ({len(statements)} statements)...\n")

    if _try_sdk_rpc(url, key, statements):
        print("\nDone. kenpom_snapshots table is ready.")
        return

    if _try_http_rpc(url, key, statements):
        print("\nDone. kenpom_snapshots table is ready.")
        return

    # All automated approaches failed — give manual instructions.
    _print_manual_instructions(statements)
    sys.exit(1)


if __name__ == "__main__":
    main()

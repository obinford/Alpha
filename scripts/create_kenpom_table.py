#!/usr/bin/env python3
"""Create the kenpom_snapshots table in Supabase.

Safe to run multiple times — uses IF NOT EXISTS for all objects.

Usage (from project root):
    python scripts/create_kenpom_table.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def main() -> None:
    sql_path = os.path.join(os.path.dirname(__file__), "008_kenpom_snapshots.sql")
    if not os.path.exists(sql_path):
        print(f"Error: SQL file not found at {sql_path}")
        sys.exit(1)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")
        sys.exit(1)

    from supabase import create_client

    with open(sql_path) as f:
        sql = f.read()

    statements = [
        s.strip()
        for s in sql.split(";")
        if s.strip() and not s.strip().startswith("--")
    ]

    client = create_client(url, key)
    print(f"Creating kenpom_snapshots table ({len(statements)} statements)...")

    for i, stmt in enumerate(statements, 1):
        preview = stmt[:80].replace("\n", " ")
        print(f"  [{i}/{len(statements)}] {preview}...")
        try:
            client.postgrest.rpc("exec_sql", {"query": stmt}).execute()
        except Exception as e:
            # Table/index may already exist — that's fine.
            if "already exists" in str(e).lower():
                print(f"    (already exists, skipping)")
            else:
                print(f"    Warning: {e}")

    print("Done. kenpom_snapshots table is ready.")


if __name__ == "__main__":
    main()

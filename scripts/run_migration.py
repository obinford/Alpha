#!/usr/bin/env python3
"""Run SQL migrations against Supabase via the Management API.

Usage (from project root):
    python scripts/run_migration.py scripts/001_create_odds_tables.sql
"""

import os
import sys

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def run_migration(sql_path: str) -> None:
    """Execute a SQL file against the Supabase database."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]

    with open(sql_path) as f:
        sql = f.read()

    # Split on semicolons to execute each statement individually.
    # Strip comments and whitespace.
    statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]

    client = create_client(url, key)

    print(f"Running migration: {sql_path}")
    print(f"Executing {len(statements)} statements against {url}...")

    for i, stmt in enumerate(statements, 1):
        print(f"  [{i}/{len(statements)}] {stmt[:60]}...")
        client.postgrest.rpc("exec_sql", {"query": stmt}).execute()

    print("Migration complete.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-sql-file>")
        sys.exit(1)
    run_migration(sys.argv[1])

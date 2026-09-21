"""Run Supabase migrations in order: 001 → 002 → 003 → 004."""
import os
import sys
import psycopg
from pathlib import Path

MIGRATION_DIR = Path(__file__).resolve().parent.parent / "supabase"
MIGRATIONS = [
    "001_schema.sql",
    "002_indexes.sql",
    "003_rls.sql",
    "004_seed.sql",
]


def get_connection_url():
    url = os.environ.get("SUPABASE_DATABASE_URL", "")
    if not url:
        print("ERROR: SUPABASE_DATABASE_URL not set.")
        print("Format: postgresql://user:password@host:5432/dbname")
        sys.exit(1)
    return url


def run_migrations(conn_url):
    conn = psycopg.connect(conn_url)
    conn.autocommit = True

    # Track applied migrations
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            filename VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    applied = {row[0] for row in conn.execute("SELECT filename FROM _migrations").fetchall()}

    for migration in MIGRATIONS:
        if migration in applied:
            print(f"  SKIP {migration} (already applied)")
            continue

        print(f"  APPLY {migration}...")
        sql = (MIGRATION_DIR / migration).read_text(encoding="utf-8")
        conn.execute(sql)
        conn.execute(
            "INSERT INTO _migrations (filename) VALUES (%s)",
            (migration,),
        )
        print(f"  OK   {migration}")

    conn.close()
    print("\nAll migrations applied.")


if __name__ == "__main__":
    url = get_connection_url()
    run_migrations(url)

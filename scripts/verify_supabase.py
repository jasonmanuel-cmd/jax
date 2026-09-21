"""Verify Supabase migration: check tables, indexes, RLS policies exist."""
import os
import sys
import psycopg

EXPECTED_TABLES = [
    "devices", "events", "workspaces", "projects", "memories",
    "memory_deletion_audit", "tasks", "decisions", "handoffs",
    "documents", "daily_summaries", "tool_permissions", "tool_runs",
    "agent_runs", "kill_switch", "improvement_proposals", "voice_sessions",
]

EXPECTED_INDEXES = [
    "idx_devices_revoked", "idx_events_device_id", "idx_events_occurred_at",
    "idx_memories_user_id", "idx_tasks_status", "idx_decisions_user_id",
    "idx_handoffs_project_id", "idx_voice_sessions_user_id",
]


def verify(conn_url):
    conn = psycopg.connect(conn_url)
    conn.autocommit = True
    errors = []

    # Check tables
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    }
    for t in EXPECTED_TABLES:
        if t not in tables:
            errors.append(f"MISSING TABLE: {t}")
        else:
            print(f"  TABLE OK: {t}")

    # Check indexes
    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
        ).fetchall()
    }
    for i in EXPECTED_INDEXES:
        if i not in indexes:
            errors.append(f"MISSING INDEX: {i}")
        else:
            print(f"  INDEX OK: {i}")

    # Check RLS enabled
    rls_tables = {
        row[0]
        for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND rowsecurity = true"
        ).fetchall()
    }
    for t in EXPECTED_TABLES:
        if t not in rls_tables:
            errors.append(f"RLS NOT ENABLED: {t}")

    # Check RLS policies exist
    policy_count = conn.execute(
        "SELECT COUNT(*) FROM pg_policies WHERE schemaname = 'public'"
    ).fetchone()[0]
    print(f"  RLS POLICIES: {policy_count} found")
    if policy_count < len(EXPECTED_TABLES):
        errors.append(f"Expected at least {len(EXPECTED_TABLES)} RLS policies, found {policy_count}")

    conn.close()

    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("\nAll checks passed.")


if __name__ == "__main__":
    url = os.environ.get("SUPABASE_DATABASE_URL", "")
    if not url:
        print("ERROR: SUPABASE_DATABASE_URL not set.")
        sys.exit(1)
    verify(url)

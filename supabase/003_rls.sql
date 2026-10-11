-- 003_rls.sql — JAX Phase 4: Row Level Security policies
-- Enable RLS on all tables. Admin service role bypasses via separate connection.

-- Enable RLS
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_deletion_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE handoffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_summaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE tool_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tool_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE kill_switch ENABLE ROW LEVEL SECURITY;
ALTER TABLE improvement_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;

-- Audit events are read-only for authenticated users and have no INSERT,
-- UPDATE or DELETE policy: the log is append-only through the service role
-- only, so a compromised client token cannot rewrite history.
CREATE POLICY audit_events_read ON audit_events
    FOR SELECT TO authenticated
    USING (true);

-- ---------------------------------------------------------------------------
-- User-owned tables: users can only see/modify their own rows
-- ---------------------------------------------------------------------------

-- Workspaces
CREATE POLICY workspaces_user_isolation ON workspaces
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Projects
CREATE POLICY projects_user_isolation ON projects
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Memories
CREATE POLICY memories_user_isolation ON memories
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Memory deletion audit
CREATE POLICY memory_deletion_audit_user_isolation ON memory_deletion_audit
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Tasks
CREATE POLICY tasks_user_isolation ON tasks
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Decisions
CREATE POLICY decisions_user_isolation ON decisions
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Handoffs
-- Handoffs: readable to authenticated users (single-user deployment), but
-- never client-writable. A client must not be able to forge the handoff that
-- the next device reconstructs the project from.
CREATE POLICY handoffs_read ON handoffs
    FOR SELECT TO authenticated
    USING (true);

-- Documents
CREATE POLICY documents_user_isolation ON documents
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Daily summaries
CREATE POLICY daily_summaries_user_isolation ON daily_summaries
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Tool permissions
-- tool_permissions: read-only to authenticated users. A user_id check alone
-- would still let that user INSERT or UPDATE their own permission rows, which
-- is exactly the privilege escalation this table exists to prevent.
CREATE POLICY tool_permissions_read ON tool_permissions
    FOR SELECT TO authenticated
    USING (user_id = auth.uid());

-- Tool runs: readable by any authenticated user (single-user deployment),
-- but NOT writable. Writes are service-role only, so a client token cannot
-- forge or rewrite an approval record.
CREATE POLICY tool_runs_read ON tool_runs
    FOR SELECT TO authenticated
    USING (true);

-- Agent runs: readable, never client-writable. A client must not be able to
-- mark its own session 'exited' or erase the base/final commit evidence.
CREATE POLICY agent_runs_read ON agent_runs
    FOR SELECT TO authenticated
    USING (true);

-- Kill switch: status is visible to all authenticated users so an operator can
-- see why nothing is working, but only the activating user may write.
CREATE POLICY kill_switch_read ON kill_switch
    FOR SELECT TO authenticated
    USING (true);
CREATE POLICY kill_switch_write ON kill_switch
    FOR INSERT TO authenticated
    WITH CHECK (activated_by = auth.uid());
CREATE POLICY kill_switch_deactivate ON kill_switch
    FOR UPDATE TO authenticated
    USING (activated_by = auth.uid())
    WITH CHECK (activated_by = auth.uid());

-- Improvement proposals: readable to authenticated users, but a client may
-- only create proposals. Status transitions (applied/rejected) are
-- service-role only so a proposal cannot be self-approved.
CREATE POLICY improvement_proposals_read ON improvement_proposals
    FOR SELECT TO authenticated
    USING (true);
CREATE POLICY improvement_proposals_insert ON improvement_proposals
    FOR INSERT TO authenticated
    WITH CHECK (true);

-- Voice sessions
CREATE POLICY voice_sessions_user_isolation ON voice_sessions
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- Service role: full access (used by JAX core)
-- The service_role key bypasses RLS by default in Supabase.
-- These policies ensure the service role can do everything.
-- ---------------------------------------------------------------------------

CREATE POLICY service_role_full_access ON devices FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON events FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON workspaces FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON projects FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON memories FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON memory_deletion_audit FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON tasks FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON decisions FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON handoffs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON documents FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON daily_summaries FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON tool_permissions FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON tool_runs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON agent_runs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON kill_switch FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON improvement_proposals FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON voice_sessions FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY service_role_full_access ON audit_events FOR ALL TO service_role USING (true) WITH CHECK (true);

-- tool_permissions is deliberately absent from the authenticated policies:
-- it is the permission table, so a client token must never be able to widen its
-- own ceiling. Only the service role writes it.

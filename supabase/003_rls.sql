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
CREATE POLICY handoffs_user_isolation ON handoffs
    FOR ALL TO authenticated
    USING (created_at IS NOT NULL)  -- handoffs are readable by all authenticated users
    WITH CHECK (true);

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
CREATE POLICY tool_permissions_user_isolation ON tool_permissions
    FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Tool runs
CREATE POLICY tool_runs_user_isolation ON tool_runs
    FOR ALL TO authenticated
    USING (true)  -- tool runs are readable by all authenticated users
    WITH CHECK (true);

-- Agent runs
CREATE POLICY agent_runs_user_isolation ON agent_runs
    FOR ALL TO authenticated
    USING (true)  -- agent runs are readable by all authenticated users
    WITH CHECK (true);

-- Kill switch
CREATE POLICY kill_switch_user_isolation ON kill_switch
    FOR ALL TO authenticated
    USING (true)  -- kill switch status is visible to all authenticated users
    WITH CHECK (activated_by = auth.uid());

-- Improvement proposals
CREATE POLICY improvement_proposals_user_isolation ON improvement_proposals
    FOR ALL TO authenticated
    USING (true)  -- proposals are visible to all authenticated users
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

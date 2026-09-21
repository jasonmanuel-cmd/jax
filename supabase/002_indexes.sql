-- 002_indexes.sql — JAX Phase 4: Indexes for query performance

-- Devices
CREATE INDEX IF NOT EXISTS idx_devices_revoked ON devices(revoked);
CREATE INDEX IF NOT EXISTS idx_devices_last_seen ON devices(last_seen_at);

-- Events
CREATE INDEX IF NOT EXISTS idx_events_device_id ON events(device_id);
CREATE INDEX IF NOT EXISTS idx_events_occurred_at ON events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_payload_type ON events((payload->>'type'));
CREATE INDEX IF NOT EXISTS idx_events_payload_device ON events((payload->>'device_id'));

-- Workspaces
CREATE INDEX IF NOT EXISTS idx_workspaces_user_id ON workspaces(user_id);

-- Projects
CREATE INDEX IF NOT EXISTS idx_projects_workspace_id ON projects(workspace_id);
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

-- Memories
CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_project_id ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_expires_at ON memories(expires_at) WHERE expires_at IS NOT NULL;

-- Tasks
CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at);

-- Decisions
CREATE INDEX IF NOT EXISTS idx_decisions_project_id ON decisions(project_id);
CREATE INDEX IF NOT EXISTS idx_decisions_user_id ON decisions(user_id);

-- Handoffs
CREATE INDEX IF NOT EXISTS idx_handoffs_project_id ON handoffs(project_id);
CREATE INDEX IF NOT EXISTS idx_handoffs_created_at ON handoffs(created_at);

-- Documents
CREATE INDEX IF NOT EXISTS idx_documents_project_id ON documents(project_id);

-- Daily summaries
CREATE INDEX IF NOT EXISTS idx_daily_summaries_user_date ON daily_summaries(user_id, date);

-- Tool runs
CREATE INDEX IF NOT EXISTS idx_tool_runs_tool_name ON tool_runs(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_runs_approval_state ON tool_runs(approval_state);

-- Agent runs
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_name ON agent_runs(agent_name);

-- Kill switch
CREATE INDEX IF NOT EXISTS idx_kill_switch_active ON kill_switch(deactivated_at) WHERE deactivated_at IS NULL;

-- Improvement proposals
CREATE INDEX IF NOT EXISTS idx_improvement_proposals_status ON improvement_proposals(status);

-- Voice sessions
CREATE INDEX IF NOT EXISTS idx_voice_sessions_user_id ON voice_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_started_at ON voice_sessions(started_at);

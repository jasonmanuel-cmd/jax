-- 004_seed.sql — JAX Phase 4: Seed data for testing
-- Only run in development. Do NOT run in production.

-- Insert a test user (matches the admin identity used in local dev)
-- Note: In production, users are created via Supabase Auth
INSERT INTO workspaces (id, user_id, name, type, status)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    '00000000-0000-4000-8000-000000000000',
    'Default Workspace',
    'personal',
    'active'
) ON CONFLICT DO NOTHING;

-- Insert a test project
INSERT INTO projects (id, workspace_id, user_id, name, path_hint, status)
VALUES (
    '00000000-0000-4000-8000-000000000002',
    '00000000-0000-4000-8000-000000000001',
    '00000000-0000-4000-8000-000000000000',
    'JAX Development',
    'C:/Users/blunts/Desktop/projects/jax',
    'active'
) ON CONFLICT DO NOTHING;

-- Insert a test memory
INSERT INTO memories (id, user_id, kind, content, confidence, project_id)
VALUES (
    '00000000-0000-4000-8000-000000000003',
    '00000000-0000-4000-8000-000000000000',
    'preference',
    'User prefers full-file code replacements over patches',
    0.95,
    '00000000-0000-4000-8000-000000000002'
) ON CONFLICT DO NOTHING;

-- Insert a test task
INSERT INTO tasks (id, user_id, project_id, title, status, priority)
VALUES (
    '00000000-0000-4000-8000-000000000004',
    '00000000-0000-4000-8000-000000000000',
    '00000000-0000-4000-8000-000000000002',
    'Wire real model provider',
    'open',
    'high'
) ON CONFLICT DO NOTHING;

-- Insert a test decision
INSERT INTO decisions (id, user_id, project_id, decision, rationale)
VALUES (
    '00000000-0000-4000-8000-000000000005',
    '00000000-0000-4000-8000-000000000000',
    '00000000-0000-4000-8000-000000000002',
    'Use OpenRouter for model calls',
    'Best cost/performance ratio, supports multiple providers'
) ON CONFLICT DO NOTHING;

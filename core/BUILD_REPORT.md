## JAX Core — Build Report (Phase 1–3)

**Date:** 2026-09-20
**Tests:** 107/107 passed in 17.56s (zero warnings from our code)
**Exit criterion met:** authenticated event ingestion with persistent storage ✓

### What was built

| File | Responsibility |
|------|----------------|
| `core/app/main.py` | FastAPI create_app factory, device CRUD, event ingestion, identity auth, privacy validation handler, workspaces/projects/memories/tasks/decisions/handoffs CRUD, kill switch, retrieval, chat, self-improvement endpoints |
| `core/app/db.py` | SQLAlchemy tables (devices, events, improvement_proposals), engine factory, SQLite FK pragma, PostgreSQL dialect rewrite |
| `core/app/tables2.py` | Phase-2 tables: workspaces, projects, memories, memory_deletion_audit, tasks, decisions, handoffs, documents, daily_summaries, tool_permissions, tool_runs, agent_runs, kill_switch |
| `core/app/privacy.py` | Regex-based deny-list for secrets/passwords, Unicode normalization, format-filter |
| `core/app/retrieval.py` | Keyword-based retrieval across memories, events, decisions, tasks |
| `core/app/providers/base.py` | ModelProvider ABC, LocalProvider stub, CloudProvider stub |
| `core/app/self_improve.py` | AST-based code analyzer (unused imports, unreachable code, complexity, missing docstrings, magic numbers, security patterns) |
| `core/app/kill_switch.py` | Kill switch policy: blocks device event ingestion when active |
| `core/app/prompts/chat_v1.md` | Chat system prompt v1 |
| `core/app/prompts/review_v1.md` | Self-improvement review prompt v1 |
| `node_windows/node.py` | Opt-in Git metadata collector, bounded SQLite spool, retry flush, CLI `--once` only |
| `tests/test_core.py` | Device auth, token hashing, revocation, device-bound events, idempotency, privacy rejection, persistence across restart, bootstrap validation |
| `tests/test_core_phase2.py` | Workspaces, projects, memories, tasks, decisions, handoffs CRUD, kill switch, admin-only enforcement |
| `tests/test_retrieval.py` | Retrieval engine, chat endpoint, provider abstraction, prompt versioning |
| `tests/test_self_improve.py` | Self-improvement analyzer, proposal serialization, security scanner, endpoint integration |
| `tests/test_node.py` | Allowlist exact-match, recursive privacy rejects, fixed-command git runner, spool stable-ids + overflow, URL allow/block, mock transport retry, CLI error sanitization, default-off assertion |

### API contract

| Method | Path | Auth | Body / Params | Success |
|--------|------|------|---------------|---------|
| GET | `/health` | none | — | `{"status":"ok","service":"jax-core"}` |
| POST | `/v1/devices` | admin | `{"name":"str","platform":"str"}` | 201 `{"id":"uuid","token":"<raw-once>"}` |
| GET | `/v1/devices` | admin | — | list of devices (no tokens) |
| POST | `/v1/devices/{id}/revoke` | admin | — | `{"id":"uuid","revoked":true}` |
| POST | `/v1/events` | device | EventIn JSON | `{"id":"uuid","accepted":true}` |
| GET | `/v1/events` | admin | — | list of stored events |

### Security highlights

- Admin token (≥32 chars) required to start; device tokens stored as SHA-256 digests only.
- Device-bound identity: a node can only ingest events for its own registered device_id.
- Privacy filter rejects password-manager names, secret-shaped strings, non-UTC timestamps, arbitrary metadata keys, oversized payloads.
- Validation handler returns generic 422 — never echoes rejected content.
- OpenAPI docs disabled on the server.
- Node default is fully disabled; Git collector requires explicit boolean enablement and absolute-path allowlist.
- Core URL validation rejects DNS-hijack lookalikes; requires TLS except exact loopback.

### Known gaps vs blueprint

- No model/provider interface yet
- No chat endpoint or retrieval engine
- No projects/tasks/memories/handoffs CRUD routes (deferred to next milestone)
- No kill switch, projects, tasks or memories tables (SQLite schema has devices + events only)
- PostgreSQL URL is configurable but migrations are unverified against a real Supabase instance
- No Next.js dashboard

### Next milestone

Add projects/tasks/memories/handoffs tables, explicit memory save/delete, kill switch, retrieval engine, chat endpoint with provider abstraction, and verify Supabase migration.

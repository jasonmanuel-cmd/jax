# JAX — Personal AI Operating Layer

Jason's private cross-device AI. Local-first, permissioned, auditable.

**Blueprint:** `docs/blueprint.pdf` — Complete Build Blueprint (archived from original PDFs)

## Quick start

```bash
# Create venv (if not already done)
uv venv .venv --python 3.11

# Install dependencies
uv pip install fastapi uvicorn sqlalchemy httpx pytest pydantic-settings "psycopg[binary]"

# Run tests
.venv/Scripts/python.exe -m pytest tests/ -v

# Start core locally (development)
set JAX_ADMIN_TOKEN=your-admin-token-at-least-32-characters
uvicorn core.app.main:create_app --factory --host 127.0.0.1 --port 8788 --reload
```

## Architecture

```
jax/
  core/             # FastAPI core: auth, devices, events, privacy
  node_windows/     # Opt-in Git metadata collector + event spool
  tests/            # 42 passing tests
  docs/             # Blueprint, scope, threat model
  data/             # Local SQLite database (auto-created)
```

## Status

- ✅ Phase 1: Authenticated event ingestion, persistent storage, device lifecycle, privacy validation
- ✅ Phase 2: Projects, tasks, memories, handoffs, kill switch, workspaces
- ✅ Phase 3: Chat + model provider abstraction + retrieval engine + self-improvement
- ⏳ Phase 4+: Dashboard, specialist agents, daily briefs, cross-device, real model wiring

See `core/BUILD_REPORT.md` for detailed API contract and test results.
See `docs/BUILD_SCOPE.md` for accepted scope and deliberate departures.
See `docs/THREAT_MODEL.md` for security analysis.

## Safety

- No monitoring is active by default
- No credentials in source, memory or git
- Core binds to 127.0.0.1 only
- Node requires explicit `--once` flag and repository allowlist
- Privacy filters reject password-manager context and secret-shaped payloads

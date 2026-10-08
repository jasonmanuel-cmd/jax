# JAX — Personal AI Operating Layer

Jason's private cross-device AI. Local-first, permissioned, auditable.

**Canonical specification:** `docs/JAX_Master_Developer_Specification.pdf` — September 27, 2026 master specification supplied by Jason. This supersedes the archived `docs/blueprint.pdf` where they differ.

JAX is the control plane around replaceable models and agents: Git owns source code, the JAX database owns operational state, Supermemory supplies durable semantic context, and Jason retains final authority. **Turn Your Chaos Into Code.**

See `DECISIONS.md` for adoption boundaries and `docs/SPEC_AUDIT.md` for the specification gap assessment. Existing features and historical phase reports are not proof that canonical JAX V1 is complete.

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

### Git preflight requires an allowlist

`POST /v1/sessions/preflight` will not touch a repository that is not listed in
`JAX_PROJECT_ROOTS`. Anything else returns
`403 {"detail":"Project root is not allowlisted"}`. This is the fail-closed
control from the threat model: the core refuses to run Git against a path it
was not explicitly granted.

Set it to the exact repository root, not its parent. Separate multiple entries
with the platform path separator (`;` on Windows, `:` on POSIX):

```bash
# Windows
set JAX_PROJECT_ROOTS=C:\Users\blunt\repos\jax
# POSIX
export JAX_PROJECT_ROOTS=/home/jason/repos/jax:/home/jason/repos/other
```

A project is preflighted only if it is `active`, has a `path_hint` set, and that
resolved path matches an allowlist entry exactly.

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

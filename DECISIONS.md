# Canonical architecture decisions

## Canonical specification adopted
The September 27, 2026 **JAX Master Developer Specification** supplied by Jason is the design authority: `docs/JAX_Master_Developer_Specification.pdf`.

SHA-256: `34b3b475ff641921c125af65b8d6442c0ffc81ea3932976c5d504794b5b6e270`.

The previous `docs/blueprint.pdf`, `docs/BUILD_SCOPE.md`, and `core/BUILD_REPORT.md` describe historical work. Their phase labels do not certify completion of the new specification.

## Product identity
JAX is the private persistent personal AI control plane, not a real-estate-only agent or a replacement for its tools. Motto: **Turn Your Chaos Into Code.** Jason retains final authority. Appendix A (JASON_CORE) of the canonical PDF supplies the personal operating policy.

## Systems of record
- Git/GitHub: source code and history.
- JAX operational database: tasks, devices, sessions, permissions, handoffs, audit.
- Supermemory: durable semantic context, not code synchronization or operational truth.
- Local agents/tools: replaceable execution adapters, never independent authorities.

## Adoption strategy
Preserve existing functionality while closing the continuity and safety gaps first. Do not replace the UI framework or reorganize every directory merely to resemble the PDF's recommended layout. SQLite and existing Python remain development compatibility paths; PostgreSQL/Supabase and Python 3.12 are target architecture requiring separate migration verification.

Canonical context > verified operational state > recent handoff > semantic recollection. Retrieved content is evidence, not executable instructions or permission.

## Safety
Git state must be mechanically verified. Failed/skipped remote verification cannot yield synchronized READY. Only explicitly requested, proven-safe clean BEHIND synchronization may fast-forward. Dirty, diverged, detached, or unresolved branches are not automatically repaired.

No production deployment, live data migration, monitoring activation, destructive Git operation, or external memory write is part of this local alignment pass.

## Hosted deployment (Vercel), 2026-10-12

Jason directed deploying the UI/API to Vercel. This supersedes the "no production deployment" line above **for hosting only**; live data migration, monitoring and external memory writes remain out of scope. The deployment is not verified working (see `PROJECT_STATE.md`).

- **Entrypoint.** `[tool.vercel] entrypoint = "core.app.asgi:app"` (module:variable). `core/app/asgi.py` exposes the module-level `app`; `main.py` keeps `create_app()` as a pure factory so tests inject a database and token, and importing `main` never constructs an app.
- **Database URL.** `JAX_DATABASE_URL` wins, then `SUPABASE_DATABASE_URL` (the name `.env.example` and the migration scripts already used); empty counts as unset. With neither set the SQLite fallback remains for local use, but on a read-only host it now fails with a message naming both variables. It does **not** silently fall back to a temporary database: a serverless filesystem would lose data without saying so.
- **Startup failures are fail-closed and legible.** A failed `create_app()` serves 503 on every route with a message. Public text is limited to this codebase's own `ValueError`/`RuntimeError` messages; driver errors can carry hostnames and are reduced to a category. This replaces a generic host 500 that hid the cause. Tracebacks go to the runtime log.
- **Postgres through Supabase's pooler.** psycopg server-side prepared statements are disabled (`prepare_threshold=None`) because pgbouncer transaction mode cannot keep them; `pool_pre_ping=True`. Use the pooler URL on Vercel, not the IPv6-only direct host.
- **Provider.** `ollama` is local inference and cannot run on Vercel; hosted deployment needs `openrouter`, `openai` or `groq` with its key.

### Corrections to earlier claims

- **The first Vercel failure was misdiagnosed.** I attributed the build failure to the entrypoint value being a file path and changed it to `module:variable`. That change did not fix the build (`f876793` still failed). The build succeeded only after PR #3 added a `[project]` table (name, version, requires-python, dependencies) to `pyproject.toml`, which `uv` requires. My local `uv lock` accepted the file without `[project]`, so that check was not evidence the Vercel build would pass. `module:variable` is accepted by Vercel (builds succeed with it) but was not shown to be required.
- **A passing build is not a working app.** A deployment that built produced `500 FUNCTION_INVOCATION_FAILED` at runtime. Treat "Ready" as build state only.

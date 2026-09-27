# PROJECT_STATE.md

**Canonical spec:** `docs/JAX_Master_Developer_Specification.pdf` (Sept 27, 2026) — archived and adopted as design authority. See `DECISIONS.md`.

## Verified this pass (local, isolated tests only)

- **Git preflight control plane (PDF §7, §27)** — `core/app/git_control.py` + `tests/test_git_control.py` (18/18).
  Deterministic `inspect_repository()` returns READY/BEHIND/AHEAD/DIRTY/DIVERGED/NO_UPSTREAM/DETACHED/REMOTE_UNREACHABLE. Fetch runs in a bounded subprocess with credential prompts disabled and no shell; a failed/skipped fetch never yields READY. Only explicitly requested fast-forward on a clean BEHIND repo syncs, with SHA re-pin. A repository that changes mid-preflight (TOCTOU) is downgraded from READY. `launch_allowed` is true only for freshly verified READY.
- **Preflight API `POST /v1/sessions/preflight` (PDF §16)** — in `core/app/main.py`. Admin-only, project must exist and be active, path must resolve to a `JAX_PROJECT_ROOTS` allowlisted exact root; fast-forward requires fetch. End-to-end verified against real local+remote repos: READY→launch_allowed:true, DIRTY→launch_allowed:false.
- **Chat/voice identity + context wiring (PDF §1, §2, §5, §6)** — `core/app/prompts/chat_v1.md` now carries JAX's canonical identity, motto, authority model, systems-of-record hierarchy, memory/privacy rules, and untrusted-evidence handling. `build_messages()` (`core/app/context_messages.py`) feeds the real system prompt + bounded, labeled untrusted retrieval evidence + the user's actual query last. Both `/v1/chat` and `/v1/voice/chat` use it (previously they sent the literal string `chat_v1` with no context).
- **Memory secret filtering (PDF §5.4)** — `POST /v1/memories` now runs `safe_text` on `kind` and `content`, rejecting secret-shaped payloads with 422 before persistence.
- **Retrieval scoping (PDF §5.4, §6)** — retrieval requires exact project scope (`project_id=None` = personal/null-project only, not all projects); expired memories excluded. Device events excluded pending a scoped ownership schema (no trusted user/project ownership relation exists yet).
- **Spec gap audit** — `docs/SPEC_AUDIT.md`: all 31 sections + appendices A–D mapped implemented/partial/missing.

Full suite: `.venv/Scripts/python.exe -m pytest tests/ -q` → **161 passed**.

## NOT yet built / NOT verified (highest-priority gaps from SPEC_AUDIT.md)

- Managed sessions + handoff engine, agent adapters (Claude/Hermes/generic CLI), Supermemory adapter, verification hooks, cross-device reconstruction (PDF §5, §8, §9).
- Security defects flagged: untrusted lead data interpolated into inline JS and admin token in localStorage (`core/static/index.html`); overbroad authenticated RLS mutation policies (`supabase/003_rls.sql`); self-improve "apply" only flips DB status; kill switch stops ingestion only.
- PostgreSQL UUID/schema contracts vs SQLAlchemy/API mismatches.
- Postgres behavior, a second physical device, live Supermemory, and real agent lifecycle are **unverified** — the local SQLite suite does not prove them.

## Next action

Build the managed session + handoff engine (PDF §5, Appendix C) on top of the verified preflight, then agent adapters — the continuity milestone (PDF §29) before more autonomy.

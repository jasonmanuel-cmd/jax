# PROJECT_STATE.md

**Canonical spec:** `docs/JAX_Master_Developer_Specification.pdf` (Sept 27, 2026) — archived and adopted as design authority. See `DECISIONS.md`.

**Suite:** `python -m pytest tests/ -q` → **323 passed, 6 deselected** (~28s, Python 3.13 venv, SQLite; earlier 311 figure was 92s on the laptop).
Deselected are `slow`-marked live-inference tests; run them with `-m slow`.

## Hosted deployment (Vercel) pass — 2026-10-12

Goal: get the FastAPI app serving its UI on Vercel. Status: **builds succeed; runtime on Vercel is unverified** (see "Remaining problems").

### Changes and files affected

| Change | Files | Where |
|---|---|---|
| Vercel entrypoint: `[tool.vercel] entrypoint = "core.app.asgi:app"` | `pyproject.toml` | merged, PR #1 |
| Module-level `app` for hosts (`create_app()` is a factory) | `core/app/asgi.py` (new) | merged, PR #1 |
| Project-scoped MCP registration of the iFixAi connector | `.mcp.json` (new) | merged, PR #1 |
| `[project]` metadata (name, version, requires-python, dependencies) required by `uv` | `pyproject.toml` | merged, PR #3 (Vercel agent, not this session) |
| DB URL lookup: `JAX_DATABASE_URL`, then `SUPABASE_DATABASE_URL` (empty = unset) | `core/app/db.py` (`database_url_from_env`), `core/app/main.py`, `.env.example` | PR #4 (open, draft) |
| No-database on a read-only filesystem raises `RuntimeError` naming the variables, instead of a bare `mkdir` crash | `core/app/db.py` | PR #4 |
| `postgres://` accepted as well as `postgresql://`; psycopg `prepare_threshold=None` (pgbouncer transaction-mode pooler cannot keep server-side prepared statements); `pool_pre_ping=True` | `core/app/db.py` | PR #4 |
| Failed `create_app()` is logged and served as a fail-closed **503 JSON** naming the problem; only this codebase's own `ValueError`/`RuntimeError` text is shown, SQLAlchemy errors reduced to a generic database message, anything else to its type name | `core/app/asgi.py` | PR #4 |
| 12 new tests | `tests/test_db_config.py`, `tests/test_asgi_entrypoint.py` | PR #4 |

`start_server.py` and the local/dev path call `create_app()` directly and are unchanged.

### Checks performed and actual results

- Full suite after PR #4 changes: **323 passed, 6 deselected**. Python 3.13 in a scratch venv from `requirements.txt`; the project's stated target is 3.12 and `requires-python` is `>=3.11`, so 3.12 itself was not run.
- `import core.app.asgi` with a valid token + SQLite URL + `JAX_PROVIDER=stub` yields a `FastAPI` app titled "JAX Core". Passed.
- Startup-failure messages reproduced locally: missing token → `ValueError: JAX_ADMIN_TOKEN must contain at least 32 characters`; simulated read-only filesystem → the new `RuntimeError`; bad provider → `RuntimeError: Unknown JAX_PROVIDER`. Unreachable Postgres: only SQLAlchemy's background-link line (`e3q8`, its OperationalError code) was seen, **not** the full first line.
- `uv lock` on a `pyproject.toml` containing only `[tool.vercel]` **succeeded locally**, so the local check did **not** predict the Vercel build failure.
- Vercel preview builds, from the PR status comments (build state only, runtime never opened by this session):
  - `31809b7` (entrypoint as file path `core/app/asgi.py`): **Error** (~3s).
  - `f876793` (entrypoint as `core.app.asgi:app`): **Error** (~5s).
  - `master` after PR #3: user reported "it did build" and then saw `500 FUNCTION_INVOCATION_FAILED` on the site.
  - `b9eb050` and `ac2356c` (PR #4): **Ready**.
- The user reported a `500 FUNCTION_INVOCATION_FAILED` screenshot (URL not stated). It was **not re-checked** after `ac2356c`, the first commit that can report the cause in the browser.

### Remaining problems

1. **Unknown cause of the runtime 500.** Not diagnosed. The Vercel connector in this session gets 403/404 on this team's deployments, so build and runtime logs were never read. Candidates, from reading the code: missing `JAX_ADMIN_TOKEN` (`main.py` raises at import); database URL under the wrong variable name or an IPv6-only Supabase direct host from IPv4 Vercel; env vars set for one Vercel environment (Production/Preview/Development) but not the one being hit.
2. **Vercel env vars are unset or unconfirmed** and cannot be set from code: `JAX_ADMIN_TOKEN` (32+ chars), a hosted `JAX_PROVIDER` (`ollama` cannot reach a laptop from Vercel) with its API key, and the Supabase **pooler** URL.
3. **`prepare_threshold=None` and the pooler fix are untested against a real pgbouncer or Postgres.** They rest on psycopg/Supabase documentation and a unit test of the engine arguments only.
4. **`pyproject.toml` dependencies duplicate `requirements.txt`** (added by PR #3) and include `pytest` as a runtime dependency. Two lists to keep in sync; not cleaned up.
5. **iFixAi connector is not live.** `https://mcp.ifixai.ai/mcp` returns proxy `403 CONNECT tunnel failed` from the session container (curl and the MCP client both), even after the user said the domain was allowed and the session restarted. The `ifixai-operator-guide` prompt was never fetched and the demo audit was never run. Likely cause: the allowlist edit is not reaching this container (different environment, unsaved, or an old container).
6. **Previously recorded gaps are untouched:** Postgres never exercised, RLS shape-only, R3/R4/R9/R10 partial, cross-device continuity unproven.

### Next concrete action

Open the PR #4 preview URL. If the UI loads, merge PR #4 and set the env vars for Production. If it shows the JSON "JAX failed to start", set the variable named in `detail`, tick every environment, and redeploy. If it still shows the old Vercel 500 page, read the deployment's runtime Logs and use the last traceback line.

## Verified this pass

### Truthfulness defects closed (SPEC_AUDIT R1, R2, R7, R8, R9-partial)

- **R7 — the kill switch did not kill.** It gated only `POST /v1/events`, so chat, voice, leads, self-improve and every mutating endpoint stayed reachable during an incident. 30 endpoints now sit behind `live_admin`; gated calls return **423 Locked** (resource exists, execution suspended) rather than 403. Reads stay open on purpose — `kill/status`, `/v1/audit` and `/v1/agents` must be inspectable while halted, and the deactivate path is never gated by the thing it deactivates. A device-scoped switch halts only that device; only a global one halts admin work. `core/app/main.py`, `core/app/kill_switch.py` (`global_only` param), `tests/test_kill_switch_scope.py` (21 tests).
- **R8 — `apply` falsely reported application.** It flipped a row to `applied` and returned 200 while writing nothing. Now returns **202** with `applied=false`, `requires_review=true` and a `patch_ref`; no file is modified. Protected control code (policy engine, kill switch, `main.py`, `agents/`, `audit/`) is refused, as are paths outside the project root and traversal attempts. `core/app/self_improve_apply.py`, `tests/test_self_improve_apply.py` (16 tests).
  - **Three pre-existing tests asserted the false contract** (200 + `status == "applied"`) and passed while the endpoint did nothing. They encoded the bug; rewritten to assert the honest contract.
- **R1 — XSS and stored admin token.** Scraped titles/URLs were interpolated into inline `onclick` handlers where one quote breaks out. Handlers are now bound by delegation reading `data-*` at click time; `safeHttpUrl()` allow-lists `http(s)` so `javascript:`/`data:` can never reach `window.open` or `href`; `escAttr` escapes ampersands and angle brackets; external links get `rel="noopener noreferrer"`. The admin bearer was in `localStorage`, readable by any script on the origin — it is now memory-only and must be re-entered after a reload. `core/static/index.html`, `tests/test_static_xss.py` (12 tests).
- **R2 — RLS policies that were write grants wearing read labels.** Policies commented "readable by all authenticated users" were `FOR ALL ... WITH CHECK (true)`, so any client token could write every row, including `tool_permissions` (the permission table itself). `handoffs` had the same defect — a client could forge the handoff the next device reconstructs from. `tool_runs`, `agent_runs`, `handoffs`, `audit_events`, `tool_permissions` are now read-only to clients; `kill_switch` writes require ownership; `improvement_proposals` may be INSERTed but never UPDATEd or DELETEd, so a proposal cannot self-approve. Service-role full access retained. `supabase/003_rls.sql`, `tests/test_rls_policy_shape.py` (23 tests).
  - **Asserted as policy *shape*, not run against Postgres** — no live database exists. See "Unverified" below.

### Local model inference (R9, partial)

- **R9 — external failures collapsed into normal-looking success.** Providers returned `{"answer": "Model provider not yet configured"}` on failure, indistinguishable from the model replying badly. `OllamaProvider` (`core/app/providers/ollama_provider.py`) raises `ProviderUnavailable` / `ProviderError`; chat maps them to **503** and **502** with no `answer` key at all. An unrecognised `JAX_PROVIDER` now fails at startup instead of silently degrading to `LocalProvider`.
- **Empty completions are not answers.** Proven against a real `deepseek-r1:32b`, which returned `content: ""` with `done_reason: "length"` because the token budget went entirely into its `thinking` field. The adapter raises, naming the truncation; reasoning is surfaced separately as `thinking` and never conflated with `answer`.
- `GET /v1/provider/health` reports reachability and installed models without raising. Deliberately a read and deliberately **not** kill-gated — "why is chat failing" is asked during an incident.
- **Live verified:** `POST /v1/chat` returned a real `qwen3-coder:30b` answer through the retrieval path in 34.5s.

### Carried forward (verified earlier, unchanged)

- **Git preflight control plane (PDF §7, §27)** — `core/app/git_control.py` + `tests/test_git_control.py` (18/18). Deterministic `inspect_repository()` returns READY/BEHIND/AHEAD/DIRTY/DIVERGED/NO_UPSTREAM/DETACHED/REMOTE_UNREACHABLE. A failed/skipped fetch never yields READY. TOCTOU downgrades READY. `launch_allowed` is true only for freshly verified READY.
- **Preflight API `POST /v1/sessions/preflight` (PDF §16)** — admin-only, path must resolve to a `JAX_PROJECT_ROOTS` allowlisted exact root; fast-forward requires fetch.
- **Chat/voice identity + context grounding (R5)** — `core/app/prompts/chat_v1.md` carries JAX's canonical identity, motto, authority model, systems-of-record hierarchy and privacy rules. `build_messages()` feeds the real system prompt + bounded, labeled untrusted retrieval evidence + the user's query last.
- **Memory secret filtering** — `POST /v1/memories` runs `safe_text` on `kind` and `content`, rejecting secret-shaped payloads with 422 before persistence.
- **Retrieval scoping (R6)** — requires exact project scope (`project_id=None` = personal only, not all projects); expired memories excluded.
- **Autonomy policy, agent adapters, managed session lifecycle (phases 5/8/9)** — `policy_engine.py` (L0–L4, payload-bound approvals), `agents/` (Claude, Hermes, generic_cli), `session_manager.py` (preflight → kill switch → policy → launch → verify → handoff).
- **Approvals + audit** — `audit/approvals.py`: deny-by-default, payload-bound, expiring, decisions immutable, denials recorded. Append-only `AuditLog` with no update/delete method.

## NOT yet built / NOT verified

- **Postgres has never been exercised.** Everything runs on SQLite bootstrap. The R2 fixes are asserted as policy *shape* against the SQL file — they have not been run against a live Postgres, and live grants were never inspected. `db.py` uses `create_all`, not migrations; `data/jax.db` had to be deleted once because `create_all` never ALTERs an existing table.
- **R3 is only partially addressed.** Memory writes now redact via `safe_text`, but `self_improve.py` still copies a detected hardcoded-secret line into both proposal code fields, and the analyzer still accepts an arbitrary `project_root` without the node's repository allowlist.
- **R9 is only partially addressed.** Providers and chat are fixed. `leads.py:120–121` still converts every search exception into `[]`, so a failed search is still presented as "no matching leads". `main.py:1032` still hides analysis exceptions. The UI still treats any non-401/403 response as connected.
- **R10 is only partially addressed.** New provider tests are hermetic, but `tests/test_phase4.py:35,52,71` still asserts `status_code in (200, 500)` — it passes while voice is broken.
- **R4** — PostgreSQL UUID/schema contracts disagree with SQLAlchemy/API usage.
- **Supermemory adapter (phase 6)** — `SessionBrief.durable_context` slot exists and is waiting.
- **Memory candidate pipeline (phase 7)** and **per-device project paths/commands/risk (phase 3 remainder)**.
- **Cross-device continuity (PDF §29) — the actual V1 milestone.** Unproven, and unprovable on one laptop. This is the thing more code on this machine cannot substitute for.
- **Live Supermemory** — never called; no credentials configured.

## Hardware constraint on this machine

No discrete GPU (Intel UHD 730 integrated graphics), 31.7 GB RAM. `qwen3-coder:30b` and `deepseek-r1:32b` are ~18.5 GB of weights each and cannot both stay resident, so Ollama evicts and reloads and inference runs on CPU. Live-inference tests are therefore `slow`-marked and opt-in; in the default suite they took 8–13 minutes and timed out on memory contention, which said nothing about the adapter. Both models were verified individually.

## Next action

1. **Hosted deployment first:** see "Next concrete action" under the Vercel pass above.
2. Then: stand up a real Postgres instance and run the RLS role/isolation tests against it — R2 is asserted as SQL text and has never been executed. After that, cross-device continuity needs a second physical machine, which no further work on this laptop can prove.
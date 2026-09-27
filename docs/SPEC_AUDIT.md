# JAX canonical specification audit — baseline source snapshot

## Verdict and boundary

**Spec axis: NO_SHIP as canonical JAX V1 (high confidence). Correctness/security axis: NO_SHIP for remote or production use (high confidence).** The existing product is a real FastAPI/SQLite CRUD and opt-in metadata foundation with chat, voice, and lead-search integrations. It is not yet the deterministic cross-device project control plane defined by the supplied specification. This is not a cosmetic/dashboard gap.

Claim source: **JAX Master Developer Specification, Canonical Architecture, September 27, 2026**, supplied as `C:/Users/blunts/Downloads/JAX_Master_Developer_Specification (1).pdf`. The complete extracted document was read, including sections 1–31 and appendices A–D. References below use PDF section numbers, not the older blueprint. The PDF places section 31 after the appendices.

This audit is **source inspection only**. No application startup, test suite, database query/migration, remote request, credential lookup, or deployment was performed. Database files and credential/environment files were not opened. Existing passing-test claims are not verification evidence for this audit. Only this document was written by the auditor.

**Concurrent-work exclusion:** the parent is adding canonical documentation and a preflight API; another implementer owns `core/app/git_control.py` and `tests/test_git_control.py`. That work is **in progress and not verified by this baseline audit**. Missing preflight references here describe the inspected baseline, not a rejection or verification of concurrent changes. References to `main.py` line ranges describe the baseline read and may shift after integration. Re-audit the integrated preflight and its launch-policy boundary separately.

No `REVIEW.md` was found. Blocking criteria used here: violations of PDF hard security boundaries, misleading claims of execution or evidence, and missing functionality required by the V1 definition of done (§29). Stack recommendations alone are not blockers.

Status vocabulary:

- **Implemented (source):** the narrow described behavior has concrete implementation, not a claim of runtime verification or entire-section completion.
- **Partial:** some relevant behavior exists, but required behavior is absent or contradictory.
- **Missing:** no corresponding implementation was found in inspected source/schema/UI/tests.
- **Not verified:** deployment, runtime, or concurrent-work evidence was intentionally not obtained. Missing is scoped to this source snapshot.

## Ranked correctness and security findings

| ID / priority / confidence | Finding and concrete evidence | Consequence / required correction |
|---|---|---|
| R1 — P1 — high | **Untrusted search results enter JavaScript event-handler strings.** `core/static/index.html:489–495,567–569` interpolates URLs, titles, location, and type into inline `onclick` JavaScript. `escAttr` HTML-encodes quotes, but HTML entity decoding occurs before the handler is parsed as JavaScript; this is not JavaScript-string escaping. URLs are also opened without an explicit scheme allowlist. The admin bearer is persisted in localStorage (`:215–222,238–249`). | Search-derived content can cross the data/code boundary on interaction; the stored admin token increases impact. Replace inline handlers with DOM listeners and data objects, validate HTTP(S) URLs, and avoid persistent all-powerful browser bearer storage. No exploit or token access was attempted. §§18,21. |
| R2 — P1 — high | **RLS policies labeled as readable are actually broad write policies.** `supabase/003_rls.sql:64–67,88–109` uses `FOR ALL TO authenticated` with permissive `USING`/`WITH CHECK` on handoffs, tool runs, agent runs, and proposals. Kill-switch `USING (true)` also exposes deletion under a DELETE grant; its check only constrains new/updated rows. Memory-deletion audit is user-mutable (`:45–49`). | With applicable table grants, authenticated clients can modify/delete other records rather than merely read them. Separate SELECT from owner/project-scoped mutation policies, make audit append-only, and test actual roles/grants. Live grants and installed policies were not inspected. §§10,15,21. |
| R3 — P1 — high | **Secret filtering is limited to events, not durable memory or self-analysis.** `main.py:60–85` validates event text, but `:100–107,361–371` persists memory content without `safe_text` or sensitivity classification. `self_improve.py:225–243` copies a detected hardcoded-secret line into both proposal code fields; `main.py:645–660` persists/returns it. The analyzer accepts arbitrary `project_root` and recursively reads Python files (`self_improve.py:280–307`) without the node's repository allowlist. | An authorized admin can inadvertently store secrets or unrelated local source in operational records; detecting a secret currently copies it. Add mandatory sink-level redaction/rejection, approved canonical roots, bounded scanning, and tests that secret-shaped input is never persisted/returned. This is an admin-reachable privacy/policy bypass, not an unauthenticated route. §§5,10,17,21. |
| R4 — P1 — high | **PostgreSQL and SQLAlchemy/API contracts disagree.** `main.py:200–206` sets administrator identity to literal `admin`, used by writes at `:289–291,317–323,367–371,469–470,610–612`. SQL schema requires UUID ownership/device/actor values (`supabase/001_schema.sql:35–55,61–70,115–121,194–200`). `tables2.py:42` defines memory `source_event_id` as BigInteger while `db.py:16` defines event IDs as strings; SQL uses UUID on both sides (`001_schema.sql:24–29,67`). `db.py:54` uses `create_all`, not migrations. | SQLite tests cannot establish Postgres compatibility. UUID insert paths and fresh Postgres FK creation require correction and isolated integration tests. SQL migrations lack the leads table defined in `tables2.py:158–176`; an application-created table is not evidence it received RLS or migration coverage. §§4,15,21. |
| R5 — P1 — high | **Returned sources do not ground chat.** `main.py:500–516` retrieves context but sends only literal `chat_v1` and the user query to the provider; it attaches sources afterward. Voice repeats this (`:571–582`). The real prompt file (`core/app/prompts/chat_v1.md:5–22`) is not loaded here. | Responses can appear source-backed even though the model never received those sources or identity/policy prompt. Load a versioned prompt and bounded ranked context, preserve provenance, and test the actual provider request payload and unsupported-claim behavior. §§2,5,6,13,19,31. |
| R6 — P1 — high | **Retrieval violates scope and lifecycle semantics.** `retrieval.py:49–66` filters events by devices that have a recent event, not each event's own cutoff; a requested project filters only event type, not project identity. Memories have no expiry filter (`:37–47`); superseded decisions remain eligible (`:68–80`). Zero-score candidates are retained; the so-called token budget counts snippet characters (`:98–107`). | Stale, unrelated, expired, or superseded facts can be returned. Events do not carry a project FK to enforce the intended boundary. Add project/device ownership, per-row time limits, expiry/lineage handling, canonical-source precedence and a real bounded bundle. §§5,6,13,21,23. |
| R7 — P1 — high | **Kill switch is ingestion suspension, not execution cancellation.** The only runtime check in baseline `main.py` is event ingestion (`:255–261`); chat, voice, leads, and analysis do not check it. `kill_switch.py:1–16` only queries activation. There is no child-process/worker stop control. | Do not advertise global stopping. Gate all actionable paths and implement cancellation once agent processes exist. Current threat-model text correctly limits its claim (`docs/THREAT_MODEL.md:20`). §§17,21,23. |
| R8 — P1 — high | **Self-improvement falsely reports application.** `main.py:680–694` changes a row to `applied` after a boolean confirmation, without writing a patch, creating a branch, running verification, merging, or recording an execution receipt. `tests/test_self_improve.py:353–365` verifies only that status string. | Rename to an honest reviewed/approved transition until actual execution exists. Never equate approval with application. Keep future core/policy changes behind review and evidence. §22. |
| R9 — P2 — high | **External failures collapse into normal-looking success.** Provider files `openrouter.py`, `openai_provider.py`, `groq.py:15–21` return an ordinary answer for missing configuration. `leads.py:110–121` turns every search exception into `[]`; `:101–107` reports attempted queries as sources checked. `main.py:751–755` hides analysis exceptions. UI treats any non-401/403 auth response as success (`index.html:219–222,245–249`) and resets chat status to online after failures (`:313–316`). | Distinguish unavailable, failed, empty, partial and completed. Require successful authenticated responses before connected status and show service-level degraded state. A failed search must not be presented as no matching leads. §§12,18,23,24. |
| R10 — P2 — high | **Tests are not hermetic and accept failures as success criteria.** `main.py:14–17` loads environment configuration. `tests/test_phase4.py:17–20,31–71` calls real voice paths without transport stubs and accepts HTTP 500; `tests/test_retrieval.py:17–20,70–87` calls the configured chat provider. Only the later OpenRouter test explicitly mocks HTTP (`test_phase4.py:200–230`). SQL tests check text presence (`:155–174`), and `scripts/verify_supabase.py:51–68` checks RLS enablement/count, not isolation behavior. | A suite run can reach configured remote providers and can pass while voice is broken. Inject fake transports/providers, prevent environment credential loading in tests, fail on unexpected 5xx, add Postgres role/isolation tests and canonical acceptance drills. No suite was run here. §§21,27. |

Additional correctness detail: project creation returns `status: active` even when another status was stored (`main.py:317–324`). Project/task updates accept unconstrained dictionaries (`:340–347,422–428`), so typed field/status validation and immutable-field restrictions are missing. Voice input has no maximum base64 size (`:528–538`), and transcript/answer text is put directly into HTTP headers (`:590–598`); transport-safe encoding and size limits need tests. These are secondary to the foundational and security gaps above.

## Entire-spec section mapping

### Identity, goals and architecture

| PDF section | Baseline status and implementation evidence | Missing or unresolved requirement |
|---|---|---|
| **1. Executive Definition** | **Partial.** Database-backed personal/project records and provider abstraction exist (`main.py:281–517`; `providers/base.py:5–20`). | No verified project/session control plane or cross-device reconstruction. Git, semantic memory, operational state and agent execution are not composed into the ownership contract. |
| **2. Identity, Origin, and Evolution** | **Partial.** `prompts/chat_v1.md:5–22` names a private operating layer. Business work exists separately in `leads.py`. | Prompt is not loaded into chat (R5); no JASON_CORE policy loader. Real-estate identity must remain a module, not the product definition. |
| **3. Primary Product Goals and Use Cases** | **Partial.** Project/task/decision/memory/handoff CRUD and public lead search exist (`main.py:312–517,733–825`). | Cross-device continuity, coding-agent control, daily routines, reminders, connected knowledge and provenance-rich research are missing or incomplete. CRUD is not operational continuity. |
| **4. Target Architecture** | **Partial.** FastAPI, SQLAlchemy, Postgres URL conversion (`db.py:31–54`), Python node, cloud providers, static UI. | Missing session manager, policy engine, memory router to Supermemory, agent orchestrator and notification service. Static HTML rather than recommended Next.js is a stack departure, not itself a failure; absent workflows are the blocker. Postgres compatibility is unverified and contradicted by R4. |

### Memory, code state and continuity

| PDF section | Baseline status and implementation evidence | Missing or unresolved requirement |
|---|---|---|
| **5. Memory Architecture—How JAX Learns** | **Partial.** Explicit save/list/delete, confidence, project FK, optional expiry, deletion metadata (`tables2.py:35–55`; `main.py:361–396`), decision supersedes FK (`tables2.py:70–79`). | No candidate classifier, sensitivity/importance/source/evidence model, duplicate/contradiction workflow, inference decay, enforced expiry or durable correction pipeline. Secrets can persist (R3). |
| **6. Supermemory Integration** | **Missing.** `retrieval.py:22–115` searches only local memories/events/decisions/tasks. No Supermemory adapter found in core. | Read at session start, summarized/explicit write policy, scoped normalization, availability marker, canonical > operational > handoff > semantic precedence and bounded session brief. |
| **7. Git/GitHub Control Plane** | **Partial baseline; new engine in progress, not verified.** `node_windows/node.py:60–95` reads root, branch, HEAD and dirty count with fixed commands. | Baseline has no upstream/remote verification, fetch/ff-only orchestration, READY/BEHIND/AHEAD/DIRTY/DIVERGED/NO_UPSTREAM/DETACHED/REMOTE_UNREACHABLE gate, exact dirty-file display or agent-launch dependency. Node telemetry must not be labeled synchronization. Canonical context-file lifecycle not implemented in baseline. |
| **8. Multi-Device Continuity** | **Partial.** Revocable device IDs/tokens (`main.py:230–249`), persistent event spool (`node.py:98–143`), minimal handoff rows (`tables2.py:81–89`). | No stable configured machine-name/path registry, managed session base/final SHAs, reconstruction protocol or two-device demonstration. Handoff creation records admin as from-device (`main.py:463–470`), not actual machine identity. Phone roles absent. |
| **9. Multi-Agent Orchestration** | **Missing.** `agent_runs` is only a table (`tables2.py:136–146`). | No AgentAdapter availability/version/launch/health/result/stop contract, Claude/Hermes/generic CLI/research/QA adapters, interchangeable SessionBrief, budgets or process recovery. Model providers are not coding-agent adapters. |

### Permissions, context and operating intelligence

| PDF section | Baseline status and implementation evidence | Missing or unresolved requirement |
|---|---|---|
| **10. Permission and Autonomy Model** | **Partial.** Admin/device distinction (`main.py:200–216`), node exact repository allowlist (`node.py:34–57`), draft-level analyzer (`self_improve.py:20`). | L0–L4 enforcement, typed action previews, payload-bound approval/denial and execution-time recheck are missing. `tool_permissions` is storage, not an enforced policy engine. R2/R3 undermine hard boundaries. |
| **11. Context Collection and Senses** | **Partial; narrow collection implemented.** Default-off manual `--once`, explicit Git approval, no active-window collector (`node.py:45–57,212–232`). UI mic is user-triggered (`index.html:344–369`). | Allowlisted filesystem watcher, editor/browser/calendar/email context integrations and inspectable scopes are absent. No claim of continuous surveillance is supported; do not add it to fill a feature checklist. |
| **12. Model Provider and Reasoning Layer** | **Partial.** OpenRouter/OpenAI/Groq HTTP adapters and static environment selection (`main.py:158–175`; provider modules). | No task/sensitivity/cost/latency/capability routing, Anthropic/Google/local model implementation, policy-aware fallback or persistent model/version audit. `LocalProvider` is explicitly a placeholder (`base.py:11–20`). |
| **13. Project Intelligence Layer** | **Partial.** Basic registry has name, workspace, path hint, repo URL and status (`tables2.py:23–33`; `main.py:312–355`). | No device-path map, commands, milestone, stakeholder/constraint/risk fields, allowed agents, memory scope, canonical-file loader or verified session-start brief. |
| **14. JAX Daily, Drift Detection, Personal Alignment** | **Missing behavior.** `daily_summaries` is a table only (`tables2.py:103–112`). | No scheduled morning/evening routines, due-commitment/follow-up queue, drift detectors, priority displacement evidence or notifications. |

### Schema, API, node and interfaces

| PDF section | Baseline status and implementation evidence | Missing or unresolved requirement |
|---|---|---|
| **15. Core Database Schema** | **Partial.** Device/project/task/handoff/permission-related tables exist in `db.py`, `tables2.py`, and `supabase/001_schema.sql`. | No canonical users, project_device_paths, managed sessions, memory_refs or audit_events tables. Handoffs lack session/SHA/files/tests/decisions/unresolved fields; permissions lack project/action/constraint contract. Device SQL has last_seen but ORM/API does not maintain it. R4 prevents treating schemas as equivalent. |
| **16. Core API Surface** | **Partial.** Canonical `GET /v1/projects` and `GET /v1/devices` exist, with reduced semantics (`main.py:238–241,326–330`). | Baseline lacks `/v1/sessions`, launch-agent, verify, session handoff, project context, `/v1/memory/search`, candidates, approvals and `/v1/audit`. `/v1/retrieve`, `/v1/memories`, `/v1/handoffs` are not equivalent contracts. Preflight API is concurrent unverified work. |
| **17. Windows JAX Node** | **Partial.** Opt-in approved Git inspection, environment device identity, bounded durable retry, TLS-or-loopback validation (`node.py:60–209`). | No installed service/health heartbeat, machine/path reconciliation, approved agent/test process manager, exit/log collection, watcher, Windows credential store or stop/cancel protocol. No arbitrary shell exposed by this node is a positive boundary. |
| **18. User Interfaces** | **Partial.** Real static chat/lead tabs, auth and microphone controls (`index.html:133–185,238–429`). | No Today/projects sync states/session monitor/memory corrections/approvals/audit/devices/settings dashboard, phone PWA or notifications. Existing screens do call APIs; they are not proof of the requested control-plane workflows. R1/R9 apply. |
| **19. Voice Interaction** | **Partial.** OpenAI STT/TTS and voice/chat endpoints (`voice.py:14–72`; `main.py:540–599`); explicit browser recording and TTS. | No shared managed-session lifecycle, intent/action policy-preview-confirm-execute-audit chain, explicit retention policy/settings or bounded recording. Browser recognition fallback is not evidence of offline voice. Context is discarded (R5). |
| **20. Tool Registry and MCP/Connector Architecture** | **Missing behavior.** Permission/run tables only (`tables2.py:114–134`). | No typed registry with risk, level, reversibility, network/data scope, timeout and audit enforcement; no MCP integration. Direct lead-search HTTP calls are not a permissioned connector framework. |

### Security, recovery, engineering and release criteria

| PDF section | Baseline status and implementation evidence | Missing or unresolved requirement |
|---|---|---|
| **21. Security and Threat Model** | **Partial.** Device token hashes/revocation, device-bound events, exact node paths, sanitized node errors, URL restrictions, event privacy checks (`main.py:200–273`; `node.py:34–95,146–180,229–232`). | R1–R7; missing append-only action audit, OS credential storage, generalized permissions, process cancellation, verified backups, rate/budget limits and prompt-injection boundary tests. TLS enforcement is node transport logic, not proof of deployed core TLS. |
| **22. Self-Improvement Without Unsafe Self-Modification** | **Partial.** Read-only AST/regex proposal generation; no auto-writing in analyzer (`self_improve.py:251–307`). | No branch/patch/test/security-review/diff/approval/merge pipeline; misleading applied status (R8), secret-copying scanner (R3). Safe absence of execution is not implemented improvement delivery. |
| **23. Failure Handling and Recovery** | **Partial.** Event spool retains retries, conflicts are rejected, HTTP timeouts configured (`node.py:98–182`; `main.py:265–272`). | No agent crash recovery, interrupted session/handoff, adapter switching, contradiction surfacing or tool retry decisions. Search errors are hidden (R9). |
| **24. Offline and Degraded Modes** | **Partial.** Manual local Git observation and queued events survive failed upload (`node.py:185–209`). | No local model, session context cache, durable memory reconciliation, offline-safe action policy or explicit unverified remote-sync state. Missing-key messages do not constitute offline inference. |
| **25. Recommended Repository Structure** | **Partial/departure.** Actual layout is `core/app`, `node_windows`, `supabase`, `tests`, `core/static`, `docs`. | Canonical service boundaries/modules, agent/memory adapters, web/PWA and unit/integration/e2e separation are absent. Moving files to suggested names alone would not implement them. |
| **26. Developer Build Order** | **Partial foundation, not completed phases.** See crosswalk below. | Legacy numbered phases must not be mapped by number to canonical phases 0–16. Baseline work prioritized chat/voice/leads before continuity. |
| **27. Acceptance Tests** | **Partial unit-level precursors; canonical acceptance not demonstrated.** Existing tests inspect auth, CRUD, node safety/spool, retrieval shape, analyzer and provider wiring. | Full scenario-by-scenario evidence matrix below. No acceptance run occurred in this audit. |
| **28. Product Milestones** | **V1 missing as an integrated milestone.** CRUD/node/provider pieces exist. | No basis to claim V1 Continuity, V2 Personal Operating Layer or V3 Delegated Operations. Features resembling later releases do not satisfy missing V1 gates. |
| **29. Definition of Done for First Real JAX** | **Missing end-to-end outcome.** Handoff CRUD (`main.py:463–477`) cannot reconstruct verified project state. | Must prove canonical commit, safe sync/refusal, bounded objective/constraints, chosen agent launch, verification and durable handoff across two computers without old chat. |
| **30. Developer Quick-Start Checklist** | **Partial scaffolding.** Baseline `README.md:7–22` provides setup and test/start commands. | No demonstrated laptop reference install, disposable Git-state fixtures, HANDOFF lifecycle, Supermemory retrieval, Claude restart, Hermes abnormal termination or work-desktop continuity. Source review of this PDF is complete; runtime checklist remains unverified. |
| **31. Final Engineering Principle** | **Partial foundation only.** Deterministic auth, fixed node commands and idempotent ingestion are useful controls. | No integrated deterministic system preserving permissions/context/continuity across model, agent and device changes. UI polish and model responses cannot prove two computers share one verified reality. |

### Appendices

| Appendix | Status / evidence | Gap |
|---|---|---|
| **A — JASON_CORE** | **Missing runtime integration.** Existing chat prompt has general priorities (`prompts/chat_v1.md:7–17`) but is not loaded. | Load versioned canonical policy; preserve Jason's authority and evidence-based challenge format. Concurrent canonical docs are not proof of policy use. |
| **B — Session Brief Template** | **Missing.** Retrieval output contains query/project/source snippets (`retrieval.py:109–115`), not a SessionBrief. | Verified device/agent/repo SHAs and state, objective, constraints, last handoff, bounded context, acceptance, permissions, confirmations and test commands. |
| **C — Handoff Template** | **Partial.** Summary and next action exist (`tables2.py:81–89`). | Session/machine/agent/base/final commit, changed files, command-result verification, decisions, unresolved items and risks; canonical HANDOFF.md lifecycle. |
| **D — Legacy Concepts and Canonical Status** | **Partial alignment.** Node is opt-in and analyzer does not auto-write; lead hunting is present as a module. | Older blueprint/status documents remain historical, not the canonical roadmap. Business persona must not displace personal control-plane identity; no always-on loop or “god-mode” should be introduced. |

## Legacy phases versus canonical build phases (§26)

Baseline `README.md:35–40` calls ingestion Phase 1, CRUD Phase 2, chat/retrieval/self-improvement Phase 3 and dashboard/agents/etc. Phase 4+. `tables2.py:1–3`, `tests/test_core_phase2.py:1–3`, `tests/test_retrieval.py:1`, `tests/test_phase4.py:1` and `supabase/001_schema.sql:1` retain these **legacy labels**. They do not mean canonical Phase 2 Git state engine, Phase 3 project registry, or Phase 4 laptop node are complete. `docs/BUILD_SCOPE.md` describes an earlier blueprint and deliberately narrower milestone. Its original definition of production V1 is not the supplied master PDF's V1 definition.

| Canonical phase(s) | Baseline assessment / exit evidence needed |
|---|---|
| 0 — Specification freeze | Canonical-doc work in progress externally to this audit; confirm vocabulary, devices, permission levels and initial adapters. |
| 1 — Core repo + database | Partial: FastAPI/auth/SQLite and migration sources; reconcile schemas and verify isolated Postgres ownership/migrations/logging/config. |
| 2 — Git state engine | Baseline missing beyond telemetry; concurrent engine not verified. Require disposable-repository state fixtures, remote failure and safe ff-only rechecks. |
| 3 — Project registry | Partial CRUD; missing per-device paths, commands, constraints, risk and context loader. |
| 4 — Windows laptop node | Partial manual metadata node; missing managed process execution, health and secure installed identity. |
| 5 — Session + handoff | Missing managed lifecycle; summary CRUD is only a precursor. |
| 6 — Supermemory adapter | Missing. |
| 7 — Memory candidate pipeline | Partial explicit memory CRUD; missing provenance/sensitivity/corrections/expiry controls. |
| 8 — Agent adapters | Missing Claude, Hermes and generic CLI contract. |
| 9 — Verification hooks | Missing per-project test/lint/build execution gates and receipts. |
| 10 — Dashboard | Chat/leads UI exists; requested operational dashboard missing. |
| 11 — Work desktop node | No installation or cross-device handoff evidence observed. |
| 12 — Phone PWA | Missing. |
| 13 — JAX Daily + reminders | Table only; behavior missing. |
| 14 — Tool registry + connectors | Missing enforced registry; direct lead search is not a substitute. |
| 15 — Hardening | Partial controls; findings above, failure drills and backup/restore remain open. |
| 16 — Specialist agents | Missing orchestration; a lead-search function is not a supervised specialist agent. |

## Canonical acceptance evidence matrix (§27)

Every row is **not demonstrated by this audit**; source precursors are not passes.

| Required scenario | Baseline evidence and gap |
|---|---|
| Clean laptop behind by three commits → fetch, ff-only, matching SHA, launch | Node collects local metadata only (`node.py:60–95`). New Git tests in progress excluded; launch gate missing. |
| Dirty worktree → block auto-sync and display exact changed files | Node only returns dirty count; no sync/launch state machine or file presentation. |
| Divergent device commits → detect and refuse | No baseline ahead/behind comparison or divergence gate. |
| Claude ends → SHA/files/tests/decisions/unresolved/next action recorded | No Claude adapter/session lifecycle; handoff stores summary/next action only. |
| Switch to work desktop → reconstruct without old transcript | Device registration and spooling are precursors, not a reconstruction test. |
| Stale Supermemory fact loses to PROJECT_STATE.md and contradiction logged | Neither Supermemory nor canonical-context ranking/contradiction audit implemented. |
| “Remember this” → provenance/scope/sensitivity, no secret storage | Explicit memory endpoint exists; sensitivity/source candidate pipeline and secret rejection absent. |
| Force push → L4 approval | No managed Git write tool or L4 approval engine; absence of execution is not a passing approval test. |
| Agent crash → recoverable session and adapter switch | No process/session recovery contract. |
| Phone approval denied → action never executes | No phone approval endpoint/state machine/UI or denied-action test. |
| Internet loss → no false GitHub synchronization claim | Node queues failed sends and does not assert sync, but no managed remote-state failure drill. |
| Web injection requests secrets → tool boundary prevents access | No general tool-policy boundary test. UI injection path and analyzer secret persistence require correction (R1/R3). |

## Test inventory and evidence quality

Source-inspected tests:

- `tests/test_core.py`: auth/admin separation, device hashing/revocation, device-bound idempotent events, privacy validation, health/private schema.
- `tests/test_node.py`: exact resolved allowlists, recursive privacy, fixed Git command runner, bounded spool, URL validation, injected retry transport and manual default-off mode. Git runners are fixtures rather than actual repositories in this baseline file.
- `tests/test_core_phase2.py`: record CRUD, deletion, admin restriction, event-ingestion kill switch. Does not demonstrate workflow orchestration or process cancellation.
- `tests/test_retrieval.py`: response shape, limited project request acceptance and stub interface. Project filtering test checks HTTP 200, not absence of another project's data; chat tests do not assert supplied context.
- `tests/test_self_improve.py`: analyzer/serialization/auth/proposal transitions. “Apply succeeds” checks a row status, not patch application. `test_proposals_always_draft` (`:438–446`) points outside the repository's core via `parents[2] / 'core'` and lacks a nonempty assertion, so an empty result can pass vacuously.
- `tests/test_phase4.py`: provider wiring, migration file/text existence and weak voice endpoint assertions; one mocked OpenRouter completion. R10 explains why this is neither hermetic nor integration proof.

Not run: all tests, start scripts, endpoint smoke scripts, migration and verification scripts. No pass count, coverage percentage, live DB compatibility, remote availability, UI exploit reproduction or two-device result is claimed.

## Prioritized delivery gaps (spec axis, separate from risk ranking)

1. **P0 release prerequisite — establish truthful, safe foundations before managed execution.** Resolve R1–R8, make provider/search/UI failures explicit, reconcile UUID/schema/ownership and enforce secret-safe sinks. This priority denotes a release dependency, not a claim of an unauthenticated catastrophic exploit. Exit: isolated negative tests for all boundaries, no false applied/grounded/synchronized status.
2. **P1 — finish canonical phases 0–3.** Freeze source-of-truth docs; integrate/review new Git preflight; persist project/device-path/command/risk/constraint contracts. Exit: all preflight states in disposable repositories, actual remote verification receipts, safe fast-forward only when proven, blocked dirty/diverged/detached/unverified cases, canonical-file loading and no agent launch bypass.
3. **P1 — implement phases 4–9 as one vertical continuity slice.** Secure node identity, managed sessions, durable handoff, Supermemory read-only degraded path, bounded SessionBrief, Claude/Hermes/generic adapters and test/lint/build receipts. Exit: §§27/29 continuity and crash/restart scenarios, including current authorization and repository state rechecks immediately before execution.
4. **P1 — prove phase 11 deliberately, not by inference from HTTP access.** Laptop → desktop reconstruction without the old chat, competing edits/divergence refusal, revoked device and interrupted handoff drills. Preserve exact command/results and SHAs in operational audit.
5. **P2 — dashboard and phone approvals after service contracts exist.** Implement §18 operational views, corrections/forget controls, precise approval previews with expiry/payload binding and deny-by-default behavior. No cosmetic screen should claim a backend state it cannot read.
6. **P2 — complete memory pipeline, Daily/reminders and connector permissions.** Enforce explicit corrections, expiry, scopes, provenance, secret exclusion, offline reconciliation and policy-bound routines. Keep business modules subordinate to the same control plane.
7. **P2 — hardening and specialist expansion.** Append-only/tamper-evident audit, secure credential storage, authenticated TLS deployment, backup/restore/deletion drills, bounded loops, stop/cancel, hermetic tests and monitored failure handling before expanding delegated autonomy.

## Checked boundaries and unassessed surfaces

**Checked, with narrow positive source evidence:** device/admin role separation and token digest storage; device-bound event IDs and conflict handling; opt-in exact-path metadata collection with fixed shell-free commands and timeouts; bounded retry retention; TLS/exact-loopback node URL rules; analyzer does not automatically modify files. These are source observations supported by corresponding test code, not executed passes or a blanket security approval.

**Could not assess / intentionally not assessed:** installed database schema, grants/RLS behavior, deployed TLS/network exposure, real credential hygiene, model/voice/search service behavior, runtime UI rendering and exploitability, actual Windows service installation, backups, two-device continuity, CI/coverage, and concurrently implemented canonical Git preflight/API/docs. Reasons: read-only source scope, no credentials/live services, and concurrent-work separation. Re-audit after integration; do not upgrade this baseline to completed V1 based on documents, route existence, or a green legacy suite alone.

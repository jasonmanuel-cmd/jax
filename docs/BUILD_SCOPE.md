# JAX foundation — accepted starting scope

Source: Jason supplied three Complete Build Blueprint PDFs. All three are byte-identical SHA-256 `09ca8a33541ced72d4ea570b675d4b3a7272acf42dfee6945e1a29f8c6dba553` (58,638 bytes each). One canonical copy is archived as `docs/blueprint.pdf`; no divergent requirements were dropped.

Original names:
- JAX_Personal_AI_Complete_Build_Blueprint.pdf
- JAX_Personal_AI_Complete_Build_Blueprint (1).pdf
- JAX_Personal_AI_Complete_Build_Blueprint (2).pdf

## This milestone

A runnable local foundation, not the blueprint's completed V1:
- FastAPI core, authenticated event ingestion, persistent structured data.
- Independently revocable device credentials, administrator boundary.
- Explicit memory writes/deletion, projects, tasks and handoffs.
- Persisted kill switch and content-minimizing audit records.
- Opt-in metadata-only Git node, durable bounded retry spool, privacy checks.
- Automated tests and a live loopback integration verification.

## Deliberate departures from production target

SQLite is the local bootstrap database so development does not require cloud credentials or change any business database. SQLAlchemy provides a PostgreSQL configuration path; PostgreSQL/Supabase is NOT verified merely because the URL is configurable. Python 3.11 is used in an isolated environment on this host; the PDF suggests 3.12. Migration/compatibility verification remains necessary.

No Next.js dashboard, model chat, embeddings, specialist orchestration, automatic classification, daily scheduler, notifications, voice or Android integration is claimed in this milestone. No fake model responses or sample business state stand in for those features. Provider/model selection is deferred; no model costs or evaluation metrics exist yet. The initial tests evaluate deterministic policy/storage behavior, not LLM quality.

## Permission matrix

| Capability | Current starting boundary |
| --- | --- |
| Health | Public, no personal data |
| Device provisioning/revocation | Administrator |
| Event ingestion | Authenticated device, its own identity only |
| Read personal state | Administrator only |
| Organize JAX records | Administrator only; explicit user action |
| Observe repositories | Node opt-in, explicit allowlist, metadata only |
| Observe windows/screens/audio/clipboard | Not activated |
| Execute code or computer actions | Not implemented |
| Send/deploy/delete external files/purchase | Not implemented; future per-action approval |
| Extract credentials/disable protections | Never supported |

## Next milestones, in dependency order

1. Verify PostgreSQL migrations and row-level/user ownership isolation in a dedicated JAX database.
2. Build authenticated dashboard and device enrollment UI; secure credentials with OS keychain.
3. Approve narrowly scoped local collectors and prove a real event reaches core.
4. Add source-grounded retrieval, versioned prompts and a configurable provider boundary; choose actual model with Jason.
5. Evaluate grounded chat and handoffs; require cited records and clearly labeled inference.
6. Secure private-network cross-device access; validate second PC and phone end-to-end.
7. Add bounded tools with host-issued payload-bound approvals and execution-time policy rechecks.
8. Daily briefs, specialist agents, backup/restore drills, retention, migrations and hardening.

Production V1 remains incomplete until two computers, grounded chat, reliable handoffs, daily briefs and consequential-action confirmation have been demonstrated, as required by the blueprint.

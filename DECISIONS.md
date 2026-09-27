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

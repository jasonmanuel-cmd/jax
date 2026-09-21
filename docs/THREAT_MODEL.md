# JAX foundation threat model

## Scope and assets

Single-owner local development. Assets: personal memory, project state, device credentials, administrator credential and local event queue. Trust boundaries: administrator → core; node → core; collector → repository metadata; core → database. Authentication is not permission to execute arbitrary machine actions.

## Threats and controls

- Unauthenticated reads/writes: authenticate all personal-data routes. Keep health minimal. Verify unauthorized denial in automated and live tests.
- Compromised node: device tokens ingest only their own events, cannot enroll/revoke peers or read/administer personal memory. Independently revoke devices.
- Credential disclosure: no credentials in logs, source, memory or git; persist device token hashes only in core. Runtime secrets outside version control. Environment bootstrap is development-only; move to OS credential storage for installation.
- Device spoofing: bind supplied device ID to authenticated token server-side.
- Replay: stable event UUID and idempotent insertion; reject conflicting reuse rather than replace records.
- Sensitive context: no keystrokes, screenshots, clipboard, continuous audio, raw diffs or file contents. Explicit collector enablement and repository allowlist. Privacy heuristics are defense-in-depth, NOT a guarantee that arbitrary free text is secret-free.
- Path escape: canonicalize paths and enforce exact scoped repositories. Never accept arbitrary shell commands from API or node config.
- Lost connectivity: bounded local spool, retain pending items until confirmed success, retry stable IDs. Local SQLite data is not encrypted by this application; OS account/disk protection remains necessary.
- Accidental exposure: bind core to 127.0.0.1 only. No router forwarding, public tunnel, deployment or firewall change. Remote setup needs dedicated authenticated TLS/private network design.
- Malicious context/instructions: observations remain data. There is no execution/LLM loop in this milestone. Future model output cannot authorize permissions or record writes by itself.
- Administrative mistakes: explicit memory deletion removes content from future reads; audit metadata should not copy the deleted content. Future backup restore must honor deletion state.
- Kill switch: persist suspension state and enforce before accepting node activity. This is not an OS process termination feature or an unimplemented tool-execution guarantee.

## Known limitations / production gates

Local admin compromise and other processes under the same OS account are outside this prototype's protective boundary. No at-rest application encryption, external security review, multi-user/tenant rollout, verified Supabase RLS, tested encrypted backups, token-expiry automation, production rate limiting or remote access is claimed. Generated credentials must never be printed into chat. Device token delivery must eventually use secure enrollment rather than manual environment setup.

No live collector is enabled merely by installing or starting the core. Approval to build the software is not approval to begin observing the desktop.

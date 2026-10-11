"""Session manager: preflight gate, launch, verify, close.

This is the phase 5/9 spine. It enforces the spec's ordering rule — prove
repository state, check the kill switch, check policy, *then* launch — and it
never reports completion that verification did not prove.

State is written to agent_runs so a crashed session survives the process that
started it and can be handed to another adapter.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ..agents import AgentResult, SessionBrief
from ..git_control import inspect_repository
from ..kill_switch import is_kill_active
from ..policy_engine import PolicyDenied
from ..db import devices
from ..tables2 import agent_runs, handoffs, projects


class LaunchRefused(Exception):
    """A launch was refused. Carries the HTTP status the API should return."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(f'{code}: {detail}')
        self.status = status
        self.code = code
        self.detail = detail


class SessionManager:
    def __init__(self, engine, adapters, policy_engine):
        self.engine = engine
        self.adapters = adapters
        self.policy = policy_engine

    # -- helpers ----------------------------------------------------------

    def _project(self, db, project_id: str):
        project = db.execute(
            select(projects).where(projects.c.id == project_id)
        ).mappings().first()
        if project is None:
            raise LaunchRefused(404, 'project_not_found', project_id)
        return project

    def _resolve_device(self, db, machine_id: str | None) -> str | None:
        """Map a local machine name to a provisioned device, if one exists.

        Device identity lives in local config as a name like "travel-laptop",
        not a device UUID. agent_runs.machine_id always records where the work
        happened; device_id is set only when that machine is actually enrolled,
        so an unenrolled machine cannot forge a device reference.
        """
        if not machine_id:
            return None
        row = db.execute(
            select(devices.c.id).where(devices.c.name == machine_id)
        ).first()
        return row[0] if row else None

    def _record_run(self, db, session_id: str, adapter: str, objective: str,
                    status: str, machine_id: str | None = None,
                    project_id: str | None = None, model: str | None = None,
                    device_id: str | None = None):
        now = datetime.now(timezone.utc)
        db.execute(agent_runs.insert().values(
            id=session_id, agent_name=adapter, objective=objective,
            status=status, model=model, started_at=now,
            finished_at=now if status != 'running' else None,
            machine_id=machine_id, project_id=project_id,
            device_id=device_id))

    def _finish_run(self, db, session_id: str, status: str):
        db.execute(agent_runs.update()
                   .where(agent_runs.c.id == session_id)
                   .values(status=status,
                           finished_at=datetime.now(timezone.utc)))

    # -- preflight --------------------------------------------------------

    def preflight(self, project_id: str, root: str, fetch: bool = True,
                  fast_forward: bool = False, device_id: str | None = None) -> dict:
        """Prove repository state. Never raises on an unsafe repo; returns state."""
        with self.engine.connect() as db:
            if is_kill_active(db, device_id):
                raise LaunchRefused(403, 'kill_switch_active',
                                    'A kill switch is active; no agent may launch')
        try:
            state = inspect_repository(root, fetch=fetch,
                                      fast_forward=fast_forward)
        except (ValueError, OSError, RuntimeError) as exc:
            raise LaunchRefused(409, 'preflight_failed', str(exc)[:200])
        return state

    # -- launch -----------------------------------------------------------

    def launch(self, project_id: str, machine_id: str, agent_name: str,
               objective: str, brief: SessionBrief | None = None,
               repo_state: dict | None = None) -> dict:
        """Launch an adapter only if preflight, kill switch and policy all allow."""
        # Resolve and gate everything BEFORE writing a run row. Recording a
        # 'running' session for a launch that never happened is exactly the
        # kind of false claim the spec forbids, and it would orphan the row.
        try:
            adapter = self.adapters.get(agent_name)
        except KeyError:
            raise LaunchRefused(404, 'unknown_adapter', agent_name)

        # Policy is checked before the adapter is probed or launched, so an
        # unapproved agent cannot cause side effects by starting up.
        try:
            self.policy.check('process.launch_agent', {'agent': agent_name})
        except PolicyDenied as exc:
            raise LaunchRefused(403, exc.code, exc.detail)

        if not adapter.available():
            raise LaunchRefused(
                409, 'adapter_unavailable',
                f'{agent_name} is not installed on this host; not claiming a launch')

        with self.engine.begin() as db:
            project = self._project(db, project_id)
            if project['status'] != 'active':
                raise LaunchRefused(409, 'project_not_active', project_id)
            device_id = self._resolve_device(db, machine_id)
            if is_kill_active(db, device_id):
                raise LaunchRefused(403, 'kill_switch_active',
                                    'A kill switch is active; no agent may launch')

        if brief is None:
            brief = SessionBrief(project=project['name'], device=machine_id,
                                 agent=agent_name,
                                 timestamp=datetime.now(timezone.utc).isoformat())
        if repo_state:
            brief.branch = repo_state.get('branch')
            brief.local_head = repo_state.get('head')
            brief.remote_head = repo_state.get('upstream_head')
            brief.sync_state = repo_state.get('state', 'UNKNOWN')
            brief.dirty_files = list(repo_state.get('dirty_files', []))

        session = adapter.launch(project['path_hint'] or '.', brief)

        # Keyed by the adapter's session id, so /verify can find the run that
        # actually happened. A crashed launch is still recorded: it is
        # recoverable, and an unrecorded crash would look like it never ran.
        with self.engine.begin() as db:
            self._record_run(db, session.id, agent_name, objective,
                            session.status, machine_id=machine_id,
                            project_id=project_id, device_id=device_id)

        return {'session_id': session.id, 'adapter': session.adapter,
                'status': session.status, 'base_commit': session.base_commit,
                'error': session.error, 'brief': brief.to_dict()}

    # -- verify + close ---------------------------------------------------

    def verify_and_close(self, session_id: str, root: str | None = None,
                         test_commands: list[str] | None = None,
                         fetch: bool = False) -> dict:
        """Run verification, then write a handoff from proven state only."""
        run = self._load_run(session_id)
        adapter_name = run['agent_name']

        try:
            adapter = self.adapters.get(adapter_name)
        except KeyError:
            raise LaunchRefused(404, 'unknown_adapter', adapter_name)
        result: AgentResult = adapter.collect_result(session_id)

        repo_state = None
        if root:
            # fetch defaults off: closing a session must not silently mutate the
            # working tree or depend on the network to write a truthful handoff.
            try:
                repo_state = inspect_repository(root, fetch=fetch)
            except (ValueError, OSError, RuntimeError):
                repo_state = None

        receipts = []
        for command in test_commands or []:
            receipts.append(self._run_verification(command, root))

        verification_passed = all(r['exit_code'] == 0 for r in receipts) if receipts else None

        with self.engine.begin() as db:
            self._finish_run(db, session_id,
                             result.status if result.status != 'unknown' else 'exited')
            handoff_id = str(uuid4())
            summary = self._summary(result, repo_state, receipts)
            db.execute(handoffs.insert().values(
                id=handoff_id, from_device=run.get('machine_id'),
                project_id=run.get('project_id'),
                summary=summary,
                next_action=('Investigate the failure; the session did not verify'
                             if verification_passed is False else
                             'Continue from the recorded state'),
                created_at=datetime.now(timezone.utc)))

        return {'session_id': session_id, 'agent': adapter_name,
                'status': result.status, 'exit_code': result.exit_code,
                'base_commit': result.base_commit,
                'final_commit': result.final_commit,
                'changed_files': result.changed_files,
                'repository_state': repo_state,
                'verification': receipts,
                'verification_passed': verification_passed,
                'handoff_id': handoff_id, 'error': result.error}

    def _load_run(self, session_id: str) -> dict:
        with self.engine.connect() as db:
            row = db.execute(
                select(agent_runs).where(agent_runs.c.id == session_id)
            ).mappings().first()
        if row is None:
            raise LaunchRefused(404, 'session_not_found', session_id)
        return dict(row)

    def _run_verification(self, command: str, root: str | None) -> dict:
        """Run one test/lint/build command and record the real result."""
        import subprocess
        cwd = root or '.'
        try:
            proc = subprocess.run(command, shell=True, cwd=cwd,
                                  capture_output=True, text=True,
                                  encoding='utf-8', errors='replace',
                                  timeout=900, check=False)
        except subprocess.TimeoutExpired:
            return {'command': command, 'exit_code': None, 'timed_out': True,
                    'tail': ''}
        except OSError as exc:
            return {'command': command, 'exit_code': None,
                    'error': type(exc).__name__, 'tail': ''}
        tail = (proc.stdout or proc.stderr or '').strip().splitlines()
        return {'command': command, 'exit_code': proc.returncode,
                'timed_out': False, 'tail': tail[-1][:300] if tail else ''}

    @staticmethod
    def _summary(result: AgentResult, repo_state: dict | None,
                 receipts: list[dict]) -> str:
        parts = [f'Agent {result.adapter} ended with status {result.status}']
        if result.exit_code is not None:
            parts.append(f'exit code {result.exit_code}')
        if result.base_commit:
            parts.append(f'base commit {result.base_commit}')
        if result.final_commit:
            parts.append(f'final commit {result.final_commit}')
        if result.changed_files:
            parts.append(f'changed files: {", ".join(result.changed_files[:20])}')
        if repo_state:
            parts.append(f'repository state {repo_state.get("state")} '
                         f'(branch {repo_state.get("branch")}, '
                         f'HEAD {str(repo_state.get("head"))[:12]})')
        for receipt in receipts:
            parts.append(f'verification "{receipt["command"]}" '
                         f'exit {receipt["exit_code"]}'
                         + (' (timed out)' if receipt.get('timed_out') else ''))
        if result.error:
            parts.append(f'error: {result.error}')
        return '; '.join(parts)
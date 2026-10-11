"""Agent adapter contract and session brief.

Agents and models are replaceable workers. JAX owns the session contract, so
swapping Claude for Hermes must not change what a session records.

The brief is the anti-amnesia artifact: it must let a device reconstruct the
project without the previous agent's transcript.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..policy_engine import LEVEL_NAMES


@dataclass
class SessionBrief:
    """Bounded context handed to an agent at launch.

    Every field is either verified state or an explicit gap. Nothing here may
    claim synchronization, health, or completion that was not proven.
    """
    project: str
    device: str
    agent: str
    timestamp: str
    branch: str | None = None
    local_head: str | None = None
    remote_head: str | None = None
    sync_state: str = 'UNKNOWN'
    dirty_files: list[str] = field(default_factory=list)
    objective: str = ''
    constraints: list[str] = field(default_factory=list)
    last_handoff: str | None = None
    durable_context: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    permitted_actions: list[str] = field(default_factory=list)
    requires_confirmation: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'project': self.project,
            'device': self.device,
            'agent': self.agent,
            'timestamp': self.timestamp,
            'verified_repository_state': {
                'branch': self.branch,
                'local_head': self.local_head,
                'remote_head': self.remote_head,
                'sync_state': self.sync_state,
                'dirty_files': self.dirty_files,
            },
            'objective': self.objective,
            'constraints': self.constraints,
            'last_handoff': self.last_handoff,
            'durable_context': self.durable_context,
            'acceptance_criteria': self.acceptance_criteria,
            'permitted_actions': self.permitted_actions,
            'requires_confirmation': self.requires_confirmation,
            'test_commands': self.test_commands,
        }


@dataclass
class AgentSession:
    """A launched agent process, tracked so it stays recoverable after a crash."""
    id: str
    adapter: str
    cwd: str
    status: str = 'running'          # running | exited | crashed | stopped
    base_commit: str | None = None
    final_commit: str | None = None
    exit_code: int | None = None
    error: str | None = None
    changed_files: list[str] = field(default_factory=list)

    @property
    def recoverable(self) -> bool:
        """A crashed session is resumable; it is not a dead session.

        The brief is retained, so another adapter can be handed the same work.
        """
        return self.status in {'running', 'crashed', 'exited'}


@dataclass
class AgentResult:
    session_id: str
    adapter: str
    status: str
    exit_code: int | None = None
    base_commit: str | None = None
    final_commit: str | None = None
    changed_files: list[str] = field(default_factory=list)
    error: str | None = None


@runtime_checkable
class AgentAdapter(Protocol):
    """The replaceable-worker contract from the canonical spec.

    Implementations must be honest: available() reflects a real probe,
    collect_result() reports the real exit status, and nothing may claim
    success the process did not achieve.
    """

    name: str

    def available(self) -> bool:
        """True only if this adapter can actually run on this host."""

    def version(self) -> str:
        """Installed version, or an explicit 'unknown'."""

    def launch(self, cwd: str, brief: SessionBrief) -> AgentSession:
        """Start the worker in cwd with the brief."""

    def healthcheck(self) -> dict:
        """Diagnostic detail for the dashboard."""

    def collect_result(self, session_id: str) -> AgentResult:
        """Report the true outcome of a launched session."""

    def stop(self, session_id: str) -> None:
        """Terminate a session. Must be safe to call twice."""


class BaseAdapter:
    """Shared plumbing: availability probing and session bookkeeping.

    Subclasses implement _build_command() and _interpret_exit(); everything
    else (probing, session storage, timeouts) is inherited so behaviour does
    not drift between adapters.
    """

    name = 'base'

    def __init__(self, executable: str | None = None, timeout: int = 900,
                 env_overrides: dict[str, str] | None = None):
        self.executable = executable or self.default_executable()
        self.timeout = timeout
        self.env_overrides = env_overrides or {}
        self._sessions: dict[str, AgentSession] = {}

    @staticmethod
    def default_executable() -> str:
        return 'true'  # POSIX no-op; harmless on Windows

    def _probe_version(self) -> str | None:
        import subprocess
        try:
            out = subprocess.run([self.executable, '--version'],
                                 capture_output=True, text=True,
                                 timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return (out.stdout or out.stderr or '').strip() or None

    def available(self) -> bool:
        return self._probe_version() is not None

    def version(self) -> str:
        return self._probe_version() or 'unknown'

    def healthcheck(self) -> dict:
        probe = self._probe_version()
        return {'adapter': self.name, 'executable': self.executable,
                'available': probe is not None, 'version': probe or 'unknown'}

    def launch(self, cwd: str, brief: SessionBrief) -> AgentSession:
        raise NotImplementedError

    def collect_result(self, session_id: str) -> AgentResult:
        session = self._sessions.get(session_id)
        if session is None:
            return AgentResult(session_id=session_id, adapter=self.name,
                               status='unknown', error='No such session')
        return AgentResult(
            session_id=session.id, adapter=self.name, status=session.status,
            exit_code=session.exit_code, base_commit=session.base_commit,
            final_commit=session.final_commit, changed_files=[],
            error=session.error)

    def stop(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None and session.status == 'running':
            session.status = 'stopped'

    def _record(self, session: AgentSession) -> AgentSession:
        self._sessions[session.id] = session
        return session
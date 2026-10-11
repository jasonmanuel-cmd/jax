"""Generic CLI adapter: any executable that accepts a working directory and a prompt.

This is the reference adapter because it has no external dependency, which
makes the session contract testable without Claude or Hermes installed. It is
third in the spec's V1 order but first here for that reason.

The prompt is passed on stdin rather than argv: a long brief routinely exceeds
Windows' command-line length limit, and passing untrusted text through argv is
its own hazard.
"""
from __future__ import annotations

import subprocess
from uuid import uuid4

from .base import AgentResult, AgentSession, BaseAdapter, SessionBrief


class GenericCliAdapter(BaseAdapter):
    """Runs `<executable> --prompt-stdin` inside the project directory."""

    name = 'generic_cli'

    def __init__(self, executable: str = 'python', timeout: int = 900,
                 env_overrides: dict[str, str] | None = None):
        super().__init__(executable=executable, timeout=timeout,
                         env_overrides=env_overrides)

    def _build_command(self) -> list[str]:
        return [self.executable, '-c',
                'import sys; sys.stdin.read()']

    def launch(self, cwd: str, brief: SessionBrief) -> AgentSession:
        import json
        import os

        session = AgentSession(id=str(uuid4()), adapter=self.name, cwd=cwd)
        payload = json.dumps(brief.to_dict(), indent=2)

        env = os.environ.copy()
        env.update(self.env_overrides)
        env['JAX_SESSION_ID'] = session.id
        env['JAX_PROJECT'] = brief.project
        env['JAX_SYNC_STATE'] = brief.sync_state

        try:
            proc = subprocess.run(
                self._build_command(), input=payload, cwd=cwd, env=env,
                capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            session.status = 'crashed'
            session.error = f'Agent exceeded {self.timeout}s and was terminated'
            return self._record(session)
        except OSError as exc:
            session.status = 'crashed'
            session.error = f'Could not start agent: {type(exc).__name__}'
            return self._record(session)

        session.exit_code = proc.returncode
        if proc.returncode == 0:
            session.status = 'exited'
        elif proc.returncode is not None and proc.returncode < 0:
            # Negative on POSIX means killed by signal.
            session.status = 'crashed'
            session.error = f'Terminated by signal {-proc.returncode}'
        else:
            session.status = 'crashed'
            detail = (proc.stderr or proc.stdout or '').strip().splitlines()
            session.error = detail[-1][:300] if detail else f'exit {proc.returncode}'
        return self._record(session)

    def collect_result(self, session_id: str) -> AgentResult:
        result = super().collect_result(session_id)
        session = self._sessions.get(session_id)
        if session is not None:
            result.changed_files = list(session.changed_files)
        return result
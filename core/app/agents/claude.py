"""Claude adapter.

Built from the spec's adapter contract, not from Claude's private API: it
launches the `claude` CLI in the project directory and feeds it the session
brief. Availability is a real probe, so a host without Claude reports itself
unavailable instead of failing at launch.
"""
from __future__ import annotations

import json
import os
import subprocess
from uuid import uuid4

from .base import AgentSession, BaseAdapter, SessionBrief


class ClaudeAdapter(BaseAdapter):
    """Launches `claude` with the brief on stdin."""

    name = 'claude'

    def __init__(self, executable: str = 'claude', timeout: int = 1800,
                 model: str | None = None,
                 env_overrides: dict[str, str] | None = None):
        super().__init__(executable=executable, timeout=timeout,
                         env_overrides=env_overrides)
        self.model = model

    def _build_command(self) -> list[str]:
        command = [self.executable, '-p']
        if self.model:
            command += ['--model', self.model]
        return command

    def launch(self, cwd: str, brief: SessionBrief) -> AgentSession:
        session = AgentSession(id=str(uuid4()), adapter=self.name, cwd=cwd)

        if not self.available():
            session.status = 'crashed'
            session.error = (f'{self.executable} is not installed or not on PATH; '
                             'refusing to claim a launch that did not happen')
            return self._record(session)

        env = os.environ.copy()
        env.update(self.env_overrides)
        env['JAX_SESSION_ID'] = session.id

        try:
            proc = subprocess.run(
                self._build_command(), input=json.dumps(brief.to_dict(), indent=2),
                cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            session.status = 'crashed'
            session.error = f'Claude exceeded {self.timeout}s and was terminated'
            return self._record(session)
        except OSError as exc:
            session.status = 'crashed'
            session.error = f'Could not start Claude: {type(exc).__name__}'
            return self._record(session)

        session.exit_code = proc.returncode
        if proc.returncode == 0:
            session.status = 'exited'
        else:
            session.status = 'crashed'
            detail = (proc.stderr or proc.stdout or '').strip().splitlines()
            session.error = detail[-1][:300] if detail else f'exit {proc.returncode}'
        return self._record(session)
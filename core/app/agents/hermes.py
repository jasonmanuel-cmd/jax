"""Hermes adapter.

The spec explicitly requires testing abnormal TUI termination for Hermes, so
this adapter does not assume a TTY and treats any non-zero or signal exit as a
crash rather than a normal end. A crashed session stays recoverable: the brief
survives so another adapter can receive the same work.
"""
from __future__ import annotations

import json
import os
import subprocess
from uuid import uuid4

from .base import AgentSession, BaseAdapter, SessionBrief


class HermesAdapter(BaseAdapter):
    """Launches `hermes` non-interactively with the brief on stdin."""

    name = 'hermes'

    def __init__(self, executable: str = 'hermes', timeout: int = 1800,
                 env_overrides: dict[str, str] | None = None):
        super().__init__(executable=executable, timeout=timeout,
                         env_overrides=env_overrides)

    def _build_command(self) -> list[str]:
        return [self.executable, '--stdin']

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
        # No TTY is allocated, so a TUI that demands one must fail loudly
        # instead of hanging until the timeout.
        env.setdefault('TERM', 'dumb')
        env['CI'] = '1'

        try:
            proc = subprocess.run(
                self._build_command(), input=json.dumps(brief.to_dict(), indent=2),
                cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            session.status = 'crashed'
            session.error = (f'Hermes exceeded {self.timeout}s; terminated. '
                             'Session retained and resumable.')
            return self._record(session)
        except OSError as exc:
            session.status = 'crashed'
            session.error = f'Could not start Hermes: {type(exc).__name__}'
            return self._record(session)

        session.exit_code = proc.returncode
        if proc.returncode == 0:
            session.status = 'exited'
        else:
            session.status = 'crashed'
            detail = (proc.stderr or proc.stdout or '').strip().splitlines()
            session.error = detail[-1][:300] if detail else f'exit {proc.returncode}'
        return self._record(session)
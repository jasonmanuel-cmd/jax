"""Opt-in manual metadata node; importing this module performs no I/O."""
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


_SECRET = re.compile(
    r'password|bitwarden|keepass|1password|lastpass|dashlane|private[ _-]?key|seed[ _-]?phrase|'
    r'api[ _-]?key|access[ _-]?token|refresh[ _-]?token|client[ _-]?secret|authorization|'
    r'bearer\s+\S+|sk-[\w-]{16,}|gh[pousr]_[\w]{20,}|github_pat_[\w]+|'
    r'AKIA[A-Z0-9]{16}|eyJ[\w-]+\.[\w-]+\.[\w-]+', re.I
)


def allowed_event(value, _depth=0):
    """Fail closed on unsupported, oversized or deeply nested values."""
    if _depth > 20:
        return False
    if isinstance(value, str):
        text = unicodedata.normalize('NFKC', value)
        text = ''.join(c for c in text if unicodedata.category(c) != 'Cf')
        return len(value) <= 8192 and not _SECRET.search(text)
    if isinstance(value, dict):
        return len(value) <= 100 and all(
            isinstance(k, str) and allowed_event(k, _depth + 1) and allowed_event(v, _depth + 1)
            for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return len(value) <= 100 and all(allowed_event(v, _depth + 1) for v in value)
    return value is None or type(value) in (bool, int, float)


def approved_repo(path, config):
    try:
        resolved = Path(path).resolve(strict=True)
        approved = {Path(p).resolve(strict=True) for p in config.approved_repositories}
    except (OSError, RuntimeError):
        raise PermissionError('Repository is not approved') from None
    if resolved not in approved or not resolved.is_dir():
        raise PermissionError('Repository is not approved')
    return resolved


@dataclass(frozen=True)
class Config:
    git_enabled: bool = False
    active_window_enabled: bool = False
    approved_repositories: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.git_enabled) is not bool or self.active_window_enabled is not False:
            raise ValueError('Collectors require explicit boolean approval; active window is deferred')
        if not isinstance(self.approved_repositories, (tuple, list)) or any(
            not isinstance(p, str) or not Path(p).is_absolute() for p in self.approved_repositories
        ):
            raise ValueError('Approved repositories must be absolute paths')


def collect_git(path, config, device_id, *, runner=None):
    import os
    import subprocess
    from uuid import UUID, uuid4
    from datetime import datetime, timezone
    if not config.git_enabled:
        return None
    repo = approved_repo(path, config)
    # Linked worktrees/submodules can point outside approval; deliberately deferred.
    git_dir = repo / '.git'
    if not git_dir.is_dir() or git_dir.is_symlink() or git_dir.resolve().parent != repo:
        raise PermissionError('Only standalone approved repositories are supported')
    run = runner or subprocess.check_output
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    def git(*args):
        return run(['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=' + os.devnull,
                    '-c', 'status.renames=false', '-C', str(repo), *args],
                   timeout=5, shell=False, text=True, encoding='utf-8', errors='replace',
                   stderr=subprocess.DEVNULL, env=env)
    if Path(git('rev-parse', '--show-toplevel').strip()).resolve() != repo:
        raise PermissionError('Repository root differs from approval')
    branch = git('branch', '--show-current').strip()
    commit = git('rev-parse', '--verify', 'HEAD').strip()
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
        raise ValueError('Invalid commit hash')
    status = git('status', '--porcelain=v1', '-z', '--untracked-files=normal')
    event = {'event_id': str(uuid4()), 'device_id': str(UUID(device_id)),
             'type': 'git_context', 'summary': 'Approved repository Git metadata', 'app': 'git',
             'metadata': {'branch': branch, 'commit_hash': commit,
                          'dirty_count': sum(bool(s) for s in status.split('\0'))},
             'occurred_at': datetime.now(timezone.utc).isoformat()}
    if not allowed_event(event):
        raise PermissionError('Event rejected by privacy policy')
    return event


class Spool:
    """Bounded persistent queue. Overflow rejects NEW events; never evicts retries."""
    def __init__(self, path, max_events=1000):
        import sqlite3
        if type(max_events) is not int or not 1 <= max_events <= 10000:
            raise ValueError('Invalid spool bound')
        self.max_events = max_events
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA max_page_count=65536')  # 256 MiB at default 4 KiB pages
        self.db.execute('CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def enqueue(self, event):
        import json
        from uuid import UUID
        payload = json.dumps(event, allow_nan=False, separators=(',', ':'))
        if len(payload.encode('utf-8')) > 16384:
            raise ValueError('Event exceeds spool limit')
        if not allowed_event(event):
            raise PermissionError('Event rejected by privacy policy')
        event_id = str(UUID(event['event_id']))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT payload FROM events WHERE event_id=?', (event_id,)).fetchone()
            if old:
                if old[0] != payload:
                    raise ValueError('Event ID already has a different payload')
                return
            if self.db.execute('SELECT count(*) FROM events').fetchone()[0] >= self.max_events:
                raise OverflowError('Spool full; pending events retained')
            self.db.execute('INSERT INTO events VALUES (?, ?)', (event_id, payload))

    def pending(self):
        import json
        return [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM events ORDER BY rowid LIMIT ?', (self.max_events,))]

    def ack(self, event_id):
        with self.db:
            self.db.execute('DELETE FROM events WHERE event_id=?', (event_id,))


def events_url(core_url):
    from urllib.parse import urlsplit
    if not isinstance(core_url, str) or any(ord(c) <= 32 for c in core_url) or '\\' in core_url:
        raise ValueError('Invalid Core URL')
    parts = urlsplit(core_url)
    if (parts.scheme not in ('http', 'https') or not parts.hostname or
            parts.username is not None or parts.password is not None or
            parts.query or parts.fragment or parts.path not in ('', '/') or
            (parts.scheme == 'http' and parts.hostname not in ('localhost', '127.0.0.1', '::1'))):
        raise ValueError('Core requires TLS except exact loopback hosts')
    _ = parts.port
    return core_url.rstrip('/') + '/v1/events'


def flush(spool, core_url, token, device_id, *, transport=None):
    """Transport injection is for TEST ONLY; CLI never accepts a transport override."""
    import httpx
    from uuid import UUID
    url = events_url(core_url)
    device_id = str(UUID(device_id))
    if not token or not re.fullmatch(r'[A-Za-z0-9._~+/-]+=*', token):
        raise ValueError('Missing or invalid device credential')
    sent = 0
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False,
                      transport=transport) as client:
        for event in spool.pending():
            if event.get('device_id') != device_id or not allowed_event(event):
                break
            try:
                response = client.post(url, json=event, headers={'Authorization': 'Bearer ' + token})
                if not 200 <= response.status_code < 300 or response.json().get('accepted') is not True:
                    break
            except (httpx.HTTPError, ValueError, AttributeError):
                break
            spool.ack(event['event_id'])
            sent += 1
    return sent


def run_once(config, *, environ=None, spool_path=None, runner=None, transport=None):
    import os
    from uuid import UUID
    if not config.git_enabled:
        return {'disabled': True, 'queued': 0, 'sent': 0}
    env = os.environ if environ is None else environ
    device_id = str(UUID(env['JAX_DEVICE_ID']))
    token = env['JAX_NODE_TOKEN']
    core_url = env['JAX_CORE_URL']
    events_url(core_url)
    if not token or not re.fullmatch(r'[A-Za-z0-9._~+/-]+=*', token):
        raise ValueError('Invalid device credential')
    if spool_path is None:
        parent = Path(env['LOCALAPPDATA']) / 'JAX'
        parent.mkdir(parents=True, exist_ok=True)
        spool_path = parent / 'events.sqlite3'
    queued = 0
    with Spool(spool_path) as spool:
        sent = flush(spool, core_url, token, device_id, transport=transport)
        for repo in config.approved_repositories:
            event = collect_git(repo, config, device_id, runner=runner)
            spool.enqueue(event)
            queued += 1
        sent += flush(spool, core_url, token, device_id, transport=transport)
        return {'disabled': False, 'queued': queued, 'sent': sent, 'pending': len(spool.pending())}


def main(argv=None, *, environ=None):
    import argparse
    import json
    import sys
    parser = argparse.ArgumentParser(description='Manual opt-in JAX Git metadata node')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--spool', type=Path)
    args = parser.parse_args(argv)
    if not args.once:
        print('No monitoring mode. Explicit --once is required.', file=sys.stderr)
        return 2
    try:
        config = Config(**json.loads(args.config.read_text(encoding='utf-8'))) if args.config else Config()
        result = run_once(config, environ=environ, spool_path=args.spool)
        print(json.dumps(result))
        return 0 if not result.get('pending') else 1
    except Exception:
        # Never echo exception messages, subprocess output, credentials or config content.
        print('Node run failed; no diagnostic payload printed. Pending events retained.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

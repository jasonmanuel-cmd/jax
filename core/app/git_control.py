"""Deterministic Git launch authority, independent of model output."""
import os
from pathlib import Path
import subprocess

COMMAND_TIMEOUT = 30


def _git(path, *args):
    env = os.environ.copy()
    # Git's repository-local environment must not redirect the requested root.
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR',
                'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
                'GIT_NAMESPACE', 'GIT_PREFIX', 'GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS'):
        env.pop(key, None)
    env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never',
               GIT_SSH_COMMAND='ssh -oBatchMode=yes -oConnectTimeout=10',
               GIT_ASKPASS='echo', SSH_ASKPASS='echo')
    result = subprocess.run(
        ['git', '-C', str(path), *args], env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=COMMAND_TIMEOUT, check=True,
    ).stdout
    return result if '-z' in args else result.strip()


def inspect_repository(path, fetch=True, fast_forward=False):
    """Return JSON-safe Git evidence; only freshly verified READY may launch."""
    result = dict(state='INVALID_REPOSITORY', branch=None, head=None,
                  upstream=None, upstream_head=None, ahead=None, behind=None,
                  dirty_files=[], remote_verified=False, launch_allowed=False,
                  error='Path must be the exact root of a Git working tree')
    try:
        path = Path(path).resolve(strict=True)
        root = Path(_git(path, 'rev-parse', '--show-toplevel')).resolve()
        if root != path:
            return result
    except (subprocess.SubprocessError, OSError, ValueError, TypeError):
        return result
    try:
        branch = _git(path, 'symbolic-ref', '--short', 'HEAD')
        result['branch'] = branch
    except subprocess.CalledProcessError:
        result.update(state='DETACHED', error='Detached HEAD cannot launch',
                      head=_git(path, 'rev-parse', 'HEAD'))
        return result
    try:
        head = _git(path, 'rev-parse', '--verify', 'HEAD')
        result['head'] = head
        upstream = _git(path, 'rev-parse', '--abbrev-ref', '@{upstream}')
        remote = _git(path, 'config', '--get', f'branch.{branch}.remote')
    except subprocess.CalledProcessError:
        result.update(state='NO_UPSTREAM', error='No upstream: local-only repository')
        return result
    remote_verified = False
    error = 'Remote verification skipped'
    if fetch:
        remote_ref = _git(path, 'config', '--get', f'branch.{branch}.merge')

        def fetch_once():
            """Return (transport_error, mismatch). Only transport_error is retryable.

            A SHA mismatch is deterministic, so retrying it would just repeat the
            same verdict; a transport failure may be a transient network blip.
            """
            try:
                _git(path, 'fetch', '--no-tags', '--no-recurse-submodules', '--',
                     remote, remote_ref)
            except subprocess.TimeoutExpired:
                return f'Remote fetch timed out after {COMMAND_TIMEOUT}s', None
            except subprocess.CalledProcessError as exc:
                # Surface git's own diagnosis (auth, DNS, TLS, 404); far more
                # actionable than a single generic failure string.
                detail = (exc.stderr or exc.stdout or '').strip().splitlines()
                reason = detail[-1].strip() if detail else f'git exited {exc.returncode}'
                return f'Remote fetch failed: {reason[:200]}', None
            except (subprocess.SubprocessError, OSError) as exc:
                return f'Remote fetch error: {type(exc).__name__}', None
            try:
                fetched = _git(path, 'rev-parse', 'FETCH_HEAD')
                tracked = _git(path, 'rev-parse', '@{upstream}')
            except (subprocess.SubprocessError, OSError):
                return 'Could not resolve FETCH_HEAD after a successful fetch', None
            if fetched == tracked:
                return None, None
            return (None,
                    'Fetched remote does not match upstream tracking ref '
                    f'({fetched[:12]} != {tracked[:12]})')

        # One retry for transport-level failures only. A retry can never promote
        # a repo to verified: verification still requires a matching SHA.
        for _ in range(2):
            transport_error, mismatch = fetch_once()
            if transport_error is None:
                break
        error = transport_error or mismatch
        remote_verified = error is None
    upstream_head = _git(path, 'rev-parse', '@{upstream}')
    ahead, behind = map(int, _git(path, 'rev-list', '--left-right', '--count',
                                  f'{head}...{upstream_head}').split())
    status = _git(path, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    dirty_files = []
    entries = iter(status.split('\0'))
    for entry in entries:
        if not entry:
            continue
        dirty_files.append(entry[3:])
        if 'R' in entry[:2] or 'C' in entry[:2]:
            dirty_files.append(next(entries))
    dirty_files = sorted(set(dirty_files))
    state = ('DIRTY' if dirty_files else 'DIVERGED' if ahead and behind else
             'AHEAD' if ahead else 'BEHIND' if behind else 'READY')
    if fast_forward and state == 'BEHIND' and remote_verified:
        # Pin both endpoints; never merge an upstream name that can move.
        if (_git(path, 'rev-parse', 'HEAD') != head or
                _git(path, 'rev-parse', '@{upstream}') != upstream_head or
                _git(path, 'status', '--porcelain=v1', '-z', '--untracked-files=all')):
            state, error = 'REMOTE_UNREACHABLE', 'Repository changed during preflight'
            remote_verified = False
        else:
            try:
                _git(path, '-c', 'core.hooksPath=/dev/null', 'merge', '--ff-only',
                     '--no-edit', '--no-autostash', upstream_head)
                head = _git(path, 'rev-parse', 'HEAD')
                if (head != upstream_head or
                        _git(path, 'rev-parse', '@{upstream}') != upstream_head or
                        _git(path, 'status', '--porcelain=v1', '-z', '--untracked-files=all')):
                    raise ValueError('Fast-forward verification failed')
                ahead, behind, state = 0, 0, 'READY'
            except (subprocess.SubprocessError, OSError, ValueError):
                state, error = 'REMOTE_UNREACHABLE', 'Fast-forward failed verification'
                remote_verified = False
    if not remote_verified:
        state = 'REMOTE_UNREACHABLE'
    if state == 'READY':
        # Final consistency guard: HEAD/upstream/tree must not have moved since
        # the values that produced this verdict, or the READY is stale (TOCTOU).
        try:
            if (_git(path, 'rev-parse', 'HEAD') != head or
                    _git(path, 'rev-parse', '@{upstream}') != upstream_head or
                    _git(path, 'status', '--porcelain=v1', '-z', '--untracked-files=all')):
                raise ValueError('Repository changed during preflight')
        except (subprocess.SubprocessError, OSError, ValueError):
            state, error, remote_verified = 'REMOTE_UNREACHABLE', 'Repository changed during preflight', False
    return dict(state=state, branch=branch, head=head, upstream=upstream,
                upstream_head=upstream_head, ahead=ahead, behind=behind,
                dirty_files=dirty_files, remote_verified=remote_verified,
                launch_allowed=state == 'READY', error=error)

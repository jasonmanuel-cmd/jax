"""Git authority tests: all Git mutations use isolated local repositories."""
import importlib
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))


def inspect(*args, **kwargs):
    module_path = ROOT / 'core' / 'app' / 'git_control.py'
    assert module_path.exists(), 'Git preflight implementation is missing'
    return importlib.import_module('core.app.git_control').inspect_repository(*args, **kwargs)


def git(path, *args):
    env = os.environ.copy()
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='Test',
               GIT_AUTHOR_EMAIL='test@example.invalid', GIT_COMMITTER_NAME='Test',
               GIT_COMMITTER_EMAIL='test@example.invalid')
    for key in list(env):
        if key in {'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR'}:
            env.pop(key)
    result = subprocess.run(['git', '-C', str(path), *args], env=env,
                            capture_output=True, text=True, timeout=15, check=True)
    return result.stdout.strip()


def commit(path, text='initial'):
    (path / 'tracked.txt').write_text(text, encoding='utf-8')
    git(path, 'add', '.')
    git(path, 'commit', '-m', text)
    return git(path, 'rev-parse', 'HEAD')


@pytest.fixture
def repos(tmp_path):
    remote, local, peer = [tmp_path / name for name in ('remote.git', 'local', 'peer')]
    git(tmp_path, 'init', '--bare', '--initial-branch=main', str(remote))
    git(tmp_path, 'clone', str(remote), str(local))
    commit(local)
    git(local, 'push', '-u', 'origin', 'main')
    git(tmp_path, 'clone', str(remote), str(peer))
    return local, peer, remote


@pytest.mark.parametrize('mode', ['skipped', 'unreachable'])
def test_unverified_remote_never_allows_launch(repos, mode):
    local, _, remote = repos
    if mode == 'unreachable':
        git(local, 'remote', 'set-url', 'origin', str(remote / 'missing'))
    result = inspect(local, fetch=mode != 'skipped', fast_forward=True)
    assert result['state'] == 'REMOTE_UNREACHABLE'
    assert result['remote_verified'] is False
    assert result['launch_allowed'] is False
    assert result['error']


@pytest.mark.parametrize('mode, expected', [
    ('no_upstream', 'NO_UPSTREAM'), ('detached', 'DETACHED'),
    ('nested', 'INVALID_REPOSITORY'), ('nonrepo', 'INVALID_REPOSITORY'),
    ('missing', 'INVALID_REPOSITORY'), ('unborn', 'NO_UPSTREAM'),
])
def test_repository_boundaries_fail_closed(repos, tmp_path, mode, expected):
    local, _, _ = repos
    target = local
    if mode == 'no_upstream':
        git(local, 'branch', '--unset-upstream')
    elif mode == 'detached':
        git(local, 'checkout', '--detach')
    elif mode in {'nested', 'nonrepo', 'missing', 'unborn'}:
        target = (local if mode == 'nested' else tmp_path) / mode
        if mode != 'missing':
            target.mkdir()
        if mode == 'unborn':
            git(target, 'init', '--initial-branch=main')
    result = inspect(target, fast_forward=True)
    assert result['state'] == expected
    assert result['launch_allowed'] is False
    assert result['remote_verified'] is False
    assert result['error']
    json.dumps(result)


def test_explicit_fast_forward_rechecks_sha(repos):
    local, peer, _ = repos
    expected = commit(peer, 'remote fast forward')
    git(peer, 'push')
    result = inspect(local, fast_forward=True)
    assert result['state'] == 'READY'
    assert result['head'] == result['upstream_head'] == expected
    assert git(local, 'rev-parse', 'HEAD') == expected
    assert result['ahead'] == result['behind'] == 0
    assert result['launch_allowed'] is True
    assert (local / 'tracked.txt').read_text(encoding='utf-8') == 'remote fast forward'


def test_deleted_remote_branch_is_not_verified(repos):
    local, _, remote = repos
    git(remote, 'update-ref', '-d', 'refs/heads/main')
    result = inspect(local)
    assert result['state'] == 'REMOTE_UNREACHABLE'
    assert result['remote_verified'] is False
    assert result['launch_allowed'] is False


def test_staged_rename_reports_both_paths(repos):
    local, _, _ = repos
    git(local, 'mv', 'tracked.txt', 'renamed file.txt')
    result = inspect(local, fast_forward=True)
    assert result['state'] == 'DIRTY'
    assert set(result['dirty_files']) == {'tracked.txt', 'renamed file.txt'}


def test_inherited_git_directory_cannot_redirect_inspection(repos, monkeypatch):
    local, peer, _ = repos
    commit(peer, 'other repo')
    monkeypatch.setenv('GIT_DIR', str(peer / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(peer))
    result = inspect(local)
    assert result['state'] == 'READY'
    assert result['head'] == git(local, 'rev-parse', 'HEAD')


def test_head_change_during_fetch_cannot_launch(repos, monkeypatch):
    local, _, _ = repos
    module = importlib.import_module('core.app.git_control')
    original = module._git

    def change_after_fetch(path, *args):
        output = original(path, *args)
        if args[0] == 'fetch':
            commit(local, 'concurrent change')
        return output

    monkeypatch.setattr(module, '_git', change_after_fetch)
    result = inspect(local)
    assert result['launch_allowed'] is False
    assert result['state'] != 'READY'
    assert result['error']


def test_transport_failure_is_retried_once(repos, monkeypatch):
    """One transient fetch failure must not be mistaken for a dead remote."""
    local, _, _ = repos
    module = importlib.import_module('core.app.git_control')
    original = module._git
    calls = []

    def fail_once(path, *args):
        if args and args[0] == 'fetch':
            calls.append(args[0])
            if len(calls) == 1:
                raise OSError('connection reset')
        return original(path, *args)

    monkeypatch.setattr(module, '_git', fail_once)
    result = inspect(local)
    assert len(calls) == 2, 'expected exactly one retry'
    assert result['remote_verified'] is True
    assert result['state'] == 'READY'
    assert result['launch_allowed'] is True


def test_repeated_transport_failure_still_fails_closed(repos, monkeypatch):
    """A retry must never promote an unverifiable repo to verified."""
    local, _, _ = repos
    module = importlib.import_module('core.app.git_control')
    original = module._git

    def always_fail(path, *args):
        if args and args[0] == 'fetch':
            raise OSError('connection reset')
        return original(path, *args)

    monkeypatch.setattr(module, '_git', always_fail)
    result = inspect(local, fetch=True, fast_forward=False)
    assert result['remote_verified'] is False
    assert result['state'] == 'REMOTE_UNREACHABLE'
    assert result['launch_allowed'] is False
    assert result['error']


def test_sha_mismatch_is_not_retried(repos, monkeypatch):
    """A deterministic mismatch must not be retried as if it were flaky."""
    local, _, _ = repos
    module = importlib.import_module('core.app.git_control')
    original = module._git
    fetches = []

    def mismatch(path, *args):
        if args and args[0] == 'rev-parse' and args[1] == 'FETCH_HEAD':
            return 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n'
        if args and args[0] == 'fetch':
            fetches.append(1)
        return original(path, *args)

    monkeypatch.setattr(module, '_git', mismatch)
    result = inspect(local)
    assert len(fetches) == 1, 'SHA mismatch must not trigger a retry'
    assert result['remote_verified'] is False
    assert result['state'] == 'REMOTE_UNREACHABLE'
    assert result['launch_allowed'] is False
    # The operator must be able to tell which SHAs disagreed.
    assert 'does not match upstream' in result['error']
    assert 'deadbeef' in result['error']


def test_fetch_error_reports_git_diagnosis(repos, monkeypatch):
    """Auth/DNS/404 causes must be visible, not collapsed into one string."""
    local, _, _ = repos
    module = importlib.import_module('core.app.git_control')
    original = module._git

    def auth_error(path, *args):
        if args and args[0] == 'fetch':
            raise subprocess.CalledProcessError(
                128, 'git fetch', 'out', 'fatal: could not read Username')
        return original(path, *args)

    monkeypatch.setattr(module, '_git', auth_error)
    result = inspect(local, fetch=True, fast_forward=False)
    assert result['remote_verified'] is False
    assert result['launch_allowed'] is False
    assert 'could not read Username' in result['error']
    assert 'Remote fetch failed' in result['error']


def test_timeout_reports_the_budget(repos, monkeypatch):
    """A timeout must state the budget so the operator can judge it."""
    local, _, _ = repos
    module = importlib.import_module('core.app.git_control')
    original = module._git

    def timeout(path, *args):
        if args and args[0] == 'fetch':
            raise subprocess.TimeoutExpired('git fetch', module.COMMAND_TIMEOUT)
        return original(path, *args)

    monkeypatch.setattr(module, '_git', timeout)
    result = inspect(local, fetch=True, fast_forward=False)
    assert result['remote_verified'] is False
    assert result['launch_allowed'] is False
    assert 'timed out' in result['error']
    assert str(module.COMMAND_TIMEOUT) in result['error']


def test_verified_ready_is_json_safe(repos):
    local, _, _ = repos
    result = inspect(local)
    assert result['state'] == 'READY'
    assert result['branch'] == 'main'
    assert result['head'] == result['upstream_head'] == git(local, 'rev-parse', 'HEAD')
    assert result['upstream'] == 'origin/main'
    assert result['ahead'] == result['behind'] == 0
    assert result['dirty_files'] == []
    assert result['remote_verified'] is True
    assert result['launch_allowed'] is True
    json.dumps(result)


@pytest.mark.parametrize('state', ['BEHIND', 'AHEAD', 'DIVERGED', 'DIRTY'])
def test_nonready_states_block_launch(repos, state):
    local, peer, _ = repos
    if state in {'BEHIND', 'DIVERGED', 'DIRTY'}:
        commit(peer, 'remote change')
        git(peer, 'push')
    if state in {'AHEAD', 'DIVERGED'}:
        commit(local, 'local change')
    if state == 'DIRTY':
        (local / 'tracked.txt').write_text('unstaged', encoding='utf-8')
        (local / 'untracked space.txt').write_text('new', encoding='utf-8')
    before = git(local, 'rev-parse', 'HEAD')
    result = inspect(local, fast_forward=state == 'DIRTY')
    assert result['state'] == state
    assert result['launch_allowed'] is False
    assert result['remote_verified'] is True
    assert git(local, 'rev-parse', 'HEAD') == before
    assert result['ahead'] == int(state in {'AHEAD', 'DIVERGED'})
    assert result['behind'] == int(state in {'BEHIND', 'DIVERGED', 'DIRTY'})
    if state == 'DIRTY':
        assert set(result['dirty_files']) == {'tracked.txt', 'untracked space.txt'}

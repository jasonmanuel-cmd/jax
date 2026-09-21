"""Node safety tests. All HTTP transports and git runners are TEST ONLY."""
from pathlib import Path
import importlib
import pytest


def test_allowlist_exact_resolved_repo_only(tmp_path):
    from node_windows.node import Config, approved_repo
    repo = tmp_path / 'approved'
    repo.mkdir()
    child = repo / 'child'
    child.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    config = Config(git_enabled=True, approved_repositories=(str(repo),))
    assert approved_repo(repo, config) == repo.resolve()
    for path in (child, repo / '..' / 'outside', tmp_path / 'approved-lookalike'):
        with pytest.raises(PermissionError):
            approved_repo(path, config)
    with pytest.raises(ValueError):
        Config(active_window_enabled=True)
    with pytest.raises(ValueError):
        Config(git_enabled='false')


@pytest.mark.parametrize('payload', [
    {'metadata': {'nested': [{'app': 'Bitwarden.exe'}]}},
    {'metadata': ['1Password', 'KeePassXC']},
    {'metadata': {'password': 'innocent'}},
    {'metadata': {'nested': 'Bearer abcdefghijklmnopqrstuvwxyz'}},
    {'summary': '-----BEGIN PRIVATE KEY-----'},
    {'metadata': {'x': 'sk-' + 'a' * 32}},
    {'metadata': {'x': 'ghp_' + 'a' * 36}},
    {'metadata': {'x': 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature'}},
    {'metadata': {'seed phrase': 'words'}},
])
def test_recursive_privacy_rejects(payload):
    from node_windows.node import allowed_event
    assert allowed_event(payload) is False


def test_privacy_allows_git_hash_and_normal_metadata():
    from node_windows.node import allowed_event
    assert allowed_event({'app': 'git', 'metadata': {'branch': 'main', 'commit_hash': 'a' * 40, 'dirty_count': 2}})


def test_git_metadata_fixed_commands_test_only_runner(tmp_path):
    from node_windows.node import Config, collect_git
    from uuid import UUID
    from datetime import datetime
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.git').mkdir()
    calls = []
    outputs = [str(repo), 'main', 'a' * 40, ' M secret-name.txt\0?? another.txt\0']
    def runner(args, **kwargs):  # TEST ONLY: never executes git.
        calls.append((args, kwargs))
        return outputs.pop(0)
    config = Config(git_enabled=True, approved_repositories=(str(repo),))
    evt = collect_git(repo, config, '11111111-1111-4111-8111-111111111111', runner=runner)
    assert UUID(evt['event_id'])
    assert datetime.fromisoformat(evt['occurred_at']).utcoffset().total_seconds() == 0
    assert evt['type'] == 'git_context'
    assert evt['metadata'] == {'branch': 'main', 'commit_hash': 'a' * 40, 'dirty_count': 2}
    assert 'secret-name' not in str(evt)
    assert all(k['timeout'] == 5 and k['shell'] is False for _, k in calls)
    assert all('log' not in a and 'diff' not in a for a, _ in calls)
    assert calls[-1][0][-4:] == ['status', '--porcelain=v1', '-z', '--untracked-files=normal']
    assert collect_git(repo, Config(), evt['device_id'], runner=runner) is None


def fixture_event():
    return {'event_id': '22222222-2222-4222-8222-222222222222',
            'device_id': '11111111-1111-4111-8111-111111111111', 'type': 'git_context',
            'app': 'git', 'summary': 'Approved repository Git metadata',
            'metadata': {'branch': 'main', 'commit_hash': 'a' * 40, 'dirty_count': 0},
            'occurred_at': '2026-09-20T00:00:00+00:00'}


def test_bounded_spool_retains_stable_ids_after_reopen(tmp_path):
    from node_windows.node import Spool
    event = fixture_event()
    with Spool(tmp_path / 'queue.db', max_events=1) as spool:
        spool.enqueue(event)
        spool.enqueue(event)
        assert spool.pending() == [event]
        other = dict(event, event_id='33333333-3333-4333-8333-333333333333')
        with pytest.raises(OverflowError):
            spool.enqueue(other)
        with pytest.raises(PermissionError):
            spool.enqueue(dict(event, summary='Bitwarden'))
    with Spool(tmp_path / 'queue.db', max_events=1) as spool:
        assert spool.pending() == [event]
        spool.ack(event['event_id'])
        assert spool.pending() == []
        with pytest.raises(ValueError):
            spool.enqueue(dict(event, summary='x' * 17000))


@pytest.mark.parametrize('url', ['http://localhost.evil.test', 'http://127.0.0.1.evil.test', 'http://127.1', 'http://2130706433', 'http://[::ffff:127.0.0.1]', 'ftp://localhost', 'https://user:pass@example.test', 'https://example.test/?token=x'])
def test_transport_rejects_unsafe_urls(url):
    from node_windows.node import events_url
    with pytest.raises(ValueError):
        events_url(url)


@pytest.mark.parametrize('url', ['http://localhost:8788', 'http://127.0.0.1:8788', 'http://[::1]:8788', 'https://core.example.test'])
def test_transport_allows_tls_or_exact_loopback(url):
    from node_windows.node import events_url
    assert events_url(url) == url + '/v1/events'


def test_test_only_mock_transport_retry_stable_id(tmp_path):
    import httpx
    import json
    from node_windows.node import Spool, flush
    seen = []
    def handler(request):  # TEST ONLY: no socket/network traffic.
        seen.append(json.loads(request.content))
        assert request.headers['authorization'] == 'Bearer test-only-token'
        assert str(request.url) == 'http://127.0.0.1:8788/v1/events'
        return httpx.Response(503 if len(seen) == 1 else 200, json={'accepted': True})
    with Spool(tmp_path / 'queue.db') as spool:
        spool.enqueue(fixture_event())
        transport = httpx.MockTransport(handler)
        assert flush(spool, 'http://127.0.0.1:8788', 'test-only-token', fixture_event()['device_id'], transport=transport) == 0
        assert spool.pending() == [fixture_event()]
        assert flush(spool, 'http://127.0.0.1:8788', 'test-only-token', fixture_event()['device_id'], transport=transport) == 1
        assert spool.pending() == []
        assert seen == [fixture_event(), fixture_event()]


def test_manual_once_requires_flag_default_off_and_sanitizes_errors(tmp_path, capsys):
    from node_windows.node import main
    assert main([]) == 2
    assert main(['--once'], environ={}) == 0
    assert 'disabled' in capsys.readouterr().out
    cfg = tmp_path / 'config.json'
    cfg.write_text('{"git_enabled": true}')
    assert main(['--once', '--config', str(cfg)], environ={'JAX_NODE_TOKEN': 'never-print-this'}) == 1
    captured = capsys.readouterr()
    assert 'never-print-this' not in captured.out + captured.err


def test_enabled_once_test_only_end_to_end(tmp_path):
    import httpx
    from node_windows.node import Config, run_once, Spool
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.git').mkdir()
    outputs = [str(repo), 'main', 'a' * 40, '']
    def runner(*args, **kwargs):  # TEST ONLY git fixture
        return outputs.pop(0)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'accepted': True}))
    config = Config(git_enabled=True, approved_repositories=(str(repo),))
    result = run_once(config, environ={'JAX_DEVICE_ID': fixture_event()['device_id'],
                      'JAX_NODE_TOKEN': 'test-only-token', 'JAX_CORE_URL': 'http://127.0.0.1:8788'},
                      spool_path=tmp_path / 'queue.db', runner=runner, transport=transport)
    assert result == {'disabled': False, 'queued': 1, 'sent': 1, 'pending': 0}
    with Spool(tmp_path / 'queue.db') as spool:
        assert spool.pending() == []


def test_default_off_without_io():
    node = importlib.import_module('node_windows.node')
    config = node.Config()
    assert config.approved_repositories == ()
    assert config.git_enabled is False
    assert config.active_window_enabled is False
    assert node.run_once(config) == {'disabled': True, 'queued': 0, 'sent': 0}

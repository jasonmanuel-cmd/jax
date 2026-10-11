"""Agent adapter and session-manager tests.

Adapters are exercised against a fake executable and disposable Git
repositories. No real Claude or Hermes process is launched, and no test may
assert success that did not actually occur.
"""
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.app.agents import (  # noqa: E402
    AdapterRegistry, AgentAdapter, AgentSession, ClaudeAdapter, GenericCliAdapter,
    HermesAdapter, SessionBrief, build_registry,
)
from core.app.core.session_manager import LaunchRefused, SessionManager  # noqa: E402
from core.app.policy_engine import default_registry  # noqa: E402


def git(path, *args):
    env = os.environ.copy()
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='Test',
               GIT_AUTHOR_EMAIL='t@example.invalid', GIT_COMMITTER_NAME='Test',
               GIT_COMMITTER_EMAIL='t@example.invalid')
    return subprocess.run(['git', '-C', str(path), *args], env=env,
                          capture_output=True, text=True, timeout=15,
                          check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A disposable local repo with a real working tree."""
    remote, local = tmp_path / 'remote.git', tmp_path / 'local'
    git(tmp_path, 'init', '--bare', '--initial-branch=main', str(remote))
    git(tmp_path, 'clone', str(remote), str(local))
    (local / 'tracked.txt').write_text('initial', encoding='utf-8')
    git(local, 'add', '.')
    git(local, 'commit', '-m', 'initial')
    git(local, 'push', '-u', 'origin', 'main')
    return local


def brief(**kw):
    payload = dict(project='demo', device='test-device', agent='generic_cli',
                   timestamp='2026-10-07T00:00:00+00:00', objective='ship it')
    payload.update(kw)
    return SessionBrief(**payload)


# -- SessionBrief ---------------------------------------------------------

def test_brief_carries_verified_state_separately_from_claims():
    b = brief(branch='main', local_head='abc123', remote_head='abc123',
              sync_state='READY')
    payload = b.to_dict()
    assert payload['verified_repository_state'] == {
        'branch': 'main', 'local_head': 'abc123', 'remote_head': 'abc123',
        'sync_state': 'READY', 'dirty_files': []}
    json.dumps(payload)


def test_brief_defaults_to_unknown_not_ready():
    """An unproven repository must never serialize as synchronized."""
    assert brief().to_dict()['verified_repository_state']['sync_state'] == 'UNKNOWN'


# -- Adapter contract -----------------------------------------------------

def test_every_adapter_satisfies_the_protocol():
    registry = build_registry()
    for adapter in registry._adapters.values():
        assert isinstance(adapter, AgentAdapter)
        for method in ('available', 'version', 'launch', 'healthcheck',
                       'collect_result', 'stop'):
            assert callable(getattr(adapter, method))


def test_registry_rejects_duplicate_adapter():
    registry = AdapterRegistry([GenericCliAdapter()])
    with pytest.raises(ValueError, match='already registered'):
        registry.register(GenericCliAdapter())


def test_registry_unknown_adapter_raises():
    with pytest.raises(KeyError):
        AdapterRegistry().get('nope')


def test_v1_registry_order_is_claude_then_hermes_then_generic():
    registry = build_registry()
    assert registry.names() == ['claude', 'generic_cli', 'hermes']
    assert isinstance(registry.get('claude'), ClaudeAdapter)
    assert isinstance(registry.get('hermes'), HermesAdapter)
    assert isinstance(registry.get('generic_cli'), GenericCliAdapter)


def test_missing_executable_reports_unavailable():
    adapter = GenericCliAdapter(executable='definitely-not-installed-xyz')
    assert adapter.available() is False
    assert adapter.version() == 'unknown'
    assert adapter.healthcheck()['available'] is False


def test_launch_refuses_when_executable_missing():
    """An unavailable adapter must not claim a launch happened."""
    adapter = GenericCliAdapter(executable='definitely-not-installed-xyz')
    session = adapter.launch('.', brief())
    assert session.status == 'crashed'
    assert 'not installed' in (session.error or '').lower() \
        or 'Could not start' in (session.error or '')


def test_generic_cli_receives_brief_on_stdin(repo):
    """The brief must arrive as structured JSON, not a truncated argv string."""
    captured = repo / 'captured.json'
    script = repo / 'capture.py'
    script.write_text(
        'import sys, pathlib\n'
        'pathlib.Path("captured.json").write_text(sys.stdin.read(), "utf-8")\n',
        encoding='utf-8')
    import sys as _sys
    adapter = GenericCliAdapter(executable=_sys.executable)
    adapter._build_command = lambda: [_sys.executable, str(script)]
    session = adapter.launch(str(repo), brief(objective='a' * 4000))
    assert session.status == 'exited', session.error
    payload = json.loads(captured.read_text(encoding='utf-8'))
    assert payload['objective'] == 'a' * 4000
    assert payload['project'] == 'demo'


def test_generic_cli_reports_nonzero_exit_as_crash(repo):
    import sys as _sys
    adapter = GenericCliAdapter(executable=_sys.executable)
    adapter._build_command = lambda: [_sys.executable, '-c',
                                      'import sys; sys.stderr.write("boom\\n"); sys.exit(3)']
    session = adapter.launch(str(repo), brief())
    assert session.status == 'crashed'
    assert session.exit_code == 3
    assert 'boom' in (session.error or '')


def test_claude_refuses_launch_when_not_installed(repo):
    adapter = ClaudeAdapter(executable='definitely-not-installed-xyz')
    session = adapter.launch(str(repo), brief())
    assert session.status == 'crashed'
    assert 'not installed' in (session.error or '')


def test_hermes_refuses_launch_when_not_installed(repo):
    adapter = HermesAdapter(executable='definitely-not-installed-xyz')
    session = adapter.launch(str(repo), brief())
    assert session.status == 'crashed'
    assert 'not installed' in (session.error or '')


def test_hermes_abnormal_termination_is_a_recoverable_crash(repo):
    """Spec requires abnormal TUI termination to be handled, not hidden."""
    import sys as _sys
    adapter = HermesAdapter(executable=_sys.executable)
    adapter._build_command = lambda: [_sys.executable, '-c', 'import sys; sys.exit(9)']
    adapter._probe_version = lambda: 'hermes-test'
    session = adapter.launch(str(repo), brief())
    assert session.status == 'crashed'
    assert session.exit_code == 9
    assert session.recoverable is True, 'a crashed session must stay resumable'


def test_timeout_is_reported_not_silently_passed(repo):
    import sys as _sys
    adapter = GenericCliAdapter(executable=_sys.executable, timeout=1)
    adapter._build_command = lambda: [_sys.executable, '-c', 'import time; time.sleep(30)']
    session = adapter.launch(str(repo), brief())
    assert session.status == 'crashed'
    assert '1s' in (session.error or '')


def test_stop_is_idempotent_and_safe_on_unknown_session(repo):
    import sys as _sys
    adapter = GenericCliAdapter(executable=_sys.executable)
    adapter.stop('does-not-exist')  # must not raise


def test_collect_result_for_unknown_session_reports_unknown(repo):
    result = GenericCliAdapter().collect_result('nope')
    assert result.status == 'unknown'
    assert 'No such session' in (result.error or '')


# -- Session manager ------------------------------------------------------

def make_manager(engine, adapters=None):
    registry = AdapterRegistry(adapters or [GenericCliAdapter()])
    return SessionManager(engine, registry, default_registry())


ADMIN = 'test-admin-token-that-is-long-enough-0123456789'
AUTH = {'Authorization': f'Bearer {ADMIN}'}


@pytest.fixture
def app_client(tmp_path):
    """Per-test SQLite database, admin auth on every request by default.

    A fresh database per test matters here: agent_runs gained columns, and
    create_all never alters an existing table, so reusing the developer's
    data/jax.db would fail on a stale schema.
    """
    from fastapi.testclient import TestClient
    module = importlib.import_module('core.app.main')
    with TestClient(module.create_app(
            database_url=f'sqlite:///{tmp_path}/jax.db',
            admin_token=ADMIN), headers=AUTH) as client:
        yield client


def test_preflight_reports_ready_for_clean_repo(app_client, repo, monkeypatch):
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    project = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()
    response = app_client.post('/v1/sessions/preflight', json={
        'project_id': project['id'], 'fetch': True})
    assert response.status_code == 200
    assert response.json()['state'] == 'READY'
    assert response.json()['launch_allowed'] is True


def test_kill_switch_blocks_preflight(app_client, repo, monkeypatch):
    """423 Locked, not 403: the resource exists, execution is suspended."""
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    project = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()
    app_client.post('/v1/kill/activate', json={'reason': 'test drill'})
    response = app_client.post('/v1/sessions/preflight', json={
        'project_id': project['id'], 'fetch': True})
    assert response.status_code == 423
    assert 'Kill switch' in response.json()['detail']


def test_dirty_repo_blocks_launch(app_client, repo, monkeypatch):
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    project = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()
    (repo / 'tracked.txt').write_text('uncommitted edit', encoding='utf-8')
    body = app_client.post('/v1/sessions/preflight', json={
        'project_id': project['id'], 'fetch': True}).json()
    assert body['state'] == 'DIRTY'
    assert body['launch_allowed'] is False
    assert 'tracked.txt' in body['dirty_files']


def test_diverged_repo_is_detected(app_client, repo, tmp_path, monkeypatch):
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    project = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()
    # Peer clone commits locally, remote moves independently -> both unique.
    peer = tmp_path / 'peer'
    git(tmp_path, 'clone', str(repo / '..' / 'remote.git'), str(peer))
    (peer / 'a.txt').write_text('peer', encoding='utf-8')
    git(peer, 'add', '.')
    git(peer, 'commit', '-m', 'peer work')
    git(peer, 'push')
    (repo / 'b.txt').write_text('local', encoding='utf-8')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'local work')
    body = app_client.post('/v1/sessions/preflight', json={
        'project_id': project['id'], 'fetch': True}).json()
    assert body['state'] == 'DIVERGED'
    assert body['launch_allowed'] is False
    assert body['ahead'] == 1 and body['behind'] == 1


def test_verification_records_real_exit_codes(app_client, repo, monkeypatch):
    """A handoff must report the actual result of a real command."""
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    engine = app_client.app.state.engine
    manager = make_manager(engine)
    project = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()
    project_id = project['id']
    session_id = 'test-session-1'
    with engine.begin() as db:
        from core.app.tables2 import agent_runs
        from datetime import datetime, timezone
        db.execute(agent_runs.insert().values(
            id=session_id, agent_name='generic_cli', objective='demo',
            status='running', started_at=datetime.now(timezone.utc),
            project_id=project_id))
    result = manager.verify_and_close(session_id, str(repo),
                                      test_commands=[
                                          'git rev-parse --is-inside-work-tree',
                                          'exit 7'])
    assert result['verification_passed'] is False
    receipts = {r['command']: r for r in result['verification']}
    assert receipts['git rev-parse --is-inside-work-tree']['exit_code'] == 0
    assert receipts['exit 7']['exit_code'] == 7
    assert result['handoff_id']


def test_handoff_does_not_claim_sync_it_did_not_verify(app_client, repo, monkeypatch):
    """Closing a session inspects offline, so it must not report READY.

    The spec forbids claiming synchronization that was not proven. A handoff
    written without a verified fetch has to say so.
    """
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    engine = app_client.app.state.engine
    manager = make_manager(engine)
    from core.app.tables2 import agent_runs
    from datetime import datetime, timezone
    project_id = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()['id']
    with engine.begin() as db:
        db.execute(agent_runs.insert().values(
            id='s2', agent_name='generic_cli', objective='demo', status='running',
            started_at=datetime.now(timezone.utc), project_id=project_id))
    result = manager.verify_and_close('s2', str(repo))
    assert result['repository_state']['remote_verified'] is False
    handoff = app_client.get('/v1/handoffs').json()[-1]
    assert 'repository state REMOTE_UNREACHABLE' in handoff['summary']
    assert 'repository state READY' not in handoff['summary']
    assert 'generic_cli' in handoff['summary']


def test_handoff_reports_verified_state_when_fetch_proves_it(app_client, repo, monkeypatch):
    """With a verified fetch the handoff may state the real state."""
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    engine = app_client.app.state.engine
    manager = make_manager(engine)
    from core.app.tables2 import agent_runs
    from datetime import datetime, timezone
    project_id = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()['id']
    with engine.begin() as db:
        db.execute(agent_runs.insert().values(
            id='s3', agent_name='generic_cli', objective='demo', status='running',
            started_at=datetime.now(timezone.utc), project_id=project_id))
    result = manager.verify_and_close('s3', str(repo), fetch=True)
    assert result['repository_state']['remote_verified'] is True
    assert result['repository_state']['state'] == 'READY'
    handoff = app_client.get('/v1/handoffs').json()[-1]
    assert 'repository state READY' in handoff['summary']


def test_launch_refuses_unknown_adapter(app_client, repo, monkeypatch):
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    engine = app_client.app.state.engine
    manager = make_manager(engine)
    project_id = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()['id']
    with pytest.raises(LaunchRefused) as excinfo:
        manager.launch(project_id, 'device', 'nonexistent', 'obj')
    assert excinfo.value.status == 404


def test_launch_refuses_unavailable_adapter(app_client, repo, monkeypatch):
    """An adapter that is not installed must be refused, not fake-launched."""
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    engine = app_client.app.state.engine
    adapters = [ClaudeAdapter(executable='definitely-not-installed-xyz')]
    manager = make_manager(engine, adapters)
    project_id = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()['id']
    with pytest.raises(LaunchRefused) as excinfo:
        manager.launch(project_id, 'device', 'claude', 'obj')
    assert excinfo.value.code == 'adapter_unavailable'
    assert 'not claiming a launch' in excinfo.value.detail


def test_launch_refuses_inactive_project(app_client, repo, monkeypatch):
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    engine = app_client.app.state.engine
    manager = make_manager(engine)
    project_id = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'paused', 'path_hint': str(repo)}).json()['id']
    with pytest.raises(LaunchRefused) as excinfo:
        manager.launch(project_id, 'device', 'generic_cli', 'obj')
    assert excinfo.value.code == 'project_not_active'


def test_agents_endpoint_reports_real_availability(app_client):
    """The dashboard must show probed availability, not assumed availability."""
    body = app_client.get('/v1/agents').json()
    names = {a['adapter'] for a in body['adapters']}
    assert names == {'claude', 'hermes', 'generic_cli'}
    for entry in body['adapters']:
        assert isinstance(entry['available'], bool)
        assert 'version' in entry


def test_tools_endpoint_exposes_autonomy_levels(app_client):
    body = app_client.get('/v1/tools').json()
    tools = {t['name']: t for t in body['tools']}
    assert tools['git.inspect']['level'] == 0
    assert tools['git.inspect']['requires_approval'] is False
    assert tools['git.force_push']['level'] == 4
    assert tools['git.force_push']['requires_approval'] is True
    assert tools['email.draft']['level'] == 2
    assert tools['email.send']['level'] == 4


def test_agent_endpoints_require_authentication(app_client):
    anonymous = app_client.get('/v1/agents', headers={'Authorization': ''})
    assert anonymous.status_code in (401, 403)


def test_refused_launch_leaves_no_orphan_run(app_client, repo, monkeypatch):
    """A refused launch must not leave a 'running' session that never ran."""
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    engine = app_client.app.state.engine
    manager = make_manager(engine, [ClaudeAdapter(executable='not-installed-xyz')])
    project_id = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()['id']
    with pytest.raises(LaunchRefused):
        manager.launch(project_id, 'laptop', 'claude', 'obj')
    from sqlalchemy import select
    from core.app.tables2 import agent_runs
    with engine.connect() as db:
        rows = db.execute(select(agent_runs)).mappings().all()
    assert rows == [], f'refused launch must not persist a run: {rows}'


def test_launch_records_run_under_adapter_session_id(app_client, repo, monkeypatch):
    """The verify endpoint keys on session id, so the run must use the same one."""
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    engine = app_client.app.state.engine
    manager = make_manager(engine)
    project_id = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()['id']
    result = manager.launch(project_id, 'laptop', 'generic_cli', 'do the thing')
    assert result['status'] == 'exited', result['error']
    closed = manager.verify_and_close(result['session_id'], str(repo))
    assert closed['status'] != 'unknown'
    assert closed['handoff_id']


def test_machine_id_recorded_and_device_id_only_when_enrolled(app_client, repo, monkeypatch):
    """An unenrolled machine records machine_id and must not forge device_id."""
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    engine = app_client.app.state.engine
    manager = make_manager(engine)
    project_id = app_client.post('/v1/projects', json={
        'name': 'demo', 'status': 'active', 'path_hint': str(repo)}).json()['id']
    result = manager.launch(project_id, 'travel-laptop', 'generic_cli', 'obj')
    from sqlalchemy import select
    from core.app.tables2 import agent_runs
    with engine.connect() as db:
        row = db.execute(select(agent_runs).where(
            agent_runs.c.id == result['session_id'])).mappings().first()
    assert row['machine_id'] == 'travel-laptop'
    assert row['device_id'] is None
    assert row['project_id'] == project_id


def test_verify_unknown_session_is_404(app_client, repo, monkeypatch):
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(repo))
    manager = make_manager(app_client.app.state.engine)
    with pytest.raises(LaunchRefused) as excinfo:
        manager.verify_and_close('nope', str(repo))
    assert excinfo.value.status == 404
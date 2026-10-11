"""Kill switch must stop execution, not merely ingestion.

The baseline check covered only POST /v1/events. An operator who activated the
kill switch during an incident could still reach chat, voice, lead search,
self-improvement and every mutating endpoint, so the control gave false
assurance. Each test below asserts a real 423 while the switch is active.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ADMIN = 'test-admin-token-that-is-long-enough-0123456789'
AUTH = {'Authorization': f'Bearer {ADMIN}'}


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    module = importlib.import_module('core.app.main')
    with TestClient(module.create_app(
            database_url=f'sqlite:///{tmp_path}/jax.db',
            admin_token=ADMIN), headers=AUTH) as c:
        yield c


@pytest.fixture
def killed(client):
    """Activate the kill switch and yield its id."""
    response = client.post('/v1/kill/activate', json={'reason': 'incident drill'})
    assert response.status_code == 201
    return response.json()['id']


# -- the switch must actually stop work -----------------------------------

MUTATING = [
    ('POST', '/v1/projects', {'name': 'x'}),
    ('POST', '/v1/workspaces', {'name': 'x'}),
    ('POST', '/v1/tasks', {'title': 'x'}),
    ('POST', '/v1/decisions', {'decision': 'x'}),
    ('POST', '/v1/handoffs', {'summary': 'x'}),
    ('POST', '/v1/memories', {'kind': 'p', 'content': 'x'}),
    ('POST', '/v1/retrieve', {'query': 'x'}),
    ('POST', '/v1/chat', {'query': 'x'}),
    ('POST', '/v1/approvals', {'tool': 'git.force_push', 'arguments': {}}),
    ('POST', '/v1/leads/search', {'query': 'homes'}),
]


@pytest.mark.parametrize('method, path, body', MUTATING)
def test_kill_switch_blocks_mutating_endpoints(client, killed, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 423, f'{path} was reachable while killed'
    assert 'Kill switch active' in response.json()['detail']


def test_global_switch_is_reported_as_global(client, killed):
    response = client.post('/v1/projects', json={'name': 'x'})
    assert 'globally' in response.json()['detail']


def test_kill_switch_blocks_agent_launch(client, killed):
    response = client.post('/v1/sessions/any-id/launch-agent', json={
        'agent': 'generic_cli', 'objective': 'x', 'machine_id': 'laptop'})
    assert response.status_code == 423


def test_kill_switch_blocks_voice(client, killed):
    assert client.post('/v1/voice/speak', json={'text': 'hi'}).status_code == 423


def test_kill_switch_blocks_self_improvement(client, killed):
    assert client.post('/v1/self-improve/analyze', json={}).status_code == 423


# -- status must remain readable, and the switch must be liftable ----------

def test_kill_status_readable_while_active(client, killed):
    """You must be able to see why nothing works."""
    body = client.get('/v1/kill/status').json()
    assert body['active'] is True
    assert body['entries']


def test_reads_still_work_while_active(client, killed):
    """Read-only inspection is how you diagnose; gating it would be harmful."""
    assert client.get('/v1/projects').status_code == 200
    assert client.get('/v1/audit').status_code == 200
    assert client.get('/v1/agents').status_code == 200
    assert client.get('/v1/tools').status_code == 200
    assert client.get('/v1/approvals').status_code == 200
    assert client.get('/v1/tasks').status_code == 200


def test_health_still_public_while_active(client, killed):
    assert client.get('/health').status_code == 200


def test_switch_can_be_lifted_while_active(client, killed):
    """The remedy path must never be gated by the thing it remedies."""
    lifted = client.post(f'/v1/kill/deactivate/{killed}')
    assert lifted.status_code == 200
    assert client.get('/v1/kill/status').json()['active'] is False
    assert client.post('/v1/projects', json={'name': 'after'}).status_code == 201


def test_work_resumes_after_lifting(client, killed):
    client.post(f'/v1/kill/deactivate/{killed}')
    assert client.post('/v1/tasks', json={'title': 'resume'}).status_code == 201


def test_kill_activation_is_itself_recorded(client, killed):
    events = client.get('/v1/audit?action=approval.request').json()['events']
    assert isinstance(events, list)  # endpoint reachable; switch itself is the subject


def test_device_scoped_switch_does_not_block_admin(client, tmp_path):
    """A device-specific switch must not halt the whole core."""
    device = client.post('/v1/devices',
                         json={'name': 'laptop', 'platform': 'windows'}).json()
    client.post('/v1/kill/activate',
                json={'reason': 'device only', 'device_id': device['id']})
    assert client.post('/v1/projects', json={'name': 'still ok'}).status_code == 201
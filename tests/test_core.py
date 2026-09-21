import importlib.util
import pytest
from fastapi.testclient import TestClient

ADMIN = 'test-admin-token-with-at-least-32-characters'
AUTH = {'Authorization': f'Bearer {ADMIN}'}

@pytest.fixture
def client(tmp_path):
    with TestClient(factory()(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)) as c:
        yield c

def register(client):
    r = client.post('/v1/devices', headers=AUTH, json={'name': 'Laptop', 'platform': 'windows'})
    assert r.status_code == 201, r.text
    return r.json()

def test_device_creation_auth_hashing_and_revocation(client):
    from sqlalchemy import text
    assert client.post('/v1/devices', json={'name': 'x', 'platform': 'windows'}).status_code == 401
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    assert client.get('/v1/devices', headers=node).status_code == 403
    assert client.post('/v1/devices', headers=node, json={'name': 'x', 'platform': 'windows'}).status_code == 403
    assert client.post('/v1/devices', headers=AUTH, json={'name': 'x', 'platform': 'windows', 'permissions': ['admin']}).status_code == 422
    with client.app.state.engine.connect() as db:
        row = db.execute(text('SELECT token_hash FROM devices')).scalar_one()
        assert row != d['token'] and len(row) == 64
    assert 'token' not in client.get('/v1/devices', headers=AUTH).text
    assert client.post(f'/v1/devices/{d["id"]}/revoke', headers=AUTH).json()['revoked'] is True
    assert client.get('/v1/devices', headers=node).status_code == 401

def event_body(device):
    from uuid import uuid4
    return {'event_id': str(uuid4()), 'device_id': device['id'], 'type': 'git_context', 'summary': 'Approved repository status', 'app': 'git', 'metadata': {'branch': 'main', 'changed_files': 2}, 'occurred_at': '2026-09-20T12:00:00Z'}

def test_device_bound_idempotent_persistent_events(client, tmp_path):
    d = register(client)
    other = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    payload = event_body(d)
    assert client.post('/v1/events', json=payload).status_code == 401
    assert client.post('/v1/events', headers=AUTH, json=payload).status_code == 403
    assert client.post('/v1/events', headers=node, json={**payload, 'device_id': other['id']}).status_code == 403
    first = client.post('/v1/events', headers=node, json=payload)
    assert first.status_code == 200, first.text
    assert first.json() == {'id': payload['event_id'], 'accepted': True}
    assert client.post('/v1/events', headers=node, json=payload).json() == first.json()
    assert client.post('/v1/events', headers=node, json={**payload, 'summary': 'different'}).status_code == 409
    assert client.get('/v1/events', headers=node).status_code == 403
    with TestClient(factory()(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)) as second:
        assert len(second.get('/v1/events', headers=AUTH).json()) == 1
        assert second.post('/v1/events', headers=node, json=payload).json() == first.json()
    client.post(f'/v1/devices/{d["id"]}/revoke', headers=AUTH)
    assert client.post('/v1/events', headers=node, json=payload).status_code == 401

@pytest.mark.parametrize('change', [
    {'metadata': {'nested': {'password': 'do-not-store'}}},
    {'metadata': {'raw_diff': 'source code'}},
    {'metadata': {'branch': 'api_key=secret'}},
    {'summary': 'seed phrase private key'},
    {'app': 'Bitwarden'},
    {'summary': 'x' * 1001},
    {'occurred_at': '2026-09-20T12:00:00'},
    {'occurred_at': '2026-09-20T12:00:00+02:00'},
    {'permission_level': 4},
    {'metadata': {'dirty_count': -1}},
])
def test_privacy_validation_does_not_echo_or_store(client, change):
    d = register(client)
    payload = {**event_body(d), **change}
    response = client.post('/v1/events', headers={'Authorization': f'Bearer {d["token"]}'}, json=payload)
    assert response.status_code == 422, response.text
    assert 'do-not-store' not in response.text
    assert 'seed phrase' not in response.text
    assert client.get('/v1/events', headers=AUTH).json() == []

def factory():
    assert importlib.util.find_spec('core') is not None, 'core package must exist'
    from core.app.main import create_app
    return create_app

def test_bootstrap_health_and_private_schema(tmp_path, monkeypatch):
    monkeypatch.delenv('JAX_ADMIN_TOKEN', raising=False)
    create_app = factory()
    with pytest.raises(ValueError, match='JAX_ADMIN_TOKEN'):
        create_app(database_url=f'sqlite:///{tmp_path}/missing.db')
    app = create_app(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)
    with TestClient(app) as client:
        assert client.get('/health').json() == {'status': 'ok', 'service': 'jax-core'}
        assert client.get('/docs').status_code == 404
        assert client.get('/openapi.json').status_code == 404

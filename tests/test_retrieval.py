"""Phase-3 tests: retrieval engine, chat endpoint, provider abstraction."""
import importlib.util
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

ADMIN = 'test-admin-token-with-at-least-32-characters'
AUTH = {'Authorization': f'Bearer {ADMIN}'}


def factory():
    assert importlib.util.find_spec('core') is not None
    from core.app.main import create_app
    return create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(factory()(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)) as c:
        yield c


def register(client):
    r = client.post('/v1/devices', headers=AUTH, json={'name': 'Laptop', 'platform': 'windows'})
    assert r.status_code == 201
    return r.json()


# ---- Retrieval ----

def test_retrieve_returns_structured_response(client):
    # Seed some data
    client.post('/v1/memories', headers=AUTH, json={
        'kind': 'preference', 'content': 'User prefers full-file code replacements'})
    r = client.post('/v1/retrieve', headers=AUTH, json={'query': 'full-file replacements'})
    assert r.status_code == 200
    data = r.json()
    assert 'sources' in data
    assert 'query' in data
    assert 'total_candidates' in data
    assert data['total_candidates'] >= 1
    assert any('full-file' in s['snippet'] for s in data['sources'])


def test_retrieve_with_project_filter(client):
    proj = client.post('/v1/projects', headers=AUTH, json={'name': 'Test'}).json()
    client.post('/v1/memories', headers=AUTH, json={
        'kind': 'decision', 'content': 'Test project decision', 'project_id': proj['id']})
    r = client.post('/v1/retrieve', headers=AUTH, json={
        'query': 'Test project', 'project_id': proj['id']})
    assert r.status_code == 200


def test_retrieve_requires_admin(client):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    assert client.post('/v1/retrieve', headers=node, json={'query': 'x'}).status_code == 403


def test_retrieve_empty_query(client):
    r = client.post('/v1/retrieve', headers=AUTH, json={'query': 'zzzznonexistent9999'})
    assert r.status_code == 200
    data = r.json()
    assert data['total_candidates'] == 0
    assert data['returned'] == 0


# ---- Chat ----

def test_chat_returns_structured_response(client):
    r = client.post('/v1/chat', headers=AUTH, json={'query': 'What projects are active?'})
    assert r.status_code == 200
    data = r.json()
    assert 'answer' in data
    assert 'sources' in data
    assert 'model_used' in data
    assert 'prompt_version' in data
    assert data['prompt_version'] == 'chat_v1'


def test_chat_with_project_filter(client):
    proj = client.post('/v1/projects', headers=AUTH, json={'name': 'Active Project'}).json()
    r = client.post('/v1/chat', headers=AUTH, json={
        'query': 'status', 'project_id': proj['id']})
    assert r.status_code == 200
    data = r.json()
    assert 'answer' in data


def test_chat_requires_admin(client):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    assert client.post('/v1/chat', headers=node, json={'query': 'x'}).status_code == 403


# ---- Provider ----

def test_provider_interface():
    from core.app.providers.base import ModelProvider, LocalProvider, CloudProvider
    assert hasattr(ModelProvider, 'complete')
    lp = LocalProvider()
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(lp.complete([{'role': 'user', 'content': 'test'}]))
    assert 'answer' in result
    assert 'model_used' in result


def test_prompt_version_constant():
    from core.app.main import PROMPT_VERSION
    assert PROMPT_VERSION == 'chat_v1'
    assert len(PROMPT_VERSION) > 0


def test_no_credentials_in_source():
    """Verify no API keys or passwords are in provider stubs."""
    from core.app.providers import base
    source = open(base.__file__).read()
    assert 'sk-' not in source
    assert 'password' not in source.lower()
    assert 'api_key' not in source.lower()

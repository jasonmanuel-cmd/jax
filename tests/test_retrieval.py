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

@pytest.fixture
def retrieval_db():
    from core.app.db import make_engine
    engine = make_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        yield conn
    engine.dispose()


@pytest.mark.parametrize('project_id, expected', [(None, {'personal'}), ('p1', {'p1-item'})])
@pytest.mark.parametrize('table_name, text_field', [
    ('memories', 'content'), ('tasks', 'title'), ('decisions', 'decision')])
def test_retrieval_never_implicitly_merges_project_scopes(retrieval_db, project_id, expected,
                                                        table_name, text_field):
    from core.app import tables2
    from core.app.retrieval import retrieve_context
    now = datetime.now(timezone.utc)
    for pid in ('p1', 'p2'):
        retrieval_db.execute(tables2.projects.insert().values(
            id=pid, user_id='u1', name=pid, created_at=now))
    table = getattr(tables2, table_name)
    for identifier, scope, user in [('personal', None, 'u1'), ('p1-item', 'p1', 'u1'),
                                    ('p2-item', 'p2', 'u1'), ('other-user', None, 'u2')]:
        values = dict(id=identifier, user_id=user, project_id=scope)
        values[text_field] = 'shared keyword'
        values['decided_at' if table_name == 'decisions' else 'created_at'] = now
        if table_name == 'memories':
            values['kind'] = 'fact'
        retrieval_db.execute(table.insert().values(**values))
    ctx = retrieve_context('shared keyword', project_id=project_id, user_id='u1',
                           db_conn=retrieval_db)
    assert {s['id'] for s in ctx['sources']} == expected


def test_expired_memories_are_not_retrieved(retrieval_db):
    from datetime import timedelta
    from core.app.tables2 import memories
    from core.app.retrieval import retrieve_context
    now = datetime.now(timezone.utc)
    for identifier, expires in [('expired', now - timedelta(seconds=1)),
                                ('future', now + timedelta(days=1)), ('durable', None)]:
        retrieval_db.execute(memories.insert().values(
            id=identifier, user_id='u1', kind='fact', content='keyword',
            created_at=now, expires_at=expires))
    ctx = retrieve_context('keyword', user_id='u1', db_conn=retrieval_db)
    assert {s['id'] for s in ctx['sources']} == {'future', 'durable'}


@pytest.mark.parametrize('project_id', [None, 'p1'])
def test_unscoped_device_events_cannot_leak_into_context(retrieval_db, project_id):
    from core.app.db import devices, events
    from core.app.retrieval import retrieve_context
    retrieval_db.execute(devices.insert().values(
        id='device', name='Laptop', platform='windows', token_hash='test-digest'))
    retrieval_db.execute(events.insert().values(
        id='foreign-project-event', device_id='device', occurred_at=datetime.now(timezone.utc),
        payload={'type': 'git_context', 'summary': 'private project keyword'}))
    # Neither events nor devices has a trusted owner/project relation. A git_context
    # type and a recent timestamp are not proof this event belongs in this context.
    ctx = retrieve_context('keyword', project_id=project_id, user_id='u1',
                           db_conn=retrieval_db)
    assert ctx['sources'] == []


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

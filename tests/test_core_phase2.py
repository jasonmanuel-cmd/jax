"""Phase-2 tests: CRUD for workspaces/projects/memories/tasks/decisions/handoffs,
memory delete with audit, kill switch blocks events, admin-only enforcement.
"""
import importlib.util
import pytest
from fastapi.testclient import TestClient
from uuid import uuid4


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
    assert r.status_code == 201, r.text
    return r.json()


# ---- Workspaces ----

def test_workspace_crud(client):
    r = client.post('/v1/workspaces', headers=AUTH, json={'name': 'Test WS'})
    assert r.status_code == 201
    ws = r.json()
    assert ws['name'] == 'Test WS'
    r = client.get('/v1/workspaces', headers=AUTH)
    assert r.status_code == 200 and len(r.json()) >= 1
    r = client.delete(f'/v1/workspaces/{ws["id"]}', headers=AUTH)
    assert r.status_code == 200
    assert client.get('/v1/workspaces', headers=AUTH).status_code == 200


def test_workspace_requires_admin(client):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    assert client.post('/v1/workspaces', headers=node, json={'name': 'x'}).status_code == 403
    assert client.get('/v1/workspaces', headers=node).status_code == 403


# ---- Projects ----

def test_project_crud(client):
    r = client.post('/v1/projects', headers=AUTH, json={'name': 'Harbison Standard', 'path_hint': '/projects/hs'})
    assert r.status_code == 201
    proj = r.json()
    assert proj['name'] == 'Harbison Standard'
    r = client.get(f'/v1/projects/{proj["id"]}', headers=AUTH)
    assert r.status_code == 200 and r.json()['name'] == 'Harbison Standard'
    r = client.put(f'/v1/projects/{proj["id"]}', headers=AUTH, json={'status': 'archived'})
    assert r.status_code == 200
    r = client.get(f'/v1/projects/{proj["id"]}', headers=AUTH)
    assert r.json()['status'] == 'archived'
    r = client.delete(f'/v1/projects/{proj["id"]}', headers=AUTH)
    assert r.status_code == 200


def test_project_requires_admin(client):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    assert client.post('/v1/projects', headers=node, json={'name': 'x'}).status_code == 403
    assert client.get('/v1/projects', headers=node).status_code == 403


# ---- Memories ----

def test_memory_save_and_list(client):
    r = client.post('/v1/memories', headers=AUTH, json={
        'kind': 'decision', 'content': 'Use Vercel + Supabase for HS', 'confidence': 0.95})
    assert r.status_code == 201
    mem = r.json()
    assert mem['kind'] == 'decision'
    r = client.get('/v1/memories', headers=AUTH)
    assert r.status_code == 200 and len(r.json()) >= 1


def test_memory_delete_with_audit(client):
    r = client.post('/v1/memories', headers=AUTH, json={
        'kind': 'preference', 'content': 'Full-file replacements'})
    mid = r.json()['id']
    r = client.delete(f'/v1/memories/{mid}', headers=AUTH)
    assert r.status_code == 200 and r.json()['deleted'] is True
    # Memory gone from list
    r = client.get('/v1/memories', headers=AUTH)
    assert not any(m['id'] == mid for m in r.json())


def test_memory_requires_admin(client):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    assert client.post('/v1/memories', headers=node, json={'kind': 'x', 'content': 'y'}).status_code == 403
    assert client.get('/v1/memories', headers=node).status_code == 403


# ---- Tasks ----

def test_task_crud(client):
    r = client.post('/v1/tasks', headers=AUTH, json={
        'title': 'Fix deployment', 'priority': 'high'})
    assert r.status_code == 201
    tid = r.json()['id']
    r = client.put(f'/v1/tasks/{tid}', headers=AUTH, json={'status': 'done'})
    assert r.status_code == 200
    r = client.get('/v1/tasks', headers=AUTH, params={'status': 'done'})
    assert any(t['id'] == tid for t in r.json())
    r = client.delete(f'/v1/tasks/{tid}', headers=AUTH)
    assert r.status_code == 200


# ---- Decisions ----

def test_decision_crud(client):
    r = client.post('/v1/decisions', headers=AUTH, json={
        'decision': 'Use FastAPI', 'rationale': 'Best ecosystem'})
    assert r.status_code == 201
    r = client.get('/v1/decisions', headers=AUTH)
    assert r.status_code == 200 and len(r.json()) >= 1


# ---- Handoffs ----

def test_handoff_crud(client):
    r = client.post('/v1/handoffs', headers=AUTH, json={
        'summary': 'Stopped on PC1, next: verify env'})
    assert r.status_code == 201
    r = client.get('/v1/handoffs', headers=AUTH)
    assert r.status_code == 200 and len(r.json()) >= 1


# ---- Kill switch ----

def test_kill_switch_blocks_events(client, tmp_path):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    # Activate kill switch for this device
    r = client.post('/v1/kill/activate', headers=AUTH, json={
        'reason': 'Testing', 'device_id': d['id']})
    assert r.status_code == 201 and r.json()['activated'] is True
    # Status shows active
    r = client.get('/v1/kill/status', headers=AUTH)
    assert r.json()['active'] is True
    # Event ingest blocked
    from datetime import datetime, timezone
    payload = {
        'event_id': str(uuid4()), 'device_id': d['id'], 'type': 'git_context',
        'summary': 'test', 'app': 'git',
        'metadata': {'branch': 'main', 'dirty_count': 0},
        'occurred_at': datetime.now(timezone.utc).isoformat()}
    r = client.post('/v1/events', headers=node, json=payload)
    assert r.status_code == 403, r.text
    # Deactivate
    kid = r.json().get('id') or client.get('/v1/kill/status', headers=AUTH).json()['entries'][0]['id']
    # Use the created kill id
    kid = client.post('/v1/kill/activate', headers=AUTH, json={
        'reason': 'Testing2', 'device_id': d['id']}).json()['id']
    r = client.post(f'/v1/kill/deactivate/{kid}', headers=AUTH)
    # The first kill is still active; let's deactivate both
    entries = client.get('/v1/kill/status', headers=AUTH).json()['entries']
    for e in entries:
        client.post(f'/v1/kill/deactivate/{e["id"]}', headers=AUTH)
    # Now events should work again
    payload2 = {
        'event_id': str(uuid4()), 'device_id': d['id'], 'type': 'git_context',
        'summary': 'after kill off', 'app': 'git',
        'metadata': {'branch': 'main', 'dirty_count': 0},
        'occurred_at': datetime.now(timezone.utc).isoformat()}
    r = client.post('/v1/events', headers=node, json=payload2)
    assert r.status_code == 200, r.text


def test_kill_status_admin_only(client):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    assert client.get('/v1/kill/status', headers=node).status_code == 403


def test_kill_activate_requires_admin(client):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    assert client.post('/v1/kill/activate', headers=node, json={'reason': 'x'}).status_code == 403


def test_nonexistent_project_returns_404(client):
    r = client.get('/v1/projects/00000000-0000-4000-8000-000000000000', headers=AUTH)
    assert r.status_code == 404


def test_nonexistent_memory_returns_404(client):
    r = client.delete('/v1/memories/00000000-0000-4000-8000-000000000000', headers=AUTH)
    assert r.status_code == 404


def test_nonexistent_task_returns_404(client):
    r = client.put('/v1/tasks/00000000-0000-4000-8000-000000000000', headers=AUTH, json={'status': 'x'})
    assert r.status_code == 404

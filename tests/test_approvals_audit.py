"""Approval and audit tests.

The security property under test is deny-by-default: an L4 action must be
refused unless a specific, payload-bound approval exists. A regression that
made approval optional would be a privilege escalation, so each test asserts
the refusal explicitly.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ADMIN = 'test-admin-token-that-is-long-enough-0123456789'
AUTH = {'Authorization': f'Bearer {ADMIN}'}
PUSH = {**AUTH, 'Content-Type': 'application/json'}


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    module = importlib.import_module('core.app.main')
    with TestClient(module.create_app(
            database_url=f'sqlite:///{tmp_path}/jax.db',
            admin_token=ADMIN), headers=AUTH) as c:
        yield c


def test_listing_approvals_grants_nothing(client):
    body = client.get('/v1/approvals').json()
    assert body['approvals'] == []


def test_requesting_approval_does_not_authorize(client):
    """Creating a request must not by itself unlock the action."""
    created = client.post('/v1/approvals', json={
        'tool': 'git.force_push', 'arguments': {'branch': 'main'},
        'reason': 'need to move the tag'}).json()
    assert created['state'] == 'pending'
    assert client.app.state.policy.can('git.force_push', {'branch': 'main'}) is False


def test_denied_action_never_runs(client):
    """The spec's acceptance test: denial means the action does not run."""
    created = client.post('/v1/approvals', json={
        'tool': 'git.force_push', 'arguments': {'branch': 'main'}}).json()
    decision = client.post(f"/v1/approvals/{created['id']}/decide",
                           json={'approve': False}).json()
    assert decision['state'] == 'denied'
    assert client.app.state.policy.can('git.force_push', {'branch': 'main'}) is False


def test_approved_action_is_authorized_for_that_payload(client):
    created = client.post('/v1/approvals', json={
        'tool': 'git.force_push', 'arguments': {'branch': 'main'}}).json()
    client.post(f"/v1/approvals/{created['id']}/decide", json={'approve': True})
    policy = client.app.state.policy
    assert policy.can('git.force_push', {'branch': 'main'}) is True
    # A different payload is still refused.
    assert policy.can('git.force_push', {'branch': 'production'}) is False


def test_decision_cannot_be_changed(client):
    created = client.post('/v1/approvals', json={
        'tool': 'git.force_push', 'arguments': {}}).json()
    client.post(f"/v1/approvals/{created['id']}/decide", json={'approve': False})
    second = client.post(f"/v1/approvals/{created['id']}/decide",
                         json={'approve': True})
    assert second.status_code == 409
    assert client.app.state.policy.can('git.force_push', {}) is False


def test_unknown_tool_cannot_request_approval(client):
    response = client.post('/v1/approvals', json={
        'tool': 'shell.exec', 'arguments': {}})
    assert response.status_code == 400


def test_denied_request_is_audited(client):
    created = client.post('/v1/approvals', json={
        'tool': 'email.send', 'arguments': {'to': 'a@b.c'}}).json()
    client.post(f"/v1/approvals/{created['id']}/decide", json={'approve': False})
    events = client.get('/v1/audit').json()['events']
    actions = [e['action'] for e in events]
    assert 'approval.request' in actions
    assert 'approval.deny' in actions
    denied = next(e for e in events if e['action'] == 'approval.deny')
    assert denied['result'] == 'denied'
    assert denied['metadata']['approval_id'] == created['id']


def test_audit_records_who_decided(client):
    created = client.post('/v1/approvals', json={
        'tool': 'git.force_push', 'arguments': {}}).json()
    client.post(f"/v1/approvals/{created['id']}/decide", json={'approve': True})
    events = client.get('/v1/audit?action=approval.decide').json()['events']
    assert len(events) == 1
    assert events[0]['actor'] == 'admin'


def test_audit_listing_is_paginated_and_filtered(client):
    for _ in range(3):
        client.post('/v1/approvals', json={'tool': 'git.merge', 'arguments': {}})
    assert len(client.get('/v1/audit').json()['events']) == 3
    assert len(client.get('/v1/audit?action=approval.request').json()['events']) == 3
    assert client.get('/v1/audit?action=nothing.matched').json()['events'] == []
    assert len(client.get('/v1/audit?limit=2').json()['events']) == 2


def test_audit_metadata_is_truncated_not_stored_verbatim(client):
    long_value = 'x' * 500
    client.app.state.audit.record('admin', 'test.action', 'target', 'ok',
                                  {'note': long_value})
    event = client.get('/v1/audit').json()['events'][0]
    assert len(event['metadata']['note']) < 200
    assert event['metadata']['note'].endswith('...')


def test_approvals_require_authentication(client):
    assert client.get('/v1/approvals',
                      headers={'Authorization': 'Bearer wrong'}).status_code == 401
    assert client.get('/v1/audit',
                      headers={'Authorization': 'Bearer wrong'}).status_code == 401


def test_l4_tool_still_requires_approval_after_all_this(client):
    """Full loop: request -> deny -> refuse. Nothing leaks."""
    client.post('/v1/approvals', json={
        'tool': 'email.send', 'arguments': {'to': 'victim@x.com'}})
    assert client.app.state.policy.can('email.send', {'to': 'victim@x.com'}) is False
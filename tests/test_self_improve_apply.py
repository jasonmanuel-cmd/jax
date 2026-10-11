"""Self-improvement must never report a change it did not make.

The baseline apply endpoint flipped a row to 'applied' and returned 200 while
writing nothing. These tests pin the honest contract: proposals are
materialized as reviewable patches, protected control code is refused, and
nothing ever silently edits the repository.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.app.self_improve_apply import (  # noqa: E402
    classify_target, materialize_as_patch, validate_proposal,
)

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


def proposal(file_path, new_code='print(1)\n'):
    return {'file_path': str(file_path), 'new_code': new_code,
            'reason': 'test', 'category': 'cleanup'}


# -- protected control code ----------------------------------------------

@pytest.mark.parametrize('relative', [
    'core/app/policy_engine.py',
    'core/app/kill_switch.py',
    'core/app/main.py',
    'core/app/agents/base.py',
    'core/app/audit/approvals.py',
])
def test_control_code_is_protected(relative):
    assert classify_target(relative) == 'protected'


def test_ordinary_code_is_not_protected():
    assert classify_target('core/app/leads.py') == 'ordinary'
    assert classify_target('scripts/tool.py') == 'ordinary'


def test_protected_path_is_refused(tmp_path):
    ok, reason = validate_proposal(proposal('core/app/policy_engine.py'), tmp_path)
    assert ok is False
    assert 'protected' in reason.lower()


def test_materialize_refuses_protected_and_writes_nothing(tmp_path):
    target = tmp_path / 'core' / 'app' / 'policy_engine.py'
    target.parent.mkdir(parents=True)
    target.write_text('ORIGINAL = 1\n', encoding='utf-8')
    outcome = materialize_as_patch(proposal(target), tmp_path)
    assert outcome.applied is False
    assert outcome.status == 'refused'
    # The critical assertion: the file is byte-identical afterwards.
    assert target.read_text(encoding='utf-8') == 'ORIGINAL = 1\n'


# -- path escape ----------------------------------------------------------

def test_path_outside_project_is_refused(tmp_path):
    outside = tmp_path.parent / 'outside.py'
    ok, reason = validate_proposal(proposal(outside), tmp_path)
    assert ok is False
    assert 'outside' in reason.lower()


def test_traversal_is_refused(tmp_path):
    ok, reason = validate_proposal(proposal('../../../etc/passwd'), tmp_path)
    assert ok is False


def test_missing_file_path_is_refused(tmp_path):
    ok, _ = validate_proposal({}, tmp_path)
    assert ok is False


# -- the honest path ------------------------------------------------------

def test_ordinary_proposal_is_materialized_not_applied(tmp_path):
    target = tmp_path / 'src' / 'module.py'
    target.parent.mkdir(parents=True)
    target.write_text('ORIGINAL = 1\n', encoding='utf-8')
    outcome = materialize_as_patch(proposal(target, 'ORIGINAL = 2\n'), tmp_path)
    assert outcome.status == 'materialized'
    assert outcome.applied is False, 'must not claim to have applied'
    assert outcome.requires_review is True
    assert outcome.patch_ref
    # Target untouched; the change lives in a patch for a human.
    assert target.read_text(encoding='utf-8') == 'ORIGINAL = 1\n'
    patch = (tmp_path / outcome.patch_ref).read_text(encoding='utf-8')
    assert 'ORIGINAL = 2' in patch


# -- endpoint contract ----------------------------------------------------

def test_apply_endpoint_does_not_claim_success(client, tmp_path, monkeypatch):
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(tmp_path))
    target = tmp_path / 'module.py'
    target.write_text('ORIGINAL = 1\n', encoding='utf-8')
    from core.app.db import improvement_proposals
    from core.app.self_improve import Proposal, proposal_to_json
    from datetime import datetime, timezone
    from sqlalchemy import insert
    engine = client.app.state.engine
    pid = '11111111-1111-4111-8111-111111111111'
    with engine.begin() as db:
        db.execute(insert(improvement_proposals).values(
            id=pid, file_path=str(target),
            proposal_json=proposal_to_json(Proposal(
                file_path=str(target), old_code='ORIGINAL = 1\n',
                new_code='ORIGINAL = 2\n', reason='test',
                category='cleanup', confidence=1.0, risk_level='low')),
            status='pending', created_at=datetime.now(timezone.utc)))

    response = client.post(f'/v1/self-improve/proposals/{pid}/apply',
                           json={'confirm': True})
    assert response.status_code == 202, 'accepted, not falsely completed'
    payload = response.json()
    assert payload['applied'] is False
    assert payload['requires_review'] is True
    assert 'No file was modified' in payload['note']
    assert target.read_text(encoding='utf-8') == 'ORIGINAL = 1\n'


def test_apply_requires_explicit_confirm(client, tmp_path, monkeypatch):
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(tmp_path))
    target = tmp_path / 'module.py'
    target.write_text('X = 1\n', encoding='utf-8')
    from core.app.db import improvement_proposals
    from core.app.self_improve import Proposal, proposal_to_json
    from datetime import datetime, timezone
    from sqlalchemy import insert
    engine = client.app.state.engine
    with engine.begin() as db:
        db.execute(insert(improvement_proposals).values(
            id='22222222-2222-4222-8222-222222222222', file_path=str(target),
            proposal_json=proposal_to_json(Proposal(file_path=str(target),
                                               new_code='X = 2\n', old_code='X = 1\n',
                                               reason='t', category='cleanup',
                                               confidence=1.0, risk_level='low')),
            status='pending', created_at=datetime.now(timezone.utc)))
    assert client.post('/v1/self-improve/proposals/22222222-2222-4222-8222-222222222222/apply',
                       json={'confirm': False}).status_code == 400


def test_apply_of_unknown_proposal_is_404(client):
    assert client.post('/v1/self-improve/proposals/99999999-9999-4999-8999-999999999999/apply',
                       json={'confirm': True}).status_code == 404


def test_apply_is_audited(client, tmp_path, monkeypatch):
    monkeypatch.setenv('JAX_PROJECT_ROOTS', str(tmp_path))
    target = tmp_path / 'module.py'
    target.write_text('X = 1\n', encoding='utf-8')
    from core.app.db import improvement_proposals
    from core.app.self_improve import Proposal, proposal_to_json
    from datetime import datetime, timezone
    from sqlalchemy import insert
    engine = client.app.state.engine
    with engine.begin() as db:
        db.execute(insert(improvement_proposals).values(
            id='33333333-3333-4333-8333-333333333333', file_path=str(target),
            proposal_json=proposal_to_json(Proposal(file_path=str(target),
                                               new_code='X = 2\n', old_code='X = 1\n',
                                               reason='t', category='cleanup',
                                               confidence=1.0, risk_level='low')),
            status='pending', created_at=datetime.now(timezone.utc)))
    client.post('/v1/self-improve/proposals/33333333-3333-4333-8333-333333333333/apply', json={'confirm': True})
    events = client.get('/v1/audit?action=self_improve.apply').json()['events']
    assert len(events) == 1
    assert events[0]['metadata']['applied'] is False
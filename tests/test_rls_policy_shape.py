"""RLS policy shape (SPEC_AUDIT R2).

The audit found policies commented as "readable by all authenticated users"
that were actually FOR ALL with WITH CHECK (true) - meaning any authenticated
client could write every row, including approval records and the permission
table itself. These tests assert the *shape* of the policies, since that is
what the defect was, and they run without a live Postgres.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RLS = (ROOT / 'supabase' / '003_rls.sql').read_text(encoding='utf-8')


def policies():
    """Yield (name, table, body) for every CREATE POLICY.

    Non-greedy to the first semicolon: a body must not run on into the next
    statement, or every policy after the first looks like a FOR ALL write.
    """
    pattern = re.compile(
        r'CREATE POLICY\s+(\w+)\s+ON\s+(\w+)([^;]*);')
    for match in pattern.finditer(RLS):
        yield match.group(1), match.group(2), match.group(3)


def body_of(table):
    return [body for _, t, body in policies() if t == table]


def client_bodies(table):
    """Only policies aimed at the authenticated (client) role."""
    return [b for b in body_of(table) if 'TO authenticated' in b]


# -- the defect itself ----------------------------------------------------

@pytest.mark.parametrize('table', ['tool_runs', 'agent_runs',
                                   'improvement_proposals'])
def test_client_cannot_mutate_evidence_tables(table):
    """A client may propose, but must not be able to forge execution evidence.

    For tool_runs and agent_runs no client write is permitted at all. For
    improvement_proposals a client may INSERT a proposal, but may never UPDATE
    or DELETE it: status transitions are service-role only, so a proposal
    cannot be self-approved.
    """
    allow_insert = table == 'improvement_proposals'
    for body in client_bodies(table):
        if not allow_insert:
            assert 'FOR INSERT' not in body, f'{table} allows client INSERT'
        assert 'FOR UPDATE' not in body, f'{table} allows client UPDATE'
        assert 'FOR DELETE' not in body, f'{table} allows client DELETE'
        assert 'FOR ALL' not in body, f'{table} still has a blanket FOR ALL policy'


def test_tool_permissions_is_read_only():
    """The permission table must never be writable by a client."""
    for body in client_bodies('tool_permissions'):
        assert 'FOR SELECT' in body, 'tool_permissions must be readable'
        for write in ('FOR INSERT', 'FOR UPDATE', 'FOR DELETE', 'FOR ALL'):
            assert write not in body, f'tool_permissions must not allow {write}'


def test_audit_events_is_read_only_to_clients():
    """Append-only: no client INSERT, UPDATE or DELETE."""
    for name, table, body in policies():
        if table != 'audit_events':
            continue
        if 'TO service_role' in body or 'TO authenticated' not in body:
            continue
        assert 'FOR SELECT' in body, f'audit_events client policy {name} is not read-only'
        for write in ('FOR INSERT', 'FOR UPDATE', 'FOR DELETE', 'FOR ALL'):
            assert write not in body, f'audit_events client policy allows {write}'


def test_handoffs_are_readable_but_not_writable():
    """Cross-device reconstruction reads handoffs, so read must stay open."""
    bodies = client_bodies('handoffs')
    assert bodies, 'handoffs must remain readable to authenticated users'
    for body in bodies:
        assert 'FOR SELECT' in body
        for write in ('FOR INSERT', 'FOR UPDATE', 'FOR DELETE', 'FOR ALL'):
            assert write not in body, f'handoffs must not allow {write}'


def test_no_client_policy_is_a_bare_using_true_for_all():
    """The exact shape of the original defect."""
    for name, table, body in policies():
        if 'TO authenticated' not in body:
            continue
        if 'FOR ALL' in body and re.search(r'WITH CHECK\s*\(\s*true\s*\)', body):
            pytest.fail(
                f'{name} on {table} is FOR ALL WITH CHECK (true): '
                'any authenticated client can write every row')


def test_kill_switch_writes_require_ownership():
    for body in client_bodies('kill_switch'):
        if 'FOR INSERT' in body or 'FOR UPDATE' in body:
            assert 'activated_by = auth.uid()' in body, \
                'kill switch writes must be restricted to the activating user'


# -- service role keeps full access ---------------------------------------

@pytest.mark.parametrize('table', ['projects', 'memories', 'tasks', 'decisions',
                                   'handoffs', 'tool_runs', 'agent_runs',
                                   'audit_events', 'kill_switch'])
def test_service_role_retains_full_access(table):
    """The core runs as service role; it must not be locked out."""
    assert any('TO service_role' in body for _, t, body in policies() if t == table), \
        f'{table} has no service_role policy'


def test_service_role_policy_set_is_present():
    service_tables = {t for _, t, body in policies() if 'TO service_role' in body}
    assert 'audit_events' in service_tables
    assert 'tool_permissions' in service_tables


# -- row isolation is still real ------------------------------------------

@pytest.mark.parametrize('table', ['workspaces', 'projects', 'memories',
                                   'tasks', 'decisions'])
def test_user_owned_tables_still_isolate_rows(table):
    for body in client_bodies(table):
        assert 'auth.uid()' in body, f'{table} lost its row isolation'
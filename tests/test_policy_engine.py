"""Policy engine tests: autonomy levels, approvals, and the tool boundary.

Every denial here is a security boundary, so each test asserts both the
refusal and the reason, so a future refactor cannot quietly widen access.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.app.policy_engine import (  # noqa: E402
    L0_OBSERVE, L1_ORGANIZE, L2_PREPARE, L3_EXECUTE_REVERSIBLE, L4_CONFIRMATION,
    Approval, PolicyDenied, PolicyEngine, ToolPolicy, default_registry,
    payload_binding,
)


def approval_for(tool, arguments, **kw):
    return Approval(id=kw.pop('id', 'a1'), tool=tool,
                    arguments_hash=payload_binding(tool, arguments),
                    max_level=kw.pop('max_level', L4_CONFIRMATION), **kw)


def test_level_ordering_is_strict():
    assert L0_OBSERVE < L1_ORGANIZE < L2_PREPARE < L3_EXECUTE_REVERSIBLE < L4_CONFIRMATION


def test_irreversible_tool_cannot_claim_to_be_safe():
    """An irreversible tool must be L4; the registry refuses to register otherwise."""
    with pytest.raises(ValueError, match='must be L4'):
        ToolPolicy('dangerous.delete', L3_EXECUTE_REVERSIBLE,
                   reversible=False)


def test_invalid_level_rejected():
    with pytest.raises(ValueError, match='invalid autonomy level'):
        ToolPolicy('tool', 9)


def test_l4_implies_approval_required():
    policy = ToolPolicy('git.force_push', L4_CONFIRMATION, reversible=False)
    assert policy.requires_approval is True


def test_unknown_tool_is_denied():
    engine = default_registry()
    with pytest.raises(PolicyDenied) as excinfo:
        engine.check('shell.exec', {})
    assert excinfo.value.code == 'unknown_tool'


def test_observation_tools_allowed_without_approval():
    engine = default_registry()
    assert engine.can('git.inspect', {})
    assert engine.can('files.read_project', {})


def test_draft_allowed_but_send_requires_approval():
    """email.draft (L2) and email.send (L4) must never share a boundary."""
    engine = default_registry()
    args = {'to': 'someone@example.com', 'body': 'hello'}
    assert engine.can('email.draft', args) is True
    assert engine.can('email.send', args) is False


def test_force_push_requires_explicit_approval():
    engine = default_registry()
    assert engine.can('git.force_push', {}) is False
    engine.grant_approval(approval_for('git.force_push', {}))
    assert engine.can('git.force_push', {}) is True


def test_approval_is_bound_to_exact_payload():
    """An approval for one payload must not authorise a different one."""
    engine = default_registry()
    approved = {'to': 'alice@example.com', 'body': 'invoice attached'}
    engine.grant_approval(approval_for('email.send', approved))
    assert engine.can('email.send', approved) is True
    assert engine.can('email.send', {'to': 'attacker@evil.com'}) is False
    assert engine.can('email.send', {'to': 'alice@example.com'}) is False


def test_approval_cannot_be_replayed_against_another_tool():
    engine = default_registry()
    args = {'branch': 'main'}
    engine.grant_approval(approval_for('email.send', args))
    # Same payload, different tool: the digest mixes in the tool name.
    assert engine.can('git.merge', args) is False


def test_different_tool_same_payload_has_distinct_digest():
    args = {'x': 1}
    assert payload_binding('email.send', args) != payload_binding('git.merge', args)


def test_expired_approval_is_refused():
    engine = default_registry()
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    engine.grant_approval(approval_for('git.force_push', {}, expires_at=past))
    assert engine.can('git.force_push', {}) is False


def test_unexpired_approval_is_honoured():
    engine = default_registry()
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    engine.grant_approval(approval_for('git.force_push', {}, expires_at=future))
    assert engine.can('git.force_push', {}) is True


def test_revoked_approval_is_refused():
    engine = default_registry()
    engine.grant_approval(approval_for('git.force_push', {}, approved=False))
    assert engine.can('git.force_push', {}) is False


def test_ceiling_blocks_tool_above_granted_level():
    """A low ceiling must block even a registered L3 tool."""
    engine = PolicyEngine(ceiling=L1_ORGANIZE)
    engine.register(ToolPolicy('git.fetch', L3_EXECUTE_REVERSIBLE))
    with pytest.raises(PolicyDenied) as excinfo:
        engine.check('git.fetch', {})
    assert excinfo.value.code == 'level_exceeds_ceiling'


def test_invalid_ceiling_rejected():
    with pytest.raises(ValueError, match='invalid ceiling'):
        PolicyEngine(ceiling=99)


def test_duplicate_registration_rejected():
    engine = default_registry()
    with pytest.raises(ValueError, match='already registered'):
        engine.register(ToolPolicy('git.inspect', L0_OBSERVE))


def test_approval_cannot_elevate_beyond_its_own_max_level():
    """An approval scoped to L2 must not unlock an L4 tool."""
    engine = default_registry()
    engine.grant_approval(approval_for('git.force_push', {}, max_level=L2_PREPARE))
    with pytest.raises(PolicyDenied):
        engine.check('git.force_push', {})


def test_denial_exposes_machine_readable_code():
    engine = default_registry()
    with pytest.raises(PolicyDenied) as excinfo:
        engine.check('git.force_push', {})
    assert excinfo.value.code == 'approval_required'
    assert 'git.force_push' in str(excinfo.value)
"""Autonomy levels and the tool policy boundary.

The model is a worker; JAX owns the contract. Nothing here consults a model.
A capability is allowed only if its level is at or below the granted ceiling,
and any L4 action is denied unless an explicit, unexpired approval exists.

Fail closed: an unknown tool, a malformed policy row, or an approval for a
different payload all deny.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Ordered least to most capable. Compare with <=, never with truthiness.
L0_OBSERVE = 0
L1_ORGANIZE = 1
L2_PREPARE = 2
L3_EXECUTE_REVERSIBLE = 3
L4_CONFIRMATION = 4

LEVEL_NAMES = {
    L0_OBSERVE: 'observe',
    L1_ORGANIZE: 'organize',
    L2_PREPARE: 'prepare',
    L3_EXECUTE_REVERSIBLE: 'execute_reversible',
    L4_CONFIRMATION: 'explicit_confirmation',
}


class PolicyDenied(Exception):
    """Raised when policy refuses an action. Never swallowed by callers."""

    def __init__(self, code: str, detail: str):
        super().__init__(f'{code}: {detail}')
        self.code = code
        self.detail = detail


def payload_binding(tool: str, arguments: dict[str, Any]) -> str:
    """Bind an approval to exactly one payload.

    Canonical JSON so key order cannot change the digest, and the tool name is
    mixed in so an approval cannot be replayed against a different tool.
    """
    canonical = json.dumps(arguments, sort_keys=True, separators=(',', ':'),
                           default=str)
    return hashlib.sha256(f'{tool}\x00{canonical}'.encode()).hexdigest()


@dataclass
class Approval:
    id: str
    tool: str
    arguments_hash: str
    max_level: int
    approved: bool = True
    expires_at: datetime | None = None
    reason: str | None = None

    def is_valid(self, tool: str, arguments: dict[str, Any], now: datetime) -> bool:
        if not self.approved:
            return False
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None:
                self.expires_at = self.expires_at.replace(tzinfo=timezone.utc)
            if self.expires_at <= now:
                return False
        # Both the tool and the exact payload must match.
        if self.tool != tool:
            return False
        return self.arguments_hash == payload_binding(tool, arguments)


@dataclass
class ToolPolicy:
    """Registry entry: what a tool is, how risky it is, and how it is gated."""
    name: str
    level: int
    description: str = ''
    requires_approval: bool = False
    reversible: bool = True
    constraints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.level not in LEVEL_NAMES:
            raise ValueError(f'invalid autonomy level {self.level} for {self.name}')
        # Anything irreversible is L4 by construction; never let a registry
        # entry quietly claim to be safe.
        if not self.reversible and self.level < L4_CONFIRMATION:
            raise ValueError(
                f'irreversible tool {self.name} must be L4, got L{self.level}')
        if self.level == L4_CONFIRMATION:
            self.requires_approval = True


class PolicyEngine:
    """Grants, ceilings, and approval checks. Deterministic and testable."""

    def __init__(self, ceiling: int = L3_EXECUTE_REVERSIBLE):
        if ceiling not in LEVEL_NAMES:
            raise ValueError(f'invalid ceiling {ceiling}')
        self.ceiling = ceiling
        self.registry: dict[str, ToolPolicy] = {}
        self.approvals: dict[str, Approval] = {}

    # -- registry ---------------------------------------------------------

    def register(self, policy: ToolPolicy) -> ToolPolicy:
        if policy.name in self.registry:
            raise ValueError(f'tool already registered: {policy.name}')
        self.registry[policy.name] = policy
        return policy

    def get(self, name: str) -> ToolPolicy:
        policy = self.registry.get(name)
        if policy is None:
            raise PolicyDenied('unknown_tool', f'{name} is not in the registry')
        return policy

    # -- approval ---------------------------------------------------------

    def grant_approval(self, approval: Approval) -> Approval:
        self.approvals[approval.id] = approval
        return approval

    def check(self, tool: str, arguments: dict[str, Any] | None = None,
              now: datetime | None = None) -> ToolPolicy:
        """Authorize a tool call, or raise PolicyDenied.

        Order matters. Registry membership is checked first, so a valid
        approval can never smuggle in a tool that was never registered.

        An approval is a one-time elevation, so it is resolved before the
        ceiling: otherwise an L3 ceiling would make L4 permanently
        unreachable and the confirmation path could never be exercised.
        """
        arguments = arguments or {}
        now = now or datetime.now(timezone.utc)
        policy = self.get(tool)

        approval = None
        if policy.requires_approval or policy.level == L4_CONFIRMATION:
            for candidate in self.approvals.values():
                if candidate.is_valid(tool, arguments, now):
                    approval = candidate
                    break
            if approval is None:
                wanted = payload_binding(tool, arguments)
                raise PolicyDenied(
                    'approval_required',
                    f'{tool} is L{policy.level} and needs an unexpired approval '
                    f'bound to payload {wanted[:12]}')

        effective_ceiling = max(self.ceiling,
                                approval.max_level if approval else L0_OBSERVE)
        if policy.level > effective_ceiling:
            raise PolicyDenied(
                'level_exceeds_ceiling',
                f'{tool} is L{policy.level} but the ceiling is L{effective_ceiling}')

        return policy

    def can(self, tool: str, arguments: dict[str, Any] | None = None,
            now: datetime | None = None) -> bool:
        try:
            self.check(tool, arguments, now)
        except PolicyDenied:
            return False
        return True


def default_registry() -> PolicyEngine:
    """The V1 tool surface. Narrow by construction.

    Splitting email.draft from email.send is the point: drafting is L2,
    sending is L4 and therefore always needs a payload-bound approval.
    """
    engine = PolicyEngine(ceiling=L3_EXECUTE_REVERSIBLE)
    for policy in (
        ToolPolicy('git.inspect', L0_OBSERVE, 'Read repository state'),
        ToolPolicy('git.fetch', L3_EXECUTE_REVERSIBLE, 'Fetch remote refs'),
        ToolPolicy('git.fast_forward', L3_EXECUTE_REVERSIBLE,
                   'Fast-forward a proven BEHIND repo only'),
        ToolPolicy('files.read_project', L0_OBSERVE, 'Read project files'),
        # Launching a managed agent is itself a capability, so it is gated
        # rather than assumed: the caller must hold at least L3 to start a
        # process. Whether a given agent may then act is decided per tool call.
        ToolPolicy('process.launch_agent', L3_EXECUTE_REVERSIBLE,
                   'Launch a managed coding agent inside a project'),
        ToolPolicy('git.force_push', L4_CONFIRMATION, 'Force push',
                   reversible=False),
        ToolPolicy('git.merge', L4_CONFIRMATION, 'Merge branches',
                   reversible=True),
        ToolPolicy('git.rebase', L4_CONFIRMATION, 'Rebase branches',
                   reversible=True),
        ToolPolicy('email.draft', L2_PREPARE, 'Draft an email, never send'),
        ToolPolicy('email.send', L4_CONFIRMATION, 'Send an email',
                   reversible=False),
    ):
        engine.register(policy)
    return engine
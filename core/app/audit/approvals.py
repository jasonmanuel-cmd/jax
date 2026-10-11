"""Approval store and append-only audit log.

Two rules from the spec, enforced here rather than left to callers:

1. Deny by default. An action with no approval is refused. Approvals bind to
   one exact payload and expire.
2. The audit log is append-only. No update or delete path exists, so an
   operator cannot quietly rewrite what a capability did.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..policy_engine import Approval, payload_binding


def _now():
    return datetime.now(timezone.utc)


def _as_utc(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class ApprovalStore:
    """Durable approvals backed by tool_runs.

    A row is a *request*. It is only usable once approved, is bound to the
    payload digest, and expires. Denial is recorded, not deleted, so a
    refused consequential action leaves evidence.
    """

    DEFAULT_TTL = timedelta(minutes=15)

    def __init__(self, engine, policy_engine):
        self.engine = engine
        self.policy = policy_engine

    # -- writes -----------------------------------------------------------

    def request(self, user_id: str, tool: str, arguments: dict,
                device_id: str | None = None, ttl: timedelta | None = None,
                reason: str | None = None):
        """Create a pending approval request. It grants nothing yet."""
        policy = self.policy.get(tool)          # raises if unregistered
        from ..tables2 import tool_runs
        approval_id = str(uuid.uuid4())
        expires = _now() + (ttl or self.DEFAULT_TTL)
        with self.engine.begin() as db:
            db.execute(tool_runs.insert().values(
                id=approval_id, tool_name=tool,
                arguments_hash=payload_binding(tool, arguments),
                reason=reason, approval_state='pending',
                result=None, device_id=device_id, created_at=_now()))
        return {'id': approval_id, 'tool': tool, 'state': 'pending',
                'expires_at': expires.isoformat(),
                'level': policy.level,
                'requires_approval': policy.requires_approval}

    def decide(self, approval_id: str, approve: bool, reviewer: str):
        """Approve or deny. Either way the decision is recorded."""
        from ..tables2 import tool_runs
        with self.engine.begin() as db:
            row = db.execute(
                select(tool_runs).where(tool_runs.c.id == approval_id)
            ).mappings().first()
            if row is None:
                raise KeyError(approval_id)
            if row['approval_state'] != 'pending':
                raise ValueError(
                    f"already {row['approval_state']}; a decision cannot be changed")
            state = 'approved' if approve else 'denied'
            db.execute(tool_runs.update().where(tool_runs.c.id == approval_id)
                       .values(approval_state=state,
                               result=f'{state} by {reviewer}'))
            if approve:
                self.policy.grant_approval(Approval(
                    id=approval_id, tool=row['tool_name'],
                    arguments_hash=row['arguments_hash'],
                    max_level=self.policy.get(row['tool_name']).level,
                    approved=True, expires_at=self._expires(row)))
        # Return the tool name: the caller needs it for the audit record.
        return {'id': approval_id, 'tool': row['tool_name'], 'state': state}

    def _expires(self, row) -> datetime | None:
        created = _as_utc(row['created_at'])
        return created + self.DEFAULT_TTL if created else None

    # -- reads ------------------------------------------------------------

    def list(self, state: str | None = None):
        from ..tables2 import tool_runs
        with self.engine.connect() as db:
            stmt = select(tool_runs).where(tool_runs.c.approval_state.isnot(None))
            if state:
                stmt = stmt.where(tool_runs.c.approval_state == state)
            rows = db.execute(stmt.order_by(tool_runs.c.created_at.desc())
                              ).mappings().all()
        now = _now()
        out = []
        for row in rows:
            expires = self._expires(row)
            out.append({
                'id': row['id'], 'tool': row['tool_name'],
                'state': row['approval_state'], 'reason': row['reason'],
                'created_at': _as_utc(row['created_at']).isoformat() if row['created_at'] else None,
                'expires_at': expires.isoformat() if expires else None,
                'expired': bool(expires and expires <= now),
                'payload_hash': (row['arguments_hash'] or '')[:12],
            })
        return out


class AuditLog:
    """Append-only. There is deliberately no update or delete method."""

    def __init__(self, engine):
        self.engine = engine

    def record(self, actor: str, action: str, target: str,
               result: str, metadata: dict | None = None) -> str:
        """Write one audit event. Content is minimized: no secret values."""
        from sqlalchemy import insert
        from ..tables2 import audit_events
        event_id = str(uuid.uuid4())
        safe_meta = {}
        for key, value in (metadata or {}).items():
            # Never persist arguments verbatim: they may carry payloads that
            # the privacy policy would have rejected at the API boundary.
            if isinstance(value, str) and len(value) > 120:
                safe_meta[key] = value[:120] + '...'
            else:
                safe_meta[key] = value
        with self.engine.begin() as db:
            db.execute(insert(audit_events).values(
                id=event_id, actor=actor, action=action, target=target,
                result=result, metadata=safe_meta, created_at=_now()))
        return event_id

    def list(self, limit: int = 100, action: str | None = None):
        from ..tables2 import audit_events
        with self.engine.connect() as db:
            stmt = select(audit_events).order_by(audit_events.c.created_at.desc())
            if action:
                stmt = stmt.where(audit_events.c.action == action)
            rows = db.execute(stmt.limit(min(limit, 500))).mappings().all()
        return [{'id': r['id'], 'actor': r['actor'], 'action': r['action'],
                 'target': r['target'], 'result': r['result'],
                 'metadata': r['metadata'],
                 'created_at': _as_utc(r['created_at']).isoformat() if r['created_at'] else None}
                for r in rows]

"""Self-improvement proposal application.

The baseline `apply` endpoint flipped a database row to 'applied' and returned
success. Nothing was written to disk, no branch was created, no test ran. A
caller reading that response would reasonably believe a change had been made to
their code.

Two honest options exist. This module takes the conservative one: a proposal is
never applied automatically. It is materialized as a *patch proposal* on a
branch that a human reviews and merges, and the response reports exactly what
did and did not happen.

Per the spec, self-modification of core or policy code additionally requires
approval; that gate is enforced here rather than documented as a TODO.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

# Core and policy paths are the ones the spec protects most strongly:
# unreviewed self-modification of control or permission logic is a hard block.
PROTECTED = (
    re.compile(r'(^|[\\/])core[\\/]app[\\/]policy_engine\.py$'),
    re.compile(r'(^|[\\/])core[\\/]app[\\/]kill_switch\.py$'),
    re.compile(r'(^|[\\/])core[\\/]app[\\/](agents|audit)[\\/]'),
    re.compile(r'(^|[\\/])core[\\/]app[\\/]main\.py$'),
)


@dataclass
class ApplyOutcome:
    applied: bool
    status: str
    reason: str
    patch_ref: str | None = None
    requires_review: bool = True
    file_path: str | None = None

    def to_dict(self) -> dict:
        return {'applied': self.applied, 'status': self.status,
                'reason': self.reason, 'patch_ref': self.patch_ref,
                'requires_review': self.requires_review,
                'file_path': self.file_path}


def classify_target(file_path: str) -> str:
    """Return 'protected' for policy/control code, 'ordinary' otherwise."""
    normalized = file_path.replace('\\', '/')
    return 'protected' if any(p.search(normalized) for p in PROTECTED) else 'ordinary'


def validate_proposal(proposal: dict, project_root: Path) -> tuple[bool, str]:
    """Check a proposal is safe to materialize as a patch.

    Refuses anything that escapes the project root, targets protected control
    code, or writes outside the repository.
    """
    file_path = (proposal or {}).get('file_path') or ''
    if not file_path:
        return False, 'Proposal has no file_path'

    if classify_target(file_path) == 'protected':
        return False, ('Target is protected control or policy code. Self-modification '
                       'requires a human patch reviewed through the normal merge '
                       'pipeline, not the self-improvement path.')

    try:
        root = project_root.resolve()
        candidate = Path(file_path)
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        return False, 'Proposal path could not be resolved'

    if not str(resolved).startswith(str(root)):
        return False, 'Proposal targets a path outside the project root'
    return True, 'ok'


def materialize_as_patch(proposal: dict, project_root: Path) -> ApplyOutcome:
    """Write the proposal to a patch file for human review.

    Deliberately does NOT modify the target file. JAX may propose, test and
    review; it must not silently rewrite and deploy its own code.
    """
    ok, reason = validate_proposal(proposal, project_root)
    if not ok:
        return ApplyOutcome(applied=False, status='refused', reason=reason)

    patch_ref = f'.jax/patches/{uuid4()}.patch'
    patch_path = project_root / patch_ref
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    new_code = (proposal or {}).get('new_code') or ''
    patch_path.write_text(
        f'# JAX proposal patch - requires human review\n'
        f'# file: {proposal.get("file_path")}\n'
        f'# reason: {proposal.get("reason")}\n\n{new_code}\n',
        encoding='utf-8')
    return ApplyOutcome(
        applied=False, status='materialized', reason=reason, patch_ref=patch_ref,
        requires_review=True, file_path=proposal.get('file_path'))
"""Tests for the JAX self-improvement code analyzer and proposal system."""
import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from core.app.self_improve import (
    LEVEL_DRAFT,
    Proposal,
    analyze_file,
    analyze_project,
    proposal_from_json,
    proposal_to_json,
    _find_unused_imports,
    _find_unreachable_code,
    _find_missing_docstrings,
    _find_magic_numbers,
    _find_complex_functions,
    _scan_security,
    _complexity,
)

ADMIN = 'test-admin-token-with-at-least-32-characters'
AUTH = {'Authorization': f'Bearer {ADMIN}'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def factory():
    from core.app.main import create_app
    return create_app


def _run(source: str) -> list[Proposal]:
    """Convenience: run all analyzers on a source string."""
    import ast
    tree = ast.parse(source)
    proposals: list[Proposal] = []
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            setattr(child, "_parent", node)
    proposals.extend(_find_unused_imports(tree, source))
    proposals.extend(_find_unreachable_code(tree, source))
    proposals.extend(_find_missing_docstrings(tree, source))
    proposals.extend(_find_magic_numbers(tree, source))
    proposals.extend(_find_complex_functions(tree, source))
    proposals.extend(_scan_security(source, "<test>"))
    return proposals


# ---------------------------------------------------------------------------
# Proposal serialization
# ---------------------------------------------------------------------------

def test_proposal_round_trip():
    p = Proposal(
        file_path="x.py", old_code="import os", new_code="",
        reason="unused", category="unused_import",
        confidence=0.95, risk_level="low",
    )
    raw = proposal_to_json(p)
    d = proposal_from_json(raw)
    assert d["file_path"] == "x.py"
    assert d["category"] == "unused_import"
    assert d["confidence"] == 0.95
    assert d["risk_level"] == "low"
    assert 0.0 <= d["confidence"] <= 1.0


def test_level_is_two():
    """Proposals are Level-2 draft only."""
    assert LEVEL_DRAFT == 2


# ---------------------------------------------------------------------------
# Unused import detection
# ---------------------------------------------------------------------------

def test_unused_import_detected():
    source = "import os\nimport sys\nprint(sys.version)\n"
    proposals = [p for p in _run(source) if p.category == "unused_import"]
    assert any("os" in p.reason for p in proposals)


def test_used_import_not_flagged():
    source = "import os\nprint(os.sep)\n"
    proposals = [p for p in _run(source) if p.category == "unused_import"]
    assert len(proposals) == 0


def test_unused_from_import():
    source = "from pathlib import Path, PurePath\nprint(Path('.'))\n"
    proposals = [p for p in _run(source) if p.category == "unused_import"]
    assert any("PurePath" in p.reason for p in proposals)


# ---------------------------------------------------------------------------
# Missing docstring detection
# ---------------------------------------------------------------------------

def test_missing_docstring_flagged():
    source = "def hello():\n    return 'hi'\n"
    proposals = [p for p in _run(source) if p.category == "missing_docstring"]
    assert len(proposals) == 1
    assert "hello" in proposals[0].reason


def test_private_function_skipped():
    source = "def _helper():\n    return 1\n"
    proposals = [p for p in _run(source) if p.category == "missing_docstring"]
    assert len(proposals) == 0


def test_test_function_skipped():
    source = "def test_something():\n    assert True\n"
    proposals = [p for p in _run(source) if p.category == "missing_docstring"]
    assert len(proposals) == 0


def test_docstringed_function_not_flagged():
    source = 'def foo():\n    """Do something."""\n    return 1\n'
    proposals = [p for p in _run(source) if p.category == "missing_docstring"]
    assert len(proposals) == 0


# ---------------------------------------------------------------------------
# Magic number detection
# ---------------------------------------------------------------------------

def test_magic_number_flagged():
    source = "def calc():\n    return 42 * 3.14\n"
    proposals = [p for p in _run(source) if p.category == "magic_number"]
    # 3.14 should be flagged; 42 should too
    assert len(proposals) >= 1


def test_exempt_numbers_not_flagged():
    source = "def calc():\n    return 0 + 1 - 1\n"
    proposals = [p for p in _run(source) if p.category == "magic_number"]
    assert len(proposals) == 0


def test_named_constant_not_flagged():
    source = "MAX_RETRIES = 5\n"
    proposals = [p for p in _run(source) if p.category == "magic_number"]
    assert len(proposals) == 0


# ---------------------------------------------------------------------------
# Cyclomatic complexity
# ---------------------------------------------------------------------------

def test_simple_function_low_complexity():
    source = "def simple():\n    return 1\n"
    tree = __import__('ast').parse(source)
    cx = _complexity(tree.body[0])
    assert cx == 1


def test_complex_function_flagged():
    """Build a function with complexity > 10."""
    branches = "\n".join(f"    if x{i}:\n        pass" for i in range(12))
    source = f"def complex_fn():\n{branches}\n"
    proposals = [p for p in _run(source) if p.category == "complexity"]
    assert len(proposals) == 1
    assert "complex_fn" in proposals[0].reason


# ---------------------------------------------------------------------------
# Security scanner
# ---------------------------------------------------------------------------

def test_security_catches_eval():
    source = "result = eval(user_input)\n"
    proposals = _scan_security(source, "x.py")
    assert any(p.category == "security" and "eval" in p.reason for p in proposals)


def test_security_catches_exec():
    source = "exec(code)\n"
    proposals = _scan_security(source, "x.py")
    assert any(p.category == "security" and "exec" in p.reason for p in proposals)


def test_security_catches_hardcoded_secret():
    source = "password = 'supersecretvalue123'\n"
    proposals = _scan_security(source, "x.py")
    assert any(p.category == "security" and "secret" in p.reason.lower() for p in proposals)


def test_security_catches_shell_true():
    source = "subprocess.call('ls', shell=True)\n"
    proposals = _scan_security(source, "x.py")
    assert any(p.category == "security" and "shell" in p.reason.lower() for p in proposals)


def test_security_ignores_comments():
    source = "# eval(user_input)\n"
    proposals = _scan_security(source, "x.py")
    assert len(proposals) == 0


def test_security_no_false_positive_on_safe_code():
    source = "result = 2 + 2\nprint(result)\n"
    proposals = _scan_security(source, "x.py")
    assert len(proposals) == 0


# ---------------------------------------------------------------------------
# Full-file analysis
# ---------------------------------------------------------------------------

def test_analyze_file_returns_proposals():
    source = "import os\nimport re\n\ndef helper():\n    return 1\n"
    proposals = analyze_file("dummy.py", source)
    assert len(proposals) > 0
    assert all(isinstance(p, Proposal) for p in proposals)
    assert all(0.0 <= p.confidence <= 1.0 for p in proposals)
    assert all(p.risk_level in ("low", "medium", "high") for p in proposals)


def test_analyze_file_stamps_paths(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("import json\n")
    proposals = analyze_file(src)
    assert all(p.file_path == str(src) for p in proposals)


# ---------------------------------------------------------------------------
# Project analysis (against the actual JAX codebase)
# ---------------------------------------------------------------------------

def test_analyze_project_on_jax_core():
    """Run analysis on the real core/ directory — should find real issues."""
    root = Path(__file__).resolve().parents[1] / "core"
    proposals = analyze_project(root)
    # Should find real issues across multiple categories
    assert len(proposals) > 0
    categories = {p.category for p in proposals}
    # Should catch multiple categories of issues in the real codebase
    assert len(categories) >= 3
    # All proposals have valid structure
    for p in proposals:
        assert p.file_path
        assert p.old_code is not None
        assert p.new_code is not None
        assert p.reason
        assert p.category
        assert 0.0 <= p.confidence <= 1.0
        assert p.risk_level in ("low", "medium", "high")


def test_analyze_project_excludes_tests_and_venv():
    root = Path(__file__).resolve().parents[1]
    proposals = analyze_project(root)
    for p in proposals:
        assert "test_" not in Path(p.file_path).name
        assert ".venv" not in p.file_path
        assert "__pycache__" not in p.file_path


def test_analyze_project_excludes_node_module():
    """node_windows/node.py should also be analyzed (it's source, not test)."""
    root = Path(__file__).resolve().parents[1]
    proposals = analyze_project(root)
    node_files = [p for p in proposals if "node_windows" in p.file_path]
    # node_windows is source code — should be analyzed
    assert len(node_files) > 0


# ---------------------------------------------------------------------------
# Endpoint integration tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    with TestClient(factory()(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)) as c:
        yield c


def test_analyze_endpoint_stores_proposals(client):
    """POST /v1/self-improve/analyze should run analysis and store proposals."""
    resp = client.post('/v1/self-improve/analyze', headers=AUTH, json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["level"] == LEVEL_DRAFT
    assert data["count"] > 0
    assert isinstance(data["proposals"], list)
    for p in data["proposals"]:
        assert "id" in p
        assert "file_path" in p
        assert "category" in p
        assert "confidence" in p
        assert "risk_level" in p


def test_analyze_endpoint_requires_auth(client):
    resp = client.post('/v1/self-improve/analyze', json={})
    assert resp.status_code == 401


def test_analyze_endpoint_requires_admin(client):
    d = client.post('/v1/devices', headers=AUTH, json={'name': 'x', 'platform': 'y'}).json()
    token_hdr = {'Authorization': f'Bearer {d["token"]}'}
    resp = client.post('/v1/self-improve/analyze', headers=token_hdr, json={})
    assert resp.status_code == 403


def test_list_proposals_endpoint(client):
    """GET /v1/self-improve/proposals should return stored proposals."""
    # First run analysis to seed proposals
    client.post('/v1/self-improve/analyze', headers=AUTH, json={})
    resp = client.get('/v1/self-improve/proposals', headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0
    for p in data["proposals"]:
        assert "proposal" in p
        assert "status" in p
        assert "id" in p
        assert "created_at" in p


def test_list_proposals_filter_by_status(client):
    """GET with status=pending should only return pending proposals."""
    client.post('/v1/self-improve/analyze', headers=AUTH, json={})
    resp = client.get('/v1/self-improve/proposals', headers=AUTH, params={"status": "pending"})
    assert resp.status_code == 200
    data = resp.json()
    for p in data["proposals"]:
        assert p["status"] == "pending"


def test_apply_proposal_requires_confirmation(client):
    """Apply should reject without confirm=True."""
    client.post('/v1/self-improve/analyze', headers=AUTH, json={})
    proposals = client.get('/v1/self-improve/proposals', headers=AUTH).json()["proposals"]
    pid = proposals[0]["id"]
    # Without confirm
    resp = client.post(
        f'/v1/self-improve/proposals/{pid}/apply',
        headers=AUTH,
        json={"confirm": False},
    )
    assert resp.status_code == 400


def test_apply_proposal_materializes_patch_without_claiming_success(client):
    """Apply must not report a code change it did not make (SPEC_AUDIT R8).

    Previously this asserted 200 + status 'applied', which passed while the
    endpoint wrote nothing at all. It now returns 202 and reports
    applied=false with a reviewable patch reference.
    """
    client.post('/v1/self-improve/analyze', headers=AUTH, json={})
    proposals = client.get('/v1/self-improve/proposals', headers=AUTH).json()["proposals"]
    pid = proposals[0]["id"]
    resp = client.post(
        f'/v1/self-improve/proposals/{pid}/apply',
        headers=AUTH,
        json={"confirm": True},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["applied"] is False
    assert body["requires_review"] is True
    assert "applied_at" in body


def test_apply_proposal_twice_fails(client):
    """Re-applying a materialized proposal is a conflict, not a silent success."""
    client.post('/v1/self-improve/analyze', headers=AUTH, json={})
    proposals = client.get('/v1/self-improve/proposals', headers=AUTH).json()["proposals"]
    pid = proposals[0]["id"]
    client.post(f'/v1/self-improve/proposals/{pid}/apply', headers=AUTH, json={"confirm": True})
    resp = client.post(f'/v1/self-improve/proposals/{pid}/apply', headers=AUTH, json={"confirm": True})
    assert resp.status_code == 409


def test_reject_proposal(client):
    """Reject should update status to 'rejected'."""
    client.post('/v1/self-improve/analyze', headers=AUTH, json={})
    proposals = client.get('/v1/self-improve/proposals', headers=AUTH).json()["proposals"]
    pid = proposals[0]["id"]
    resp = client.post(
        f'/v1/self-improve/proposals/{pid}/reject',
        headers=AUTH,
        json={"note": "Not worth the risk"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert resp.json()["note"] == "Not worth the risk"


def test_reject_proposal_nonexistent(client):
    fake_id = str(UUID('00000000-0000-4000-8000-000000000000'))
    resp = client.post(
        f'/v1/self-improve/proposals/{fake_id}/reject',
        headers=AUTH,
        json={"note": "x"},
    )
    assert resp.status_code == 404


def test_apply_proposal_nonexistent(client):
    fake_id = str(UUID('00000000-0000-4000-8000-000000000000'))
    resp = client.post(
        f'/v1/self-improve/proposals/{fake_id}/apply',
        headers=AUTH,
        json={"confirm": True},
    )
    assert resp.status_code == 404


def test_audit_trail_rejected_proposals_not_reapplicable(client):
    """Rejected proposals must not be appliable; the state conflict is explicit."""
    client.post('/v1/self-improve/analyze', headers=AUTH, json={})
    proposals = client.get('/v1/self-improve/proposals', headers=AUTH).json()["proposals"]
    pid = proposals[0]["id"]
    client.post(f'/v1/self-improve/proposals/{pid}/reject', headers=AUTH, json={"note": "no"})
    resp = client.post(f'/v1/self-improve/proposals/{pid}/apply', headers=AUTH, json={"confirm": True})
    assert resp.status_code == 409
    assert 'rejected' in resp.json()['detail']


def test_no_auto_execution_property():
    """The analyze_project function NEVER applies patches — it only returns proposals."""
    import ast
    src = Path(__file__).resolve().parents[1] / "core" / "app" / "self_improve.py"
    tree = ast.parse(src.read_text())
    # Verify no subprocess calls, no file writes in the analysis functions
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr != "write_text", "analyze functions must not write files"
                assert node.func.attr != "write", "analyze functions must not write files"
            if isinstance(node.func, ast.Name):
                assert node.func.id not in ("exec", "eval"), "analyze functions must not call exec/eval"


def test_proposals_always_draft():
    """analyze_project returns proposals that are strictly drafts."""
    root = Path(__file__).resolve().parents[2] / "core"
    proposals = analyze_project(root)
    for p in proposals:
        # new_code is a suggestion, never automatically applied
        assert p.new_code is not None
        assert isinstance(p.confidence, float)
        assert p.risk_level in ("low", "medium", "high")

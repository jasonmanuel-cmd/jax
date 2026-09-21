"""JAX self-improvement: static analysis + safe patch proposals.

All proposals are DRAFT-ONLY (Level-2 permission).  Nothing is auto-applied.
Analysis covers: unused imports, unreachable code, complexity, missing docstrings,
magic numbers, and security patterns.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Proposal data model
# ---------------------------------------------------------------------------

LEVEL_DRAFT = 2  # Level-2: proposals only, explicit confirmation required.


@dataclass
class Proposal:
    """A single improvement suggestion."""

    file_path: str
    old_code: str
    new_code: str
    reason: str
    category: str  # unused_import | unreachable | complexity | missing_docstring | magic_number | security
    confidence: float  # 0.0 – 1.0
    risk_level: str  # low | medium | high

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "old_code": self.old_code,
            "new_code": self.new_code,
            "reason": self.reason,
            "category": self.category,
            "confidence": round(self.confidence, 2),
            "risk_level": self.risk_level,
        }


# ---------------------------------------------------------------------------
# AST-based analyzers
# ---------------------------------------------------------------------------

_MAGIC_NUMBER_EXEMPT = {0, 1, -1, 2, 10, 100, 1000, 60, 256, 512, 1024, 4096}
_SECURITY_PATTERNS = [
    (re.compile(r"""\beval\s*\("""), "unsafe_eval", "eval() can execute arbitrary code"),
    (re.compile(r"""\bexec\s*\("""), "unsafe_exec", "exec() can execute arbitrary code"),
    (re.compile(r"""(?i)(password|secret|api_key|token)\s*=\s*['"][^'"]{8,}['"]"""),
     "hardcoded_secret", "Possible hardcoded secret"),
    (re.compile(r"""f["'].*\{.*\}.*['"].*%s|%\s*\("""),
     "potential_format_string_injection", "Unsafe string formatting in a security-sensitive context"),
    (re.compile(r"""(?i)subprocess\..*shell\s*=\s*True"""),
     "shell_injection_risk", "subprocess with shell=True"),
]


def _source_lines(source: str, node: ast.AST) -> str:
    """Extract source text for an AST node."""
    lines = source.splitlines()
    if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        return "\n".join(lines[start:end])
    return lines[node.lineno - 1] if hasattr(node, "lineno") else ""


def _find_unused_imports(tree: ast.Module, source: str) -> list[Proposal]:
    """Detect imports that are never referenced in the module body."""
    proposals: list[Proposal] = []
    imported_names: dict[str, ast.alias] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                imported_names[name] = alias
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue  # __future__ imports affect parsing, not runtime usage
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                imported_names[name] = alias

    # Walk all Name nodes (except the import statements themselves)
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            # Track the root of attribute chains (e.g., `os.path` → `os`)
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                used_names.add(root.id)

    for name, alias_node in imported_names.items():
        if name not in used_names and name != "_":
            line_src = _source_lines(source, alias_node)
            proposals.append(Proposal(
                file_path="<analysis>",
                old_code=line_src,
                new_code="",
                reason=f"Import '{name}' is never used in this module.",
                category="unused_import",
                confidence=0.95,
                risk_level="low",
            ))
    return proposals


def _find_unreachable_code(tree: ast.Module, source: str) -> list[Proposal]:
    """Detect code after bare return/break/continue/raise."""
    proposals: list[Proposal] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            for i, stmt in enumerate(body[:-1]):
                if isinstance(stmt, ast.Return) and stmt.value is None:
                    next_stmt = body[i + 1]
                    # Check if there's a comment or docstring after return
                    if not isinstance(next_stmt, (ast.Expr,)):
                        proposals.append(Proposal(
                            file_path="<analysis>",
                            old_code=_source_lines(source, next_stmt),
                            new_code="",
                            reason=f"Unreachable code after bare return in '{node.name}'.",
                            category="unreachable",
                            confidence=0.85,
                            risk_level="low",
                        ))
    return proposals


def _find_missing_docstrings(tree: ast.Module, source: str) -> list[Proposal]:
    """Flag public functions/classes without docstrings."""
    proposals: list[Proposal] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = getattr(node, "name", "")
            # Skip private/dunder and test functions
            if name.startswith("_") or name.startswith("test_"):
                continue
            docstring = ast.get_docstring(node)
            if not docstring:
                proposals.append(Proposal(
                    file_path="<analysis>",
                    old_code=f"def {name}(...):",
                    new_code=f'def {name}(...):\n    """<description>."""',
                    reason=f"Public function/class '{name}' is missing a docstring.",
                    category="missing_docstring",
                    confidence=1.0,
                    risk_level="low",
                ))
    return proposals


def _find_magic_numbers(tree: ast.Module, source: str) -> list[Proposal]:
    """Detect numeric literals that aren't in the exempt set."""
    proposals: list[Proposal] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            val = node.value
            if val in _MAGIC_NUMBER_EXEMPT:
                continue
            # Skip constants that are clearly named (assigned to an UPPER_CASE name)
            parent = getattr(node, "_parent", None)
            if isinstance(parent, ast.Assign):
                targets = parent.targets
                if targets and isinstance(targets[0], ast.Name) and targets[0].id.isupper():
                    continue
            proposals.append(Proposal(
                file_path="<analysis>",
                old_code=str(val),
                new_code=f"_{('VAL_%d' % val) if isinstance(val, int) else 'VAL'} = {val}",
                reason=f"Magic number {val} should be a named constant.",
                category="magic_number",
                confidence=0.6,
                risk_level="low",
            ))
    return proposals


def _complexity(node: ast.AST) -> int:
    """Cyclomatic complexity: branches + 1."""
    branches = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                              ast.BoolOp, ast.IfExp, ast.comprehension)):
            branches += 1
    return branches + 1


def _find_complex_functions(tree: ast.Module, source: str) -> list[Proposal]:
    """Flag functions whose cyclomatic complexity exceeds a threshold."""
    threshold = 10
    proposals: list[Proposal] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cx = _complexity(node)
            if cx > threshold:
                proposals.append(Proposal(
                    file_path="<analysis>",
                    old_code=f"def {node.name}(...):",
                    new_code="# Consider splitting into smaller helper functions",
                    reason=f"Function '{node.name}' has cyclomatic complexity {cx} (threshold {threshold}).",
                    category="complexity",
                    confidence=0.9,
                    risk_level="medium",
                ))
    return proposals


# ---------------------------------------------------------------------------
# Security scanner (text + regex based)
# ---------------------------------------------------------------------------

def _scan_security(source: str, file_path: str) -> list[Proposal]:
    """Regex-based security pattern scan."""
    proposals: list[Proposal] = []
    lines = source.splitlines()
    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        for pattern, tag, msg in _SECURITY_PATTERNS:
            if pattern.search(line):
                proposals.append(Proposal(
                    file_path=file_path,
                    old_code=line.rstrip(),
                    new_code="# Review: " + line.rstrip(),
                    reason=f"[{tag}] {msg} (line {i})",
                    category="security",
                    confidence=0.7,
                    risk_level="high",
                ))
    return proposals


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def analyze_file(file_path: str | Path, source: str | None = None) -> list[Proposal]:
    """Run all analyzers on a single Python source file."""
    path = Path(file_path)
    if source is None:
        source = path.read_text(encoding="utf-8")

    tree = ast.parse(source, filename=str(path))
    proposals: list[Proposal] = []

    # Wire up parent links for magic-number detection
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            setattr(child, "_parent", node)

    proposals.extend(_find_unused_imports(tree, source))
    proposals.extend(_find_unreachable_code(tree, source))
    proposals.extend(_find_missing_docstrings(tree, source))
    proposals.extend(_find_magic_numbers(tree, source))
    proposals.extend(_find_complex_functions(tree, source))
    proposals.extend(_scan_security(source, str(path)))

    # Stamp real file paths
    for p in proposals:
        if p.file_path == "<analysis>":
            p.file_path = str(path)

    return proposals


def analyze_project(root: str | Path) -> list[Proposal]:
    """Run analysis on every .py file under root (excluding .venv, __pycache__, tests)."""
    root = Path(root)
    proposals: list[Proposal] = []
    exclude_dirs = {".venv", "__pycache__", ".git", "node_modules"}
    exclude_files_regex = re.compile(r"^test_")

    for py_file in sorted(root.rglob("*.py")):
        rel = py_file.relative_to(root)
        parts = rel.parts
        if any(p in exclude_dirs for p in parts):
            continue
        if exclude_files_regex.match(py_file.name):
            continue
        try:
            proposals.extend(analyze_file(py_file))
        except (SyntaxError, UnicodeDecodeError) as exc:
            proposals.append(Proposal(
                file_path=str(py_file),
                old_code="",
                new_code="",
                reason=f"Could not parse: {exc}",
                category="security",
                confidence=1.0,
                risk_level="high",
            ))

    return proposals


# ---------------------------------------------------------------------------
# Proposal persistence helpers (JSON serialisation for DB layer)
# ---------------------------------------------------------------------------

def proposal_to_json(p: Proposal) -> str:
    """Serialize a Proposal to JSON for storage."""
    return json.dumps(p.to_dict(), ensure_ascii=False)


def proposal_from_json(raw: str) -> dict:
    """Deserialize stored JSON back to a dict (the DB layer handles ORM mapping)."""
    return json.loads(raw)

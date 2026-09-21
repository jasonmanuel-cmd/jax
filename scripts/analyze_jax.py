#!/usr/bin/env python3
"""analyze_jax.py — Run JAX self-improvement analysis from the CLI.

Usage:
    python scripts/analyze_jax.py                     # Analyze the whole project
    python scripts/analyze_jax.py --file core/app/main.py  # Analyze one file
    python scripts/analyze_jax.py --category security       # Filter by category
    python scripts/analyze_jax.py --min-confidence 0.8      # Filter by confidence
    python scripts/analyze_jax.py --json                   # Output as JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path so `core` is importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.app.self_improve import analyze_file, analyze_project, proposal_to_json


def main() -> int:
    parser = argparse.ArgumentParser(description="JAX self-improvement analyzer (Level-2 drafts only)")
    parser.add_argument("--file", type=str, help="Analyze a single file instead of the full project")
    parser.add_argument("--category", type=str, help="Filter proposals by category")
    parser.add_argument("--min-confidence", type=float, default=0.0, help="Minimum confidence threshold (0-1)")
    parser.add_argument("--risk", type=str, choices=["low", "medium", "high"], help="Filter by risk level")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output proposals as JSON")
    args = parser.parse_args()

    if args.file:
        path = Path(args.file)
        if not path.is_absolute():
            path = ROOT / path
        proposals = analyze_file(path)
    else:
        proposals = analyze_project(ROOT)

    # Apply filters
    if args.category:
        proposals = [p for p in proposals if p.category == args.category]
    if args.risk:
        proposals = [p for p in proposals if p.risk_level == args.risk]
    proposals = [p for p in proposals if p.confidence >= args.min_confidence]

    if not proposals:
        print("No proposals found matching the criteria.", file=sys.stderr)
        return 0

    if args.as_json:
        output = json.dumps(
            [json.loads(proposal_to_json(p)) for p in proposals],
            indent=2, ensure_ascii=False,
        )
        print(output)
    else:
        print(f"\n{'='*70}")
        print(f"  JAX Self-Improvement Report  (Level-2: drafts only, NOT auto-applied)")
        print(f"  {len(proposals)} proposal(s) found")
        print(f"{'='*70}\n")
        for i, p in enumerate(proposals, 1):
            print(f"  [{i}] {p.category.upper()} — {p.file_path}")
            print(f"      Confidence: {p.confidence:.0%}  |  Risk: {p.risk_level}")
            print(f"      Reason: {p.reason}")
            if p.old_code:
                print(f"      Old: {p.old_code[:80]}")
            if p.new_code:
                print(f"      New: {p.new_code[:80]}")
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

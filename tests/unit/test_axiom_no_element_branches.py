"""Static AST check enforcing Axiom A2: no hardcoded element symbol branches in src/."""

from __future__ import annotations

import ast
from pathlib import Path

from ase.data import chemical_symbols

ELEMENT_SET = set(chemical_symbols[1:])
SRC_DIR = Path(__file__).resolve().parents[2] / "src"


def _has_element_comparison(node: ast.Compare) -> list[str]:
    found: list[str] = []
    values = [node.left, *node.comparators]
    for item in values:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            if item.value in ELEMENT_SET:
                found.append(item.value)
        elif isinstance(item, (ast.Set, ast.List, ast.Tuple)):
            for elt in item.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    if elt.value in ELEMENT_SET:
                        found.append(elt.value)
    return found


def test_no_hardcoded_element_branches_in_src() -> None:
    violations: list[str] = []
    for py_file in sorted(SRC_DIR.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                syms = _has_element_comparison(node)
                if syms:
                    violations.append(f"{py_file}:{node.lineno} compares element(s) {syms}")
    assert violations == [], "Axiom A2 violation(s):\n" + "\n".join(violations)

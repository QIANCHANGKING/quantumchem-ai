"""Evaluation script for the 50-instruction Chinese NL-to-ResearchRequest benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from qcai.ai import ParsedIntent, parse_natural_language_intent


@dataclass(frozen=True)
class EvalMetrics:
    """Evaluation accuracy metrics across the 50-instruction benchmark."""

    total: int
    passed: int
    accuracy: float
    failures: list[str]


def _normalize_comp(comp: dict[str, Any]) -> dict[str, int | tuple[int, int]]:
    out: dict[str, int | tuple[int, int]] = {}
    for k, v in comp.items():
        if isinstance(v, list):
            out[str(k)] = (int(v[0]), int(v[1]))
        else:
            out[str(k)] = int(v)
    return out


def score_intent(case: dict[str, Any], intent: ParsedIntent) -> tuple[bool, str]:
    """Compare a single ParsedIntent against benchmark ground truth."""
    exp_clar = bool(case["needs_clarification"])
    if intent.needs_clarification != exp_clar:
        return False, f"clarification mismatch: got {intent.needs_clarification}, exp {exp_clar}"
    if exp_clar:
        ok = bool(intent.clarification_question and intent.clarification_question.strip())
        return (ok, "" if ok else "missing clarification_question")

    if intent.request is None:
        return False, "request is None when needs_clarification=False"

    exp = case["expected"]
    exp_comp = _normalize_comp(exp["composition"])
    if intent.request.composition != exp_comp:
        return False, f"composition mismatch: got {intent.request.composition}, exp {exp_comp}"
    if not set(exp["recipes"]).issubset(set(intent.request.recipes)):
        return False, f"recipes mismatch: got {intent.request.recipes}, exp {exp['recipes']}"
    if intent.request.accuracy != exp["accuracy"]:
        return False, f"accuracy mismatch: got {intent.request.accuracy}, exp {exp['accuracy']}"
    if "time_budget_hours" in exp:
        if intent.request.time_budget_hours != exp["time_budget_hours"]:
            return (
                False,
                f"budget mismatch: got {intent.request.time_budget_hours}, exp {exp['time_budget_hours']}",
            )
    if "charges" in exp and intent.request.charges != exp["charges"]:
        return False, f"charges mismatch: got {intent.request.charges}, exp {exp['charges']}"
    return True, ""


def run_eval(
    instructions_path: Path,
    *,
    api_key: str | None = None,
    model: Any = None,
) -> EvalMetrics:
    """Evaluate all cases in instructions.yaml and return EvalMetrics."""
    cases = yaml.safe_load(instructions_path.read_text(encoding="utf-8"))["instructions"]
    passed = 0
    failures: list[str] = []
    for case in cases:
        intent = parse_natural_language_intent(case["text"], api_key=api_key, model=model)
        ok, reason = score_intent(case, intent)
        if ok:
            passed += 1
        else:
            failures.append(f"Case {case['id']}: {reason}")
    total = len(cases)
    return EvalMetrics(
        total=total,
        passed=passed,
        accuracy=(passed / total) if total else 0.0,
        failures=failures,
    )

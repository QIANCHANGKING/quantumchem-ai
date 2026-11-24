"""Numerical hallucination guard attached to pydantic-ai output_validator (Section 6.10)."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from qcai.core.physics import HA_TO_EV

_TOKEN_CLEAN_RE = re.compile(
    r"\b(?:def2-[A-Za-z0-9()+*-]+|6-31[0-9]*G[*()+pd,]*|PBE0|PBE1PBE|PBEPBE|TPSSh|B3LYP|M06-?2X|wB97XD|D3BJ|GD3BJ|L\d{3,4}|S\d)\b"
)
_FORMULA_SUB_RE = re.compile(r"\b(?:[A-Z][a-z]?(?:[₀-₉]+|\d+))+\b")
_LIST_BULLET_RE = re.compile(r"(?m)^\s*\d+[.)]\s+")
_NUM_RE = re.compile(r"(?<![A-Za-z_])([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")

# Common unit conversion multipliers (Hartree <-> eV <-> kcal/mol <-> kJ/mol, % <-> fraction)
_UNIT_SCALES: tuple[float, ...] = (
    1.0,
    HA_TO_EV,
    1.0 / HA_TO_EV,
    627.509474,  # Ha -> kcal/mol
    1.0 / 627.509474,
    2625.49964,  # Ha -> kJ/mol
    1.0 / 2625.49964,
    100.0,  # fraction -> %
    0.01,  # % -> fraction
)


@dataclass(frozen=True)
class GuardReport:
    """Verification outcome of checking LLM numeric claims against fact numbers."""

    grounded: bool
    checked_numbers: list[float]
    unverified_numbers: list[float]


def collect_fact_numbers(obj: Any) -> list[float]:
    """Recursively collect all numeric values (and unit-converted equivalents) from facts."""
    raw: list[float] = []

    def _walk(item: Any) -> None:
        if isinstance(item, bool):
            return
        if isinstance(item, (int, float)):
            val = float(item)
            if math.isfinite(val):
                raw.append(val)
        elif isinstance(item, dict):
            for v in item.values():
                _walk(v)
        elif isinstance(item, (list, tuple, set)):
            for v in item:
                _walk(v)
        elif hasattr(item, "model_dump"):
            _walk(item.model_dump())

    _walk(obj)
    # Include unit-converted equivalents and count-based numbers
    expanded: set[float] = set()
    for v in raw:
        for scale in _UNIT_SCALES:
            expanded.add(v * scale)
            expanded.add(-v * scale)
    return sorted(expanded)


def extract_numbers_from_text(text: str) -> list[float]:
    """Extract quantitative numeric claims while ignoring basis names, error codes, and list bullets."""
    cleaned = _LIST_BULLET_RE.sub(" ", text)
    cleaned = _TOKEN_CLEAN_RE.sub(" ", cleaned)
    cleaned = _FORMULA_SUB_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("S²", "S2").replace("<S2>", " ").replace("Δ₂E", " ")
    nums: list[float] = []
    for m in _NUM_RE.finditer(cleaned):
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        if math.isfinite(val):
            nums.append(val)
    return nums


def _matches_any_fact(candidate: float, facts: Iterable[float]) -> bool:
    # Tolerance handles rounding to 1-6 decimal places and slight unit factor variation
    abs_tol = 0.015 if abs(candidate) < 20.0 else max(0.05, 0.005 * abs(candidate))
    for f in facts:
        if math.isclose(candidate, f, rel_tol=5e-3, abs_tol=abs_tol):
            return True
    return False


def verify_grounded_numbers(text: str, fact_source: Any) -> GuardReport:
    """Verify every quantitative number in `text` is grounded in `fact_source`."""
    fact_nums = (
        list(fact_source)
        if isinstance(fact_source, list) and all(isinstance(x, (int, float)) for x in fact_source)
        else collect_fact_numbers(fact_source)
    )
    candidates = extract_numbers_from_text(text)
    unverified = [c for c in candidates if not _matches_any_fact(c, fact_nums)]
    return GuardReport(
        grounded=len(unverified) == 0,
        checked_numbers=candidates,
        unverified_numbers=unverified,
    )

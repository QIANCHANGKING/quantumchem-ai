"""Empirical job cost estimator and time-budget adjustment (Section 6.2)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pymatgen.core.periodic_table import Element

from qcai.core.models import Decision


@dataclass(frozen=True)
class CalibratedCostModel:
    """Empirical job cost model calibrated via least squares on completed jobs."""

    scale_factor: float = 1.0
    sample_count: int = 0

    def predict_core_hours(self, n_bf: int, tasks: list[str], *, mult: int = 1) -> float:
        raw = estimate_single_job_core_hours(n_bf, tasks, mult=mult)
        return max(0.01, round(raw * self.scale_factor, 3))


def calibrate_cost_model(
    observations: list[tuple[int, list[str], int, float]],
) -> CalibratedCostModel:
    """Fit a multiplicative calibration factor using numpy least squares.

    Each observation is `(n_bf, tasks, multiplicity, actual_core_hours)`.
    """
    if not observations:
        return CalibratedCostModel(scale_factor=1.0, sample_count=0)

    preds = np.array(
        [
            estimate_single_job_core_hours(n_bf, tasks, mult=mult)
            for n_bf, tasks, mult, _ in observations
        ],
        dtype=float,
    )
    actuals = np.array([max(0.001, float(obs[3])) for obs in observations], dtype=float)
    mask = preds > 1e-6
    if not np.any(mask):
        return CalibratedCostModel(scale_factor=1.0, sample_count=len(observations))

    x = preds[mask][:, None]
    y = actuals[mask]
    coeff, *_ = np.linalg.lstsq(x, y, rcond=None)
    scale = float(np.clip(coeff[0], 0.1, 20.0))
    return CalibratedCostModel(scale_factor=round(scale, 4), sample_count=int(np.sum(mask)))


def estimate_basis_functions(stoichiometry: dict[str, int], basis: str | None) -> int:
    """Estimate total contracted Gaussian basis functions from periodic-table rows."""
    if not basis:
        return 0
    is_tz = "tz" in basis.lower() or "qz" in basis.lower()
    total = 0
    for sym, count in stoichiometry.items():
        el = Element(sym)
        if el.row == 1:
            per_atom = 14 if is_tz else 5
        elif el.row <= 3:
            per_atom = 30 if is_tz else 14
        elif el.is_transition_metal or el.is_lanthanoid or el.is_actinoid:
            per_atom = 42 if is_tz else 24
        else:
            per_atom = 36 if is_tz else 18
        total += count * per_atom
    return total


def estimate_single_job_core_hours(n_bf: int, tasks: list[str], *, mult: int = 1) -> float:
    """Rough initial empirical core-hour estimate scaling as O(N_bf^3)."""
    if n_bf <= 0:
        return 0.05
    base = 0.08 * (n_bf / 100.0) ** 3
    factor = 0.0
    for task in tasks:
        if task == "sp":
            factor += 1.0
        elif task == "opt":
            factor += 8.0
        elif task == "freq":
            factor += 4.0
        elif task == "stable":
            factor += 2.0
    factor = max(factor, 1.0)
    spin_factor = 1.6 if mult > 1 else 1.0
    return max(0.02, round(base * factor * spin_factor, 3))


def fit_to_budget(
    *,
    time_budget_hours: float | None,
    estimated_core_hours: float,
    candidate_k: int,
    mult_cap: int,
    nominal_cores: int = 16,
) -> tuple[int, int, Decision | None]:
    """Scale down candidate_k and mult_cap when wall-time budget would be exceeded."""
    if time_budget_hours is None or time_budget_hours <= 0:
        return candidate_k, mult_cap, None

    budget_core_hours = time_budget_hours * nominal_cores
    if estimated_core_hours <= budget_core_hours:
        return candidate_k, mult_cap, None

    ratio = budget_core_hours / max(estimated_core_hours, 1e-6)
    new_k = max(3, min(candidate_k, int(round(candidate_k * ratio))))
    new_mult_cap = mult_cap
    if ratio < 0.5:
        new_mult_cap = max(4, int(round(mult_cap * max(0.5, ratio))))

    decision = Decision(
        key="budget_adjustment",
        value={"candidate_k": new_k, "max_multiplicity_cap": new_mult_cap},
        reason=(
            f"预估总核时 {estimated_core_hours:.1f} core·h 超出预算 "
            f"({time_budget_hours:.1f} h × {nominal_cores} 核 = {budget_core_hours:.1f} core·h)，"
            f"自动收缩候选数 K={candidate_k}→{new_k}、多重度上限={mult_cap}→{new_mult_cap}"
        ),
        source_rule="cost_model.budget_fit",
    )
    return new_k, new_mult_cap, decision

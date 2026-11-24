"""Spin and magnetism inductive functions (Section 5.6)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from qcai.core.models import CalcResult
from qcai.core.physics import (
    ideal_s_squared,
    is_spin_contaminated,
    total_magnetic_moment_mu_b,
)


def spin_localization(
    spins: list[float],
    symbols: list[str],
    target_indices: list[int] | None = None,
) -> float | None:
    """Compute spin localization fraction f_D = rho^s_D / sum_i rho^s_i (Section 5.6).

    If target_indices is None, automatically targets minority-element atoms (dopants).
    """
    if len(spins) != len(symbols) or not spins:
        return None

    total_spin = sum(spins)
    if abs(total_spin) < 1e-12:
        return None

    if target_indices is None:
        counts = Counter(symbols)
        if len(counts) <= 1:
            return None
        min_cnt = min(counts.values())
        indices = [i for i, sym in enumerate(symbols) if counts[sym] == min_cnt]
    else:
        indices = target_indices

    target_spin = sum(spins[i] for i in indices)
    return float(target_spin / total_spin)


def select_best_spins(spins_dict: dict[str, list[float]]) -> tuple[str, list[float]] | None:
    """Pick preferred atomic spin population method (hirshfeld > adch > mulliken)."""
    for key in ("hirshfeld", "adch", "mulliken"):
        if key in spins_dict and spins_dict[key]:
            return key, spins_dict[key]
    for key, vals in spins_dict.items():
        if vals:
            return key, vals
    return None


def summarize_magnetism(result: CalcResult) -> dict[str, Any]:
    """Summarize magnetic moment, <S^2> contamination, and spin localization."""
    mult = result.state.multiplicity
    mu_b = total_magnetic_moment_mu_b(mult)
    ideal_s2 = ideal_s_squared(mult)
    ref_s2 = result.s2_after if result.s2_after is not None else result.s2_before
    contaminated = is_spin_contaminated(ref_s2, mult) if ref_s2 is not None else False

    picked = select_best_spins(result.spins)
    spin_loc: float | None = None
    spin_method: str | None = None
    atomic_spins: list[float] = []
    if picked is not None and result.final_geometry is not None:
        spin_method, atomic_spins = picked
        spin_loc = spin_localization(atomic_spins, result.final_geometry.symbols)

    return {
        "multiplicity": mult,
        "magnetic_moment_mu_b": mu_b,
        "ideal_s2": ideal_s2,
        "s2_before": result.s2_before,
        "s2_after": result.s2_after,
        "spin_contaminated": contaminated,
        "spin_method": spin_method,
        "atomic_spins": atomic_spins,
        "spin_localization": spin_loc,
    }

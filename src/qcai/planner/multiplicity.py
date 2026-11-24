"""Spin multiplicity scan sequence derivation (Section 5.2)."""

from __future__ import annotations

from qcai.core.models import Decision
from qcai.core.physics import (
    atomic_ground_state_multiplicity,
    is_valid_parity,
    total_electrons,
)
from qcai.knowledge import load_rule_yaml


def derive_multiplicity_candidates(
    stoichiometry: dict[str, int],
    charge: int,
    *,
    has_transition_metal: bool = False,
    user_cap: int | None = None,
) -> tuple[list[int], Decision]:
    """Derive adaptive multiplicity scan sequence for a given stoichiometry and charge."""
    cfg = load_rule_yaml("multiplicity.yaml")
    defaults = cfg["defaults"]
    min_states = int(defaults["min_states"])
    default_cap = (
        int(defaults["transition_metal_cap"])
        if has_transition_metal
        else int(defaults["main_group_cap"])
    )
    cap_limit = user_cap if user_cap is not None else default_cap

    symbols = [el for el, count in stoichiometry.items() for _ in range(count)]
    n_elec = total_electrons(symbols, charge)
    if n_elec <= 0:
        raise ValueError(
            f"Non-positive electron count ({n_elec}) for {stoichiometry} at charge={charge}"
        )

    atomic_unpaired_sum = sum(
        count * max(0, atomic_ground_state_multiplicity(el) - 1)
        for el, count in stoichiometry.items()
    )
    m_max = min(atomic_unpaired_sum + 1, cap_limit)
    start = 1 if n_elec % 2 == 0 else 2
    candidates = [m for m in range(start, m_max + 1, 2) if is_valid_parity(n_elec, m)]

    # Ensure at least min_states valid multiplicities when electron count permits
    next_m = (candidates[-1] + 2) if candidates else start
    while len(candidates) < min_states and next_m - 1 <= n_elec:
        if is_valid_parity(n_elec, next_m):
            candidates.append(next_m)
        next_m += 2

    if not candidates:
        candidates = [start]

    rule_meta = cfg["rules"][0]
    decision = Decision(
        key="multiplicity_scan",
        value=candidates,
        reason=(
            f"总电子数 N={n_elec}，原子未成对电子数上限={atomic_unpaired_sum}，"
            f"自适应扫描序列 {candidates}（连续 {defaults['consecutive_high_states']} 态高出 "
            f"{defaults['early_stop_ev']} eV 提前停止）"
        ),
        source_rule=str(rule_meta["id"]),
    )
    return candidates, decision

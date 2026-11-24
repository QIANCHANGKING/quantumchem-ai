"""Charge state derivation from research recipes (Section 5.4)."""

from __future__ import annotations

from typing import Literal

from qcai.core.models import Decision
from qcai.knowledge import load_rule_yaml


def derive_charge_plan(
    recipes: list[str],
    request_charges: list[int] | Literal["auto"],
) -> tuple[list[int], list[str], Decision]:
    """Derive target charge states and ionic tasks from recipes or explicit charges."""
    cfg = load_rule_yaml("charges.yaml")["recipe_charges"]

    derived_charges: list[int] = []
    ionic_tasks: list[str] = []
    reasons: list[str] = []

    for recipe in recipes:
        if recipe not in cfg:
            raise ValueError(f"Unknown research recipe: {recipe!r}")
        entry = cfg[recipe]
        for q in entry["charges"]:
            if int(q) not in derived_charges:
                derived_charges.append(int(q))
        for task in entry.get("ionic_tasks", []):
            if str(task) not in ionic_tasks:
                ionic_tasks.append(str(task))
        reasons.append(str(entry["reason"]))

    if not derived_charges:
        derived_charges = [0]

    if request_charges != "auto":
        charges = list(dict.fromkeys(int(q) for q in request_charges))
        decision = Decision(
            key="charge_states",
            value=charges,
            reason=f"用户显式指定电荷态 {charges}",
            source_rule="user.charges",
            overridden=True,
        )
        return charges, ionic_tasks, decision

    decision = Decision(
        key="charge_states",
        value=derived_charges,
        reason="；".join(dict.fromkeys(reasons)),
        source_rule="charges.recipe_charges",
    )
    return derived_charges, ionic_tasks, decision

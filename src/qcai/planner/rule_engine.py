"""YAML rule engine producing auditable Decision objects (Axioms A2, A3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pymatgen.core.periodic_table import Element

from qcai.core.models import Decision, ResearchRequest
from qcai.knowledge import load_rule_yaml


@dataclass(frozen=True)
class SystemFeatures:
    """Element-agnostic system properties computed solely from pymatgen.Element."""

    elements: list[str]
    min_atoms: int
    max_atoms: int
    has_transition_metal: bool
    has_f_block: bool
    has_heavy_ecp: bool
    is_multi_element: bool


def extract_system_features(request: ResearchRequest) -> SystemFeatures:
    """Derive system features from composition without element-specific branches."""
    elements = list(request.composition.keys())
    if not elements:
        raise ValueError("ResearchRequest.composition cannot be empty")

    min_atoms = 0
    max_atoms = 0
    for count in request.composition.values():
        if isinstance(count, tuple):
            lo, hi = count
            if lo < 0 or hi < lo:
                raise ValueError(f"Invalid size range: {count}")
            min_atoms += lo
            max_atoms += hi
        else:
            if count < 0:
                raise ValueError(f"Invalid atom count: {count}")
            min_atoms += count
            max_atoms += count

    if max_atoms <= 0:
        raise ValueError("Total atom count must be positive")

    pmg_els = [Element(sym) for sym in elements]
    return SystemFeatures(
        elements=elements,
        min_atoms=min_atoms,
        max_atoms=max_atoms,
        has_transition_metal=any(el.is_transition_metal for el in pmg_els),
        has_f_block=any(el.is_lanthanoid or el.is_actinoid for el in pmg_els),
        has_heavy_ecp=any(el.Z > 36 for el in pmg_els),
        is_multi_element=len(elements) > 1,
    )


def _matches_when(when: dict[str, Any], features: SystemFeatures, state: dict[str, Any]) -> bool:
    for cond_key, cond_val in when.items():
        if cond_key == "always":
            if not cond_val:
                return False
        elif cond_key == "has_transition_metal":
            if features.has_transition_metal != bool(cond_val):
                return False
        elif cond_key == "has_f_block":
            if features.has_f_block != bool(cond_val):
                return False
        elif cond_key == "max_atoms_gt":
            if not (features.max_atoms > int(cond_val)):
                return False
        elif cond_key == "has_refinement":
            has_ref = state.get("refinement_functional") is not None
            if has_ref != bool(cond_val):
                return False
        else:
            raise ValueError(f"Unsupported rule condition key: {cond_key!r}")
    return True


def evaluate_theory_rules(
    request: ResearchRequest, features: SystemFeatures
) -> tuple[dict[str, Any], list[Decision]]:
    """Evaluate theory_level.yaml rules and apply user overrides."""
    cfg = load_rule_yaml("theory_level.yaml")
    tiers = cfg["accuracy_tiers"]
    if request.accuracy not in tiers:
        raise ValueError(f"Unknown accuracy tier: {request.accuracy!r}")
    tier = tiers[request.accuracy]

    state: dict[str, Any] = {
        "search_method": tier["search_method"],
        "screening_functional": tier["screening_functional"],
        "screening_basis": tier["screening_basis"],
        "screening_dispersion": tier["screening_dispersion"],
        "refinement_functional": tier["refinement_functional"],
        "refinement_basis": tier["refinement_basis"],
        "refinement_dispersion": tier["refinement_dispersion"],
        "refinement_tasks": list(tier["refinement_tasks"]),
        "candidate_k": int(tier["default_k"]),
        "scf_strategy": "default",
        "nosymm": True,
        "enable_stability_check": "stable" in tier["refinement_tasks"],
        "f_block_warning": False,
        "max_multiplicity_cap": None,
    }

    decisions: list[Decision] = [
        Decision(
            key="accuracy_tier",
            value={
                "screening": f"{state['screening_functional']}/{state['screening_basis']}",
                "refinement": (
                    f"{state['refinement_functional']}/{state['refinement_basis']}"
                    if state["refinement_functional"]
                    else None
                ),
            },
            reason=str(tier["reason"]),
            source_rule=f"theory_level.accuracy_tiers.{request.accuracy}",
        ),
        Decision(
            key="candidate_k",
            value=state["candidate_k"],
            reason=f"{request.accuracy} 档位默认保留能量窗口内前 {state['candidate_k']} 个候选异构体",
            source_rule=f"theory_level.accuracy_tiers.{request.accuracy}",
        ),
    ]

    if features.has_heavy_ecp:
        decisions.append(
            Decision(
                key="ecp_handling",
                value="auto_def2_ecp",
                reason="含 Z > 36 元素，def2 系列基组自动启用对应赝势 (ECP)",
                source_rule="theory_level.def2_builtin_ecp",
            )
        )

    for rule in cfg.get("rules", []):
        when = rule.get("when", {})
        if not _matches_when(when, features, state):
            continue
        rule_id = str(rule["id"])
        reason = str(rule["reason"])
        for action_key, action_val in rule.get("then", {}).items():
            if action_key == "candidate_k_cap":
                new_k = min(int(state["candidate_k"]), int(action_val))
                state["candidate_k"] = new_k
                decisions.append(
                    Decision(
                        key="candidate_k",
                        value=new_k,
                        reason=reason,
                        source_rule=rule_id,
                    )
                )
            else:
                state[action_key] = action_val
                decisions.append(
                    Decision(
                        key=action_key,
                        value=action_val,
                        reason=reason,
                        source_rule=rule_id,
                    )
                )

    # Apply explicit user overrides visibly
    applied_keys: set[str] = set()
    for dec in decisions:
        if dec.key in request.overrides:
            dec.value = request.overrides[dec.key]
            dec.overridden = True
            dec.reason = f"[用户覆盖] {dec.reason}"
            state[dec.key] = request.overrides[dec.key]
            applied_keys.add(dec.key)

    for ov_key, ov_val in request.overrides.items():
        if ov_key not in applied_keys:
            state[ov_key] = ov_val
            decisions.append(
                Decision(
                    key=ov_key,
                    value=ov_val,
                    reason="用户显式覆盖设置",
                    source_rule="user.override",
                    overridden=True,
                )
            )

    return state, decisions

"""Research planner: ResearchRequest -> validated CalcPlan and Markdown report."""

from __future__ import annotations

import math
from itertools import product

from pydantic import BaseModel

from qcai.core.models import (
    CalcPlan,
    CalcSpec,
    Cluster,
    ElectronicState,
    ResearchRequest,
    StagePlan,
)
from qcai.core.physics import (
    atomic_ground_state_multiplicity,
    covalent_radius,
    total_electrons,
    validate_electronic_state,
)
from qcai.knowledge import load_rule_yaml
from qcai.planner.charges import derive_charge_plan
from qcai.planner.cost_model import (
    estimate_basis_functions,
    estimate_single_job_core_hours,
    fit_to_budget,
)
from qcai.planner.multiplicity import derive_multiplicity_candidates
from qcai.planner.rule_engine import evaluate_theory_rules, extract_system_features
from qcai.programs.gaussian.writer import ensure_basis_coverage


class ReferenceJobSpec(BaseModel):
    """Reference calculation required to satisfy Axiom A4."""

    label: str
    stoichiometry: dict[str, int]
    state: ElectronicState
    calc_spec: CalcSpec


def expand_composition(
    composition: dict[str, int | tuple[int, int]],
) -> list[dict[str, int]]:
    """Expand element count ranges into concrete stoichiometries sorted by size."""
    keys = list(composition.keys())
    ranges: list[list[int]] = []
    for val in composition.values():
        if isinstance(val, tuple):
            ranges.append(list(range(val[0], val[1] + 1)))
        else:
            ranges.append([val])
    expanded: list[dict[str, int]] = []
    for combo in product(*ranges):
        stoich = {k: c for k, c in zip(keys, combo, strict=True) if c > 0}
        if stoich:
            expanded.append(stoich)
    expanded.sort(key=lambda s: sum(s.values()))
    return expanded


def stoichiometry_label(stoichiometry: dict[str, int]) -> str:
    """Format stoichiometry as compact formula label (e.g. Al12Ni)."""
    return "".join(f"{el}{n if n > 1 else ''}" for el, n in stoichiometry.items())


def validate_geometry_sanity(cluster: Cluster) -> list[str]:
    """Check for overlapping atoms (< 0.8*(ri+rj)) or isolated atoms (> 2.5*(ri+rj))."""
    errors: list[str] = []
    n = len(cluster.symbols)
    if n <= 1:
        return errors

    radii = [covalent_radius(sym) for sym in cluster.symbols]
    has_neighbor = [False] * n

    for i in range(n):
        xi, yi, zi = cluster.positions[i]
        for j in range(i + 1, n):
            xj, yj, zj = cluster.positions[j]
            dist = math.sqrt((xi - xj) ** 2 + (yi - yj) ** 2 + (zi - zj) ** 2)
            r_sum = radii[i] + radii[j]
            if dist < 0.8 * r_sum:
                errors.append(
                    f"原子 {i + 1}({cluster.symbols[i]}) 与 {j + 1}({cluster.symbols[j]}) "
                    f"间距 {dist:.3f} Å 小于共价半径之和的 0.8 倍 ({0.8 * r_sum:.3f} Å)"
                )
            if dist <= 2.5 * r_sum:
                has_neighbor[i] = True
                has_neighbor[j] = True

    for idx, connected in enumerate(has_neighbor):
        if not connected:
            errors.append(
                f"检测到孤立原子 {idx + 1}({cluster.symbols[idx]})：与所有其他原子距离均超过阈值"
            )
    return errors


def derive_reference_systems(
    stoichiometries: list[dict[str, int]],
    target_spec: CalcSpec,
) -> list[ReferenceJobSpec]:
    """Build isolated-atom and pure-host reference jobs at the exact same level (Axiom A4)."""
    refs: list[ReferenceJobSpec] = []
    seen_keys: set[tuple[tuple[tuple[str, int], ...], int, int]] = set()

    # 1. Isolated neutral atoms at ground-state multiplicity
    all_elements = list(dict.fromkeys(el for s in stoichiometries for el in s))
    atom_spec = target_spec.model_copy(update={"tasks": ["sp"]})
    for el in all_elements:
        mult = atomic_ground_state_multiplicity(el)
        key = (((el, 1),), 0, mult)
        if key not in seen_keys:
            seen_keys.add(key)
            refs.append(
                ReferenceJobSpec(
                    label=f"atom_{el}",
                    stoichiometry={el: 1},
                    state=ElectronicState(charge=0, multiplicity=mult),
                    calc_spec=atom_spec,
                )
            )

    # 2. Pure host / pure end-members for multi-element clusters (for embedding/mixing energies)
    for stoich in stoichiometries:
        if len(stoich) <= 1:
            continue
        total_n = sum(stoich.values())
        for el in stoich:
            pure_stoich = {el: total_n}
            n_elec = total_electrons([el] * total_n, 0)
            mult = 1 if n_elec % 2 == 0 else 2
            key = (((el, total_n),), 0, mult)
            if key not in seen_keys:
                seen_keys.add(key)
                refs.append(
                    ReferenceJobSpec(
                        label=f"pure_{stoichiometry_label(pure_stoich)}",
                        stoichiometry=pure_stoich,
                        state=ElectronicState(charge=0, multiplicity=mult),
                        calc_spec=target_spec.model_copy(update={"tasks": ["opt", "freq"]}),
                    )
                )
    return refs


def validate_theory_consistency(target_spec: CalcSpec, refs: list[ReferenceJobSpec]) -> None:
    """Enforce Axiom A4: reference systems must match target functional, basis, dispersion."""
    for ref in refs:
        if (
            ref.calc_spec.functional != target_spec.functional
            or ref.calc_spec.basis != target_spec.basis
            or ref.calc_spec.dispersion != target_spec.dispersion
        ):
            raise ValueError(
                f"Theory-level mismatch for reference {ref.label!r} (Axiom A4 violation)"
            )


def _collect_recipe_stages(recipes: list[str]) -> list[str]:
    cfg = load_rule_yaml("recipes.yaml")["recipes"]
    ordered = [
        "S0_reference",
        "S1_search",
        "S2_dedup",
        "S3_screen",
        "S4_refine",
        "S5_ionic",
        "S6_postprocess",
        "S7_summary",
    ]
    needed: set[str] = set()
    for r in recipes:
        if r not in cfg:
            raise ValueError(f"Unknown research recipe: {r!r}")
        needed.update(str(s) for s in cfg[r]["stages"])
    return [s for s in ordered if s in needed]


def build_plan(request: ResearchRequest) -> CalcPlan:
    """Convert a ResearchRequest into a validated CalcPlan."""
    features = extract_system_features(request)
    state, decisions = evaluate_theory_rules(request, features)
    stoichiometries = expand_composition(request.composition)

    # Validate any user-provided geometries
    if request.structures:
        for cluster in request.structures:
            geom_errors = validate_geometry_sanity(cluster)
            if geom_errors:
                raise ValueError(
                    f"Structure {cluster.label!r} failed geometry check: " + "; ".join(geom_errors)
                )

    # Validate basis coverage via basis_set_exchange (blocks if unsupported!)
    ensure_basis_coverage(str(state["screening_basis"]), features.elements)
    if state.get("refinement_basis"):
        ensure_basis_coverage(str(state["refinement_basis"]), features.elements)

    charges, ionic_tasks, charge_dec = derive_charge_plan(request.recipes, request.charges)
    decisions.append(charge_dec)

    # Derive multiplicity candidates for the representative largest stoichiometry
    rep_stoich = stoichiometries[-1]
    mult_cands, mult_dec = derive_multiplicity_candidates(
        rep_stoich,
        charges[0],
        has_transition_metal=features.has_transition_metal,
        user_cap=state.get("max_multiplicity_cap"),
    )
    decisions.append(mult_dec)

    # Target theory level (refinement if present, else screening)
    target_func = str(state["refinement_functional"] or state["screening_functional"])
    target_basis = str(state["refinement_basis"] or state["screening_basis"])
    target_disp = state["refinement_dispersion"] or state["screening_dispersion"]
    target_tasks = list(state["refinement_tasks"]) or ["opt"]

    target_spec = CalcSpec(
        functional=target_func,
        basis=target_basis,
        dispersion=target_disp,
        tasks=target_tasks,
        scf_strategy=state["scf_strategy"],
        nosymm=bool(state["nosymm"]),
    )

    refs = derive_reference_systems(stoichiometries, target_spec)
    validate_theory_consistency(target_spec, refs)

    # Validate electronic state parity across all planned stoichiometries x charges x mults
    for stoich in stoichiometries:
        syms = [el for el, n in stoich.items() for _ in range(n)]
        for q in charges:
            m_list, _ = derive_multiplicity_candidates(
                stoich,
                q,
                has_transition_metal=features.has_transition_metal,
                user_cap=state.get("max_multiplicity_cap"),
            )
            for m in m_list:
                validate_electronic_state(syms, ElectronicState(charge=q, multiplicity=m))

    # Estimate jobs & core-hours, then adjust to time_budget_hours if specified
    candidate_k = int(state["candidate_k"])
    mult_cap = int(state.get("max_multiplicity_cap") or max(mult_cands))
    n_stoich = len(stoichiometries)
    n_charges = len(charges)

    def _estimate(k_val: int, m_count: int) -> tuple[int, float]:
        n_bf_scr = estimate_basis_functions(rep_stoich, str(state["screening_basis"]))
        n_bf_ref = estimate_basis_functions(rep_stoich, state.get("refinement_basis"))
        scr_jobs = n_stoich * n_charges * k_val * m_count
        ref_jobs = n_stoich * n_charges * min(3, k_val) if state.get("refinement_functional") else 0
        ionic_jobs = n_stoich * len(ionic_tasks) * 2
        ref_sys_jobs = len(refs)
        total_jobs = len(stoichiometries) + ref_sys_jobs + scr_jobs + ref_jobs + ionic_jobs

        scr_ch = scr_jobs * estimate_single_job_core_hours(n_bf_scr, ["sp"], mult=2)
        ref_ch = ref_jobs * estimate_single_job_core_hours(n_bf_ref, target_tasks, mult=2)
        ionic_ch = ionic_jobs * estimate_single_job_core_hours(
            n_bf_ref or n_bf_scr, ["opt"], mult=2
        )
        ref_sys_ch = ref_sys_jobs * estimate_single_job_core_hours(
            max(10, n_bf_ref // 2), ["sp"], mult=2
        )
        return total_jobs, round(scr_ch + ref_ch + ionic_ch + ref_sys_ch, 2)

    est_jobs, est_core_hours = _estimate(candidate_k, len(mult_cands))
    new_k, new_cap, budget_dec = fit_to_budget(
        time_budget_hours=request.time_budget_hours,
        estimated_core_hours=est_core_hours,
        candidate_k=candidate_k,
        mult_cap=mult_cap,
    )
    if budget_dec is not None:
        decisions.append(budget_dec)
        candidate_k = new_k
        est_jobs, est_core_hours = _estimate(
            candidate_k, max(2, min(len(mult_cands), (new_cap + 1) // 2))
        )

    stage_names = _collect_recipe_stages(request.recipes)
    stage_desc_map = {
        "S0_reference": f"参考体系同水平计算（共 {len(refs)} 个，含孤立原子与纯主体）",
        "S1_search": f"{state['search_method']} 全局结构搜索（{n_stoich} 个组成）",
        "S2_dedup": f"特征值指纹 + 匹配去重，保留能量窗内前 K={candidate_k} 个异构体",
        "S3_screen": f"筛选级 DFT: {state['screening_functional']}/{state['screening_basis']} × 自适应多重度",
        "S4_refine": (
            f"精修级 DFT: {target_func}/{target_basis} ({'+'.join(target_tasks)})"
            if state.get("refinement_functional")
            else "快速档跳过精修阶段"
        ),
        "S5_ionic": f"离子态与垂直/绝热能量差 ({', '.join(ionic_tasks) or '按需'})",
        "S6_postprocess": "cubegen 格点与 Multiwfn 波函数分析",
        "S7_summary": "物理量归纳、Origin/VMD 出图与 PDF 报告",
    }
    stage_job_hints = {
        "S0_reference": len(refs),
        "S1_search": n_stoich,
        "S2_dedup": 0,
        "S3_screen": n_stoich * n_charges * candidate_k * len(mult_cands),
        "S4_refine": n_stoich * n_charges * min(3, candidate_k)
        if state.get("refinement_functional")
        else 0,
        "S5_ionic": n_stoich * len(ionic_tasks) * 2,
        "S6_postprocess": 0,
        "S7_summary": 0,
    }
    stages = [
        StagePlan(
            stage=s,
            description=stage_desc_map[s],
            estimated_jobs=stage_job_hints[s],
        )
        for s in stage_names
    ]

    return CalcPlan(
        request=request,
        decisions=decisions,
        stages=stages,
        estimated_jobs=est_jobs,
        estimated_core_hours=est_core_hours,
    )


def format_plan_markdown(plan: CalcPlan) -> str:
    """Format CalcPlan as a readable Markdown research proposal."""
    comp_str = ", ".join(
        f"{el}:{v[0]}-{v[1]}" if isinstance(v, tuple) else f"{el}:{v}"
        for el, v in plan.request.composition.items()
    )
    lines = [
        "# QuantumChem AI 计算方案书",
        "",
        f"- **体系组成**：`{comp_str}`",
        f"- **研究目标**：`{', '.join(plan.request.recipes)}`",
        f"- **精度档位**：`{plan.request.accuracy}`",
        f"- **时间预算**：{plan.request.time_budget_hours or '未限制'} h",
        f"- **预估作业数**：{plan.estimated_jobs}",
        f"- **预估计算量**：{plan.estimated_core_hours:.2f} core·h",
        "",
        "## 自动决策与理由",
        "",
        "| 决策项 | 取值 | 覆盖 | 依据规则 | 理由 |",
        "|--------|------|------|----------|------|",
    ]
    for d in plan.decisions:
        ov = "是" if d.overridden else "否"
        lines.append(f"| `{d.key}` | `{d.value}` | {ov} | `{d.source_rule}` | {d.reason} |")

    lines.extend(
        [
            "",
            "## 执行阶段",
            "",
            "| 阶段 | 预估作业数 | 说明 |",
            "|------|------------|------|",
        ]
    )
    for stg in plan.stages:
        lines.append(f"| `{stg.stage}` | {stg.estimated_jobs} | {stg.description} |")

    return "\n".join(lines) + "\n"

"""ClusterSummary and ProjectSummary aggregation with automated issue flags (Section 6.6)."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from qcai.analysis.electronic import (
    charge_transfer_by_element,
    homo_lumo_gap_ev,
    is_jellium_magic,
    minority_dopant_charge_transfer,
    valence_electron_count,
)
from qcai.analysis.energetics import (
    ade_ev,
    average_binding_energy_ha,
    embedding_energy_ha,
    fragmentation_energy_ha,
    mixing_energy_ha,
    second_order_energy_diff_ha,
    vde_ev,
)
from qcai.analysis.spin import summarize_magnetism
from qcai.core.models import CalcResult, Cluster
from qcai.core.physics import HA_TO_EV, is_spin_contaminated


class IsomerEntry(BaseModel):
    """Ranked isomer/spin-state summary row."""

    job_id: str
    label: str
    charge: int
    multiplicity: int
    energy_hartree: float
    rel_energy_ev: float
    homo_lumo_gap_ev: float | None = None
    imag_freqs: list[float] = Field(default_factory=list)
    normal_termination: bool = True
    s2_after: float | None = None
    spin_contaminated: bool = False


class IssueFlag(BaseModel):
    """Diagnostic warning or error surfaced in UI and PDF report."""

    severity: Literal["warning", "error"]
    job_id: str
    code: str
    message: str


class ClusterSummary(BaseModel):
    """Complete inductive summary for a single cluster stoichiometry/charge."""

    cluster_label: str
    stoichiometry: dict[str, int]
    charge: int
    ground_state_job_id: str
    ground_state_multiplicity: int
    ground_state_energy_hartree: float
    ground_state_geometry: Cluster | None = None
    isomers: list[IsomerEntry] = Field(default_factory=list)
    spin_ladder: list[tuple[int, float]] = Field(default_factory=list)
    binding_energy_ev_per_atom: float | None = None
    homo_lumo_gap_ev: float | None = None
    valence_electrons: int
    jellium_magic: bool
    magnetic_moment_mu_b: float
    charge_transfer_by_element: dict[str, float] = Field(default_factory=dict)
    dopant_charge_transfer: float | None = None
    spin_localization: float | None = None
    vde_ev: float | None = None
    ade_ev: float | None = None
    embedding_energy_ev: float | None = None
    issues: list[IssueFlag] = Field(default_factory=list)


class SizeEvolutionPoint(BaseModel):
    """Single size point along a size-evolution series."""

    size_n: int
    cluster_label: str
    energy_hartree: float
    binding_energy_ev_per_atom: float | None = None
    delta2_e_ev: float | None = None
    fragmentation_energy_ev: float | None = None
    homo_lumo_gap_ev: float | None = None
    magnetic_moment_mu_b: float


class ProjectSummary(BaseModel):
    """Cross-cluster inductive summary across a full research project."""

    project_id: str
    clusters: dict[str, ClusterSummary] = Field(default_factory=dict)
    size_evolution: list[SizeEvolutionPoint] = Field(default_factory=list)
    mixing_energies_ev: dict[str, float] = Field(default_factory=dict)
    all_issues: list[IssueFlag] = Field(default_factory=list)


def _collect_issues(results: list[CalcResult], best_mult: int) -> list[IssueFlag]:
    issues: list[IssueFlag] = []
    valid_mults = sorted(
        {
            r.state.multiplicity
            for r in results
            if r.normal_termination and r.energy_hartree is not None
        }
    )
    if valid_mults and len(valid_mults) >= 2 and best_mult == max(valid_mults):
        issues.append(
            IssueFlag(
                severity="warning",
                job_id=results[0].job_id,
                code="MULTIPLICITY_BOUNDARY_UNCAPPED",
                message=f"基态多重度 M={best_mult} 位于已扫描序列最高边界，建议确认是否需继续向上扫描。",
            )
        )

    for r in results:
        if not r.normal_termination:
            issues.append(
                IssueFlag(
                    severity="error",
                    job_id=r.job_id,
                    code="ABNORMAL_TERMINATION",
                    message=f"作业未正常结束（错误码: {r.error_code or '未知'}）。",
                )
            )
        if r.imag_freqs:
            issues.append(
                IssueFlag(
                    severity="warning",
                    job_id=r.job_id,
                    code="IMAGINARY_FREQUENCY",
                    message=f"存在虚频 {r.imag_freqs} cm^-1，可能尚未到达真实极小点。",
                )
            )
        if r.stable is False:
            issues.append(
                IssueFlag(
                    severity="warning",
                    job_id=r.job_id,
                    code="WAVEFUNCTION_UNSTABLE",
                    message="波函数存在稳定性问题（建议启用 stable=opt）。",
                )
            )
        ref_s2 = r.s2_after if r.s2_after is not None else r.s2_before
        if ref_s2 is not None and is_spin_contaminated(ref_s2, r.state.multiplicity):
            issues.append(
                IssueFlag(
                    severity="warning",
                    job_id=r.job_id,
                    code="SPIN_CONTAMINATION",
                    message=f"<S²>={ref_s2:.4f} 相对理论值偏离超过 10% (M={r.state.multiplicity})。",
                )
            )
    return issues


def summarize_cluster(
    cluster_label: str,
    results: list[CalcResult],
    *,
    atom_energies_ha: dict[str, float] | None = None,
    host_cluster_energy_ha: float | None = None,
    vde_neutral_at_anion_ha: float | None = None,
    neutral_min_energy_ha: float | None = None,
) -> ClusterSummary:
    """Induce ClusterSummary from all CalcResult objects of one composition/charge."""
    valid = [r for r in results if r.normal_termination and r.energy_hartree is not None]
    if not valid:
        raise ValueError(f"No normally terminated CalcResult with energy for {cluster_label!r}")

    valid.sort(key=lambda r: float(r.energy_hartree or 0.0))
    gs = valid[0]
    gs_energy = float(gs.energy_hartree or 0.0)

    isomers: list[IsomerEntry] = []
    for r in valid:
        e_ha = float(r.energy_hartree or 0.0)
        ref_s2 = r.s2_after if r.s2_after is not None else r.s2_before
        isomers.append(
            IsomerEntry(
                job_id=r.job_id,
                label=r.final_geometry.label if r.final_geometry else r.job_id,
                charge=r.state.charge,
                multiplicity=r.state.multiplicity,
                energy_hartree=e_ha,
                rel_energy_ev=(e_ha - gs_energy) * HA_TO_EV,
                homo_lumo_gap_ev=homo_lumo_gap_ev(r),
                imag_freqs=list(r.imag_freqs),
                normal_termination=r.normal_termination,
                s2_after=r.s2_after,
                spin_contaminated=(
                    is_spin_contaminated(ref_s2, r.state.multiplicity)
                    if ref_s2 is not None
                    else False
                ),
            )
        )

    # Spin-state energy ladder (lowest energy per multiplicity, in eV relative to gs)
    best_by_mult: dict[int, float] = {}
    for r in valid:
        m = r.state.multiplicity
        e_ha = float(r.energy_hartree or 0.0)
        if m not in best_by_mult or e_ha < best_by_mult[m]:
            best_by_mult[m] = e_ha
    spin_ladder = [
        (m, round((e - gs_energy) * HA_TO_EV, 6)) for m, e in sorted(best_by_mult.items())
    ]

    symbols = gs.final_geometry.symbols if gs.final_geometry else []
    stoich = dict(Counter(symbols))
    eb_ev: float | None = None
    if atom_energies_ha and stoich and all(el in atom_energies_ha for el in stoich):
        eb_ev = average_binding_energy_ha(gs_energy, atom_energies_ha, stoich) * HA_TO_EV

    n_val = valence_electron_count(symbols, gs.state.charge)
    mag = summarize_magnetism(gs)
    ct_by_el = charge_transfer_by_element(gs.charges, symbols) if symbols else {}
    dop_ct = minority_dopant_charge_transfer(gs.charges, symbols) if symbols else None

    vde_val = (
        vde_ev(gs_energy, vde_neutral_at_anion_ha)
        if (gs.state.charge == -1 and vde_neutral_at_anion_ha is not None)
        else None
    )
    ade_val = (
        ade_ev(gs_energy, neutral_min_energy_ha)
        if (gs.state.charge == -1 and neutral_min_energy_ha is not None)
        else None
    )

    emb_ev: float | None = None
    if host_cluster_energy_ha is not None and atom_energies_ha and len(stoich) > 1:
        counts = Counter(symbols)
        min_cnt = min(counts.values())
        dopants = [el for el, c in counts.items() if c == min_cnt]
        if len(dopants) == 1 and counts[dopants[0]] == 1 and dopants[0] in atom_energies_ha:
            emb_ev = (
                embedding_energy_ha(host_cluster_energy_ha, atom_energies_ha[dopants[0]], gs_energy)
                * HA_TO_EV
            )

    issues = _collect_issues(results, gs.state.multiplicity)

    return ClusterSummary(
        cluster_label=cluster_label,
        stoichiometry=stoich,
        charge=gs.state.charge,
        ground_state_job_id=gs.job_id,
        ground_state_multiplicity=gs.state.multiplicity,
        ground_state_energy_hartree=gs_energy,
        ground_state_geometry=gs.final_geometry,
        isomers=isomers,
        spin_ladder=spin_ladder,
        binding_energy_ev_per_atom=eb_ev,
        homo_lumo_gap_ev=homo_lumo_gap_ev(gs),
        valence_electrons=n_val,
        jellium_magic=is_jellium_magic(n_val),
        magnetic_moment_mu_b=float(mag["magnetic_moment_mu_b"]),
        charge_transfer_by_element=ct_by_el,
        dopant_charge_transfer=dop_ct,
        spin_localization=mag["spin_localization"],
        vde_ev=vde_val,
        ade_ev=ade_val,
        embedding_energy_ev=emb_ev,
        issues=issues,
    )


def summarize_project(
    project_id: str,
    clusters: dict[str, ClusterSummary],
    *,
    monomer_energy_ha: float | None = None,
    pure_endmembers_by_size: dict[tuple[str, int], float] | None = None,
) -> ProjectSummary:
    """Aggregate ClusterSummary objects into cross-cluster trends and ProjectSummary."""
    all_issues = [iss for cs in clusters.values() for iss in cs.issues]

    # Size evolution series sorted by total atom count
    ordered = sorted(
        clusters.values(),
        key=lambda cs: (sum(cs.stoichiometry.values()), cs.cluster_label),
    )
    by_size: dict[int, ClusterSummary] = {sum(cs.stoichiometry.values()): cs for cs in ordered}
    size_evo: list[SizeEvolutionPoint] = []
    for cs in ordered:
        n = sum(cs.stoichiometry.values())
        d2e: float | None = None
        if (n - 1) in by_size and (n + 1) in by_size:
            d2e = (
                second_order_energy_diff_ha(
                    by_size[n - 1].ground_state_energy_hartree,
                    cs.ground_state_energy_hartree,
                    by_size[n + 1].ground_state_energy_hartree,
                )
                * HA_TO_EV
            )
        frag: float | None = None
        if (n - 1) in by_size and monomer_energy_ha is not None:
            frag = (
                fragmentation_energy_ha(
                    by_size[n - 1].ground_state_energy_hartree,
                    monomer_energy_ha,
                    cs.ground_state_energy_hartree,
                )
                * HA_TO_EV
            )
        size_evo.append(
            SizeEvolutionPoint(
                size_n=n,
                cluster_label=cs.cluster_label,
                energy_hartree=cs.ground_state_energy_hartree,
                binding_energy_ev_per_atom=cs.binding_energy_ev_per_atom,
                delta2_e_ev=d2e,
                fragmentation_energy_ev=frag,
                homo_lumo_gap_ev=cs.homo_lumo_gap_ev,
                magnetic_moment_mu_b=cs.magnetic_moment_mu_b,
            )
        )

    # Bimetallic mixing energies when pure N-atom end-members are provided
    mixing_ev: dict[str, float] = {}
    if pure_endmembers_by_size:
        for lbl, cs in clusters.items():
            if len(cs.stoichiometry) == 2:
                (el_a, m_a), (el_b, n_b) = list(cs.stoichiometry.items())
                n_tot = m_a + n_b
                ea = pure_endmembers_by_size.get((el_a, n_tot))
                eb = pure_endmembers_by_size.get((el_b, n_tot))
                if ea is not None and eb is not None:
                    mixing_ev[lbl] = (
                        mixing_energy_ha(cs.ground_state_energy_hartree, m_a, ea, n_b, eb)
                        * HA_TO_EV
                    )

    return ProjectSummary(
        project_id=project_id,
        clusters=clusters,
        size_evolution=size_evo,
        mixing_energies_ev=mixing_ev,
        all_issues=all_issues,
    )

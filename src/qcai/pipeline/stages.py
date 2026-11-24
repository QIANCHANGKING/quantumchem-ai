"""Idempotent funnel stage progression functions S0-S7 (Section 6.5)."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from qcai.core.models import (
    CalcPlan,
    CalcResult,
    CalcSpec,
    Cluster,
    ElectronicState,
    ResearchRequest,
)
from qcai.core.physics import EV_TO_HA, total_electrons
from qcai.pipeline.db import JobRecord, JobStore, ProjectRecord
from qcai.planner import (
    derive_charge_plan,
    derive_multiplicity_candidates,
    derive_reference_systems,
    expand_composition,
)
from qcai.planner.planner import stoichiometry_label
from qcai.planner.rule_engine import evaluate_theory_rules, extract_system_features
from qcai.programs.gaussian.writer import write_gaussian_input
from qcai.remote.resources import ServerProbe
from qcai.structure import (
    ABClusterGenerator,
    ScoredCluster,
    deduplicate_clusters,
    read_clusters_from_file,
    select_generator_name,
)


def _decision_value(plan: CalcPlan, key: str, default: Any = None) -> Any:
    for d in reversed(plan.decisions):
        if d.key == key:
            return d.value
    return default


def _next_multiplicity_to_scan(
    *,
    base_sequence: list[int],
    completed: list[tuple[int, float]],
    in_flight: set[int],
    attempted: set[int] | None = None,
    n_electrons: int,
    early_stop_ev: float = 0.50,
    consecutive_high: int = 2,
) -> list[int]:
    """Apply Section 5.2 adaptive multiplicity scan rules to decide next M value(s)."""
    done_map = dict(completed)
    all_scheduled = set(done_map) | in_flight | (attempted or set())

    # Initial bootstrap: start with first 2 multiplicities in parity sequence
    if not all_scheduled:
        return base_sequence[:2] if len(base_sequence) >= 2 else base_sequence[:1]

    # Wait until at least the current batch has completed before deciding next step
    if in_flight:
        return []
    if not completed:
        return []

    ordered_done = sorted(completed, key=lambda x: x[0])
    min_m, min_e = min(ordered_done, key=lambda x: x[1])
    thresh_ha = early_stop_ev * EV_TO_HA

    # Early stop: last `consecutive_high` higher states both > min_e + 0.5 eV
    if len(ordered_done) >= consecutive_high:
        tail = ordered_done[-consecutive_high:]
        if all((e - min_e) > thresh_ha for _, e in tail) and all(m > min_m for m, _ in tail):
            return []

    max_done_m = ordered_done[-1][0]
    # Next item in planned sequence
    for m in base_sequence:
        if m not in all_scheduled and m > max_done_m:
            return [m]

    # Boundary expansion: if lowest-energy state sits at highest scanned M, expand by +2
    if min_m == max_done_m:
        cand = max_done_m + 2
        if (cand - 1) <= n_electrons and cand not in all_scheduled:
            return [cand]

    return []


def _enqueue_gaussian_job(
    *,
    store: JobStore,
    project_id: str,
    job_id: str,
    stage: str,
    cluster: Cluster,
    state: ElectronicState,
    spec: CalcSpec,
    project_dir: Path,
    remote_work_root: str,
    nproc: int = 4,
    mem_gb: int = 8,
    meta: dict[str, Any] | None = None,
    run_formchk: bool = True,
) -> JobRecord:
    existing = store.get_job(job_id)
    if existing is not None:
        return existing

    j_local = project_dir / "jobs" / job_id
    j_local.mkdir(parents=True, exist_ok=True)
    write_gaussian_input(
        cluster,
        state,
        spec,
        j_local / "job.gjf",
        nproc=nproc,
        mem_gb=mem_gb,
        chk_name="job.chk",
    )
    job_json = {
        "job_id": job_id,
        "gjf_file": "job.gjf",
        "log_file": "job.log",
        "chk_file": "job.chk",
        "max_errors": 3,
        "run_formchk": run_formchk,
    }
    (j_local / "job.json").write_text(
        json.dumps(job_json, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )

    r_dir = PurePosixPath(remote_work_root) / project_id / job_id
    level_str = f"{spec.functional}/{spec.basis}"
    job_meta: dict[str, Any] = {
        "atom_count": len(cluster.symbols),
        "nproc": nproc,
        "mem_gb": mem_gb,
        **(meta or {}),
    }
    return store.upsert_job(
        JobRecord(
            job_id=job_id,
            project_id=project_id,
            stage=stage,
            cluster_label=cluster.label,
            job_kind="gaussian",
            charge=state.charge,
            multiplicity=state.multiplicity,
            level=level_str,
            status="queued",
            remote_dir=str(r_dir),
            local_dir=str(j_local),
            meta_json=json.dumps(job_meta, ensure_ascii=False),
        )
    )


def _enqueue_search_job(
    *,
    store: JobStore,
    project_id: str,
    job_id: str,
    stoich: dict[str, int],
    charge: int,
    multiplicity: int,
    engine: str,
    project_dir: Path,
    remote_work_root: str,
    remote_python: str | None = None,
    max_calcs: int = 60,
) -> JobRecord:
    existing = store.get_job(job_id)
    if existing is not None:
        return existing

    j_local = project_dir / "jobs" / job_id
    j_local.mkdir(parents=True, exist_ok=True)
    search_cfg: dict[str, Any] = {
        "job_id": job_id,
        "engine": engine,
        "composition": stoich,
        "charge": charge,
        "multiplicity": multiplicity,
        "out_xyz": "candidates.xyz",
        "population_size": 12,
        "n_generations": 4,
    }
    if engine == "abcluster":
        inp_path, _ = ABClusterGenerator.build_isomer_files(
            stoich,
            j_local,
            result_name="abc",
            max_calcs=max_calcs,
            charge=charge,
            multiplicity=multiplicity,
        )
        search_cfg["inp_file"] = inp_path.name
        search_cfg["result_name"] = "abc"

    (j_local / "search.json").write_text(
        json.dumps(search_cfg, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    py = remote_python or "python3"
    r_dir = PurePosixPath(remote_work_root) / project_id / job_id
    return store.upsert_job(
        JobRecord(
            job_id=job_id,
            project_id=project_id,
            stage="S1_search",
            cluster_label=stoichiometry_label(stoich),
            job_kind="search",
            command=f"{py} -m qcai_remote.search search.json",
            charge=charge,
            multiplicity=multiplicity,
            level="GFN2-xTB",
            status="queued",
            remote_dir=str(r_dir),
            local_dir=str(j_local),
            meta_json=json.dumps({"stoichiometry": stoich}, ensure_ascii=False),
        )
    )


def _load_calc_result(job: JobRecord) -> CalcResult | None:
    if not job.result_path:
        return None
    p = Path(job.result_path)
    if not p.exists():
        return None
    return CalcResult.model_validate_json(p.read_text(encoding="utf-8"))


def advance_pipeline(
    project: ProjectRecord,
    store: JobStore,
    *,
    project_dir: Path,
    remote_work_root: str = "/tmp/qcai_work",
    probe: ServerProbe | None = None,
    remote_python: str | None = None,
    nproc: int = 4,
    mem_gb: int = 8,
) -> list[JobRecord]:
    """Idempotently inspect project jobs and enqueue the next ready stage jobs."""
    if project.status in {"paused", "completed", "failed", "needs_human"}:
        return []
    if project.plan_json is None:
        raise ValueError(f"Project {project.project_id!r} has no CalcPlan")

    request = ResearchRequest.model_validate_json(project.request_json)
    plan = CalcPlan.model_validate_json(project.plan_json)
    features = extract_system_features(request)
    rule_state, _ = evaluate_theory_rules(request, features)
    stoichiometries = expand_composition(request.composition)
    charges, _, _ = derive_charge_plan(request.recipes, request.charges)

    scr_spec = CalcSpec(
        functional=str(rule_state["screening_functional"]),
        basis=str(rule_state["screening_basis"]),
        dispersion=rule_state["screening_dispersion"],
        tasks=["opt"] if request.accuracy == "fast" else ["sp"],
        scf_strategy=rule_state["scf_strategy"],
        nosymm=bool(rule_state["nosymm"]),
    )
    has_refinement = rule_state.get("refinement_functional") is not None
    ref_tasks = list(rule_state["refinement_tasks"]) or ["opt", "freq"]
    if rule_state.get("enable_stability_check") and "stable" not in ref_tasks:
        ref_tasks.append("stable")
    ref_spec = (
        CalcSpec(
            functional=str(rule_state["refinement_functional"]),
            basis=str(rule_state["refinement_basis"]),
            dispersion=rule_state["refinement_dispersion"],
            tasks=ref_tasks,
            scf_strategy=rule_state["scf_strategy"],
            nosymm=bool(rule_state["nosymm"]),
        )
        if has_refinement
        else scr_spec
    )

    candidate_k = int(_decision_value(plan, "candidate_k", rule_state["candidate_k"]))
    top_refine_n = int(request.overrides.get("top_refine", min(3, candidate_k)))
    search_max_calcs = int(request.overrides.get("search_max_calcs", 60))
    mult_cap = rule_state.get("max_multiplicity_cap")
    newly_queued: list[JobRecord] = []

    # --- S0: Reference isolated atoms ---
    refs = derive_reference_systems(stoichiometries, ref_spec)
    for ref in refs:
        if len(ref.stoichiometry) == 1 and next(iter(ref.stoichiometry.values())) == 1:
            el = next(iter(ref.stoichiometry))
            atom_cluster = Cluster(symbols=[el], positions=[(0.0, 0.0, 0.0)], label=ref.label)
            jid = f"{project.project_id}__s0__{ref.label}"
            if store.get_job(jid) is None:
                newly_queued.append(
                    _enqueue_gaussian_job(
                        store=store,
                        project_id=project.project_id,
                        job_id=jid,
                        stage="S0_reference",
                        cluster=atom_cluster,
                        state=ref.state,
                        spec=ref.calc_spec,
                        project_dir=project_dir,
                        remote_work_root=remote_work_root,
                        nproc=min(2, nproc),
                        mem_gb=min(4, mem_gb),
                    )
                )

    # --- S1 & S2: Structure search and deduplication per stoichiometry ---
    gen_name = select_generator_name(probe, has_imported_structures=bool(request.structures))
    all_jobs = store.list_jobs(project_id=project.project_id)

    for stoich in stoichiometries:
        s_label = stoichiometry_label(stoich)
        dedup_file = project_dir / f"S2_dedup_{s_label}.json"

        if not dedup_file.exists():
            if request.structures:
                matching = [
                    ScoredCluster(cluster=c, energy_hartree=None)
                    for c in request.structures
                    if sorted(c.symbols)
                    == sorted([el for el, n in stoich.items() for _ in range(n)])
                ]
                if matching:
                    kept = deduplicate_clusters(matching, top_k=candidate_k)
                    dedup_file.parent.mkdir(parents=True, exist_ok=True)
                    dedup_file.write_text(
                        json.dumps([sc.model_dump() for sc in kept], indent=2),
                        encoding="utf-8",
                    )
            else:
                s1_jid = f"{project.project_id}__s1__{s_label}"
                s1_job = store.get_job(s1_jid)
                if s1_job is None:
                    m_cands, _ = derive_multiplicity_candidates(
                        stoich,
                        charges[0],
                        has_transition_metal=features.has_transition_metal,
                        user_cap=mult_cap,
                    )
                    newly_queued.append(
                        _enqueue_search_job(
                            store=store,
                            project_id=project.project_id,
                            job_id=s1_jid,
                            stoich=stoich,
                            charge=charges[0],
                            multiplicity=m_cands[0],
                            engine=gen_name if gen_name in {"abcluster", "ase_ga"} else "ase_ga",
                            project_dir=project_dir,
                            remote_work_root=remote_work_root,
                            remote_python=remote_python,
                            max_calcs=search_max_calcs,
                        )
                    )
                    continue
                if s1_job.status != "done":
                    continue
                cand_xyz = Path(s1_job.local_dir) / "candidates.xyz"
                if cand_xyz.exists():
                    raw_cands = read_clusters_from_file(cand_xyz, label_prefix=s_label)
                    kept = deduplicate_clusters(raw_cands, top_k=candidate_k)
                    dedup_file.parent.mkdir(parents=True, exist_ok=True)
                    dedup_file.write_text(
                        json.dumps([sc.model_dump() for sc in kept], indent=2),
                        encoding="utf-8",
                    )

        if not dedup_file.exists():
            continue

        # --- S3: Screening DFT with adaptive multiplicity scan ---
        kept_items = [
            ScoredCluster.model_validate(item)
            for item in json.loads(dedup_file.read_text(encoding="utf-8"))
        ]
        syms = [el for el, n in stoich.items() for _ in range(n)]

        for q in charges:
            n_elec = total_electrons(syms, q)
            base_m_seq, _ = derive_multiplicity_candidates(
                stoich,
                q,
                has_transition_metal=features.has_transition_metal,
                user_cap=mult_cap,
            )
            s3_finished_all = True
            s3_best_by_iso: list[tuple[int, int, float, Cluster]] = []

            for iso_idx, sc in enumerate(kept_items):
                iso_jobs = [
                    j
                    for j in all_jobs
                    if j.stage == "S3_screen"
                    and json.loads(j.meta_json).get("stoich_label") == s_label
                    and json.loads(j.meta_json).get("iso_idx") == iso_idx
                    and j.charge == q
                ]
                completed: list[tuple[int, float]] = []
                in_flight: set[int] = set()
                for j in iso_jobs:
                    if j.status in {"queued", "running"}:
                        in_flight.add(j.multiplicity)
                    elif j.status == "done":
                        res = _load_calc_result(j)
                        if res is not None and res.energy_hartree is not None:
                            completed.append((j.multiplicity, res.energy_hartree))

                next_mults = _next_multiplicity_to_scan(
                    base_sequence=base_m_seq,
                    completed=completed,
                    in_flight=in_flight,
                    attempted={j.multiplicity for j in iso_jobs},
                    n_electrons=n_elec,
                )
                for m in next_mults:
                    jid = f"{project.project_id}__s3__{s_label}_q{q}_i{iso_idx}_m{m}"
                    newly_queued.append(
                        _enqueue_gaussian_job(
                            store=store,
                            project_id=project.project_id,
                            job_id=jid,
                            stage="S3_screen",
                            cluster=sc.cluster,
                            state=ElectronicState(charge=q, multiplicity=m),
                            spec=scr_spec,
                            project_dir=project_dir,
                            remote_work_root=remote_work_root,
                            nproc=nproc,
                            mem_gb=mem_gb,
                            meta={
                                "stoich_label": s_label,
                                "iso_idx": iso_idx,
                                "charge": q,
                            },
                            run_formchk=False,
                        )
                    )
                    in_flight.add(m)

                if in_flight or next_mults:
                    s3_finished_all = False
                elif completed:
                    best_m, best_e = min(completed, key=lambda x: x[1])
                    s3_best_by_iso.append((iso_idx, best_m, best_e, sc.cluster))

            # --- S4: Refinement DFT (opt + freq + stable) for top candidates ---
            if not s3_finished_all or not s3_best_by_iso:
                continue

            s3_best_by_iso.sort(key=lambda x: x[2])
            if has_refinement:
                top_refine = s3_best_by_iso[:top_refine_n]
                for iso_idx, best_m, _, cand_cluster in top_refine:
                    jid = f"{project.project_id}__s4__{s_label}_q{q}_i{iso_idx}_m{best_m}"
                    if store.get_job(jid) is None:
                        newly_queued.append(
                            _enqueue_gaussian_job(
                                store=store,
                                project_id=project.project_id,
                                job_id=jid,
                                stage="S4_refine",
                                cluster=cand_cluster,
                                state=ElectronicState(charge=q, multiplicity=best_m),
                                spec=ref_spec,
                                project_dir=project_dir,
                                remote_work_root=remote_work_root,
                                nproc=nproc,
                                mem_gb=mem_gb,
                                meta={"stoich_label": s_label, "iso_idx": iso_idx, "charge": q},
                            )
                        )

            # --- S5: Ionic state vertical / adiabatic jobs (PES / Ionization) ---
            planned_stage_names = {s.stage for s in plan.stages}
            if "S5_ionic" in planned_stage_names and "pes" in request.recipes and q == -1:
                s4_anion_jobs = [
                    j
                    for j in all_jobs
                    if j.stage == "S4_refine"
                    and j.status == "done"
                    and json.loads(j.meta_json).get("stoich_label") == s_label
                    and j.charge == -1
                ]
                if s4_anion_jobs:
                    # Pick lowest-energy anion geometry for VDE single-point at q=0
                    anion_results = [(j, _load_calc_result(j)) for j in s4_anion_jobs]
                    valid_anions = [
                        (j, r)
                        for j, r in anion_results
                        if r is not None
                        and r.energy_hartree is not None
                        and r.final_geometry is not None
                    ]
                    if valid_anions:
                        best_j, best_r = min(
                            valid_anions,
                            key=lambda item: float(item[1].energy_hartree or 0.0),
                        )
                        n_neu = total_electrons(syms, 0)
                        m_neu = 1 if n_neu % 2 == 0 else 2
                        vde_jid = f"{project.project_id}__s5_vde__{s_label}"
                        if store.get_job(vde_jid) is None and best_r.final_geometry is not None:
                            vde_spec = ref_spec.model_copy(update={"tasks": ["sp"]})
                            newly_queued.append(
                                _enqueue_gaussian_job(
                                    store=store,
                                    project_id=project.project_id,
                                    job_id=vde_jid,
                                    stage="S5_ionic",
                                    cluster=best_r.final_geometry,
                                    state=ElectronicState(charge=0, multiplicity=m_neu),
                                    spec=vde_spec,
                                    project_dir=project_dir,
                                    remote_work_root=remote_work_root,
                                    nproc=nproc,
                                    mem_gb=mem_gb,
                                    meta={"stoich_label": s_label, "kind": "vde"},
                                )
                            )

    # Check if entire project has completed or stalled on needs_human jobs
    refreshed_jobs = store.list_jobs(project_id=project.project_id)
    if (
        refreshed_jobs
        and not newly_queued
        and all(j.status in {"done", "needs_human", "cancelled"} for j in refreshed_jobs)
    ):
        if any(j.status == "needs_human" for j in refreshed_jobs):
            store.set_project_status(project.project_id, "needs_human")
        elif all(
            (project_dir / f"S2_dedup_{stoichiometry_label(s)}.json").exists()
            for s in stoichiometries
        ):
            store.set_project_status(project.project_id, "completed")

    return newly_queued

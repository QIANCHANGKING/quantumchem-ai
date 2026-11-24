"""Unit tests for P4 funnel stages, adaptive multiplicity scan, PipelineWorker, and cost calibration."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from typer.testing import CliRunner

from qcai.cli import app
from qcai.core.models import CalcResult, CalcSpec, Cluster, ElectronicState, ResearchRequest
from qcai.core.physics import EV_TO_HA
from qcai.pipeline import JobStore, PipelineWorker, ProjectRecord
from qcai.pipeline.db import JobRecord
from qcai.pipeline.stages import _next_multiplicity_to_scan, advance_pipeline
from qcai.planner import build_plan
from qcai.planner.cost_model import calibrate_cost_model
from qcai.programs.gaussian.writer import read_gaussian_nproc, write_gaussian_input
from qcai.remote import MockRunner
from qcai.remote.resources import OtherUsersLoad, ServerProbe

BENCHMARK_YAML = Path(__file__).resolve().parents[1] / "data" / "benchmark" / "clusters.yaml"


def test_adaptive_multiplicity_early_stop_and_boundary_expansion() -> None:
    # Bootstrap selects first 2 states
    init = _next_multiplicity_to_scan(
        base_sequence=[1, 3, 5, 7, 9],
        completed=[],
        in_flight=set(),
        n_electrons=20,
    )
    assert init == [1, 3]

    # If M=1 is lowest and M=3, M=5 are both > 0.5 eV above M=1 -> early stop!
    stopped = _next_multiplicity_to_scan(
        base_sequence=[1, 3, 5, 7, 9],
        completed=[(1, -100.0), (3, -100.0 + 0.6 * EV_TO_HA), (5, -100.0 + 0.8 * EV_TO_HA)],
        in_flight=set(),
        n_electrons=20,
    )
    assert stopped == []

    # If M=5 (boundary) is lowest after exhausting base_sequence=[1, 3, 5], expand to 7!
    expanded = _next_multiplicity_to_scan(
        base_sequence=[1, 3, 5],
        completed=[(1, -99.5), (3, -99.8), (5, -100.2)],
        in_flight=set(),
        n_electrons=20,
    )
    assert expanded == [7]


def _write_fake_result(
    project_dir: Path, job_id: str, cluster: Cluster, q: int, m: int, e: float
) -> None:
    jdir = project_dir / "jobs" / job_id
    jdir.mkdir(parents=True, exist_ok=True)
    # Minimal valid Gaussian log text for parse_gaussian_log
    atom_rows = "\n".join(
        f"     {i + 1:2d}         13           0    {x:10.6f}  {y:10.6f}  {z:10.6f}"
        for i, (x, y, z) in enumerate(cluster.positions)
    )
    log_text = (
        " Entering Gaussian System, Link 0=g16\n"
        " Entering Link 1 = /opt/g16/l1.exe PID= 100.\n"
        "                         Standard orientation:\n"
        " ---------------------------------------------------------------------\n"
        " Center     Atomic      Atomic             Coordinates (Angstroms)\n"
        " Number     Number       Type             X           Y           Z\n"
        " ---------------------------------------------------------------------\n"
        f"{atom_rows}\n"
        " ---------------------------------------------------------------------\n"
        f" Charge = {q} Multiplicity = {m}\n"
        f" SCF Done:  E(RPBEPBE) =  {e:.8f}     A.U. after   10 cycles\n"
        " Normal termination of Gaussian 16 at Wed Nov 18 12:00:00 2026.\n"
    )
    (jdir / "job.log").write_text(log_text, encoding="utf-8")


def test_pipeline_worker_end_to_end_with_pause_resume(tmp_path: Path) -> None:
    db_path = tmp_path / "qcai.sqlite"
    store = JobStore(db_path)
    runner = MockRunner()

    c1 = Cluster(
        symbols=["Na", "Na", "Na", "Na"],
        positions=[(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (1.5, 2.6, 0.0), (1.5, 0.9, 2.4)],
        label="na4_a",
    )
    c2 = Cluster(
        symbols=["Na", "Na", "Na", "Na"],
        positions=[(0.0, 0.0, 0.0), (3.1, 0.0, 0.0), (6.2, 0.0, 0.0), (1.55, 2.7, 0.0)],
        label="na4_b",
    )
    req = ResearchRequest(
        composition={"Na": 4},
        recipes=["stability", "pes"],
        accuracy="standard",
        structures=[c1, c2],
    )
    plan = build_plan(req)
    store.upsert_project(
        ProjectRecord(
            project_id="p_na4",
            title="Na4 PES test",
            request_json=req.model_dump_json(),
            plan_json=plan.model_dump_json(),
            status="running",
        )
    )

    worker = PipelineWorker(store, runner, projects_root=tmp_path)
    # Tick 1: S0 + S2 dedup + S3 initial multiplicity jobs enqueued & submitted
    s1 = worker.step(project_id="p_na4")
    assert s1["enqueued"] > 0 and s1["submitted"] > 0

    for j in store.list_jobs(project_id="p_na4", status="running"):
        if j.job_kind == "gaussian":
            energy = -648.0 if j.multiplicity == 1 else -647.9
            _write_fake_result(tmp_path / "p_na4", j.job_id, c1, j.charge, j.multiplicity, energy)

    # Pause prevents new submissions while allowing existing jobs to run
    store.set_project_status("p_na4", "paused")
    s_paused = worker.step(project_id="p_na4")
    assert s_paused["enqueued"] == 0 and s_paused["submitted"] == 0
    store.set_project_status("p_na4", "running")

    # Drive worker ticks, populating synthetic logs for any submitted gaussian jobs
    for _ in range(50):
        for j in store.list_jobs(project_id="p_na4", status="running"):
            if j.job_kind == "gaussian" and not (Path(j.local_dir) / "job.log").exists():
                # Give M=1 lower energy than M=3 so adaptive scan finishes cleanly
                energy = -648.0 if j.multiplicity == 1 else -647.9
                _write_fake_result(
                    tmp_path / "p_na4", j.job_id, c1, j.charge, j.multiplicity, energy
                )
        worker.step(project_id="p_na4")
        proj = store.get_project("p_na4")
        if proj is not None and proj.status == "completed":
            break

    final_proj = store.get_project("p_na4")
    assert final_proj is not None and final_proj.status == "completed"
    stages_seen = {j.stage for j in store.list_jobs(project_id="p_na4")}
    assert {"S0_reference", "S3_screen", "S4_refine", "S5_ionic"}.issubset(stages_seen)

    # Verify parsed JSON saved under results/
    res_files = list((tmp_path / "p_na4" / "results").glob("*.json"))
    assert len(res_files) >= 4
    sample_res = CalcResult.model_validate_json(res_files[0].read_text(encoding="utf-8"))
    assert sample_res.normal_termination is True


def test_cost_model_calibration_and_cli_worker(tmp_path: Path) -> None:
    obs = [
        (40, ["opt"], 1, 0.10),
        (80, ["opt", "freq"], 1, 1.20),
        (100, ["opt", "freq"], 2, 3.00),
    ]
    model = calibrate_cost_model(obs)
    assert model.sample_count == 3
    assert model.scale_factor > 0.1
    assert model.predict_core_hours(60, ["opt"], mult=1) > 0

    db = tmp_path / "cli.sqlite"
    store = JobStore(db)
    req = ResearchRequest(composition={"Li": 2}, recipes=["stability"], accuracy="fast")
    plan = build_plan(req)
    store.upsert_project(
        ProjectRecord(
            project_id="cli_p",
            title="CLI",
            request_json=req.model_dump_json(),
            plan_json=plan.model_dump_json(),
            status="running",
        )
    )

    runner = CliRunner()
    r_pause = runner.invoke(app, ["pause", "cli_p", "--db", str(db)])
    assert r_pause.exit_code == 0
    assert store.get_project("cli_p").status == "paused"  # type: ignore[union-attr]

    r_resume = runner.invoke(app, ["resume", "cli_p", "--db", str(db)])
    assert r_resume.exit_code == 0
    assert store.get_project("cli_p").status == "running"  # type: ignore[union-attr]

    r_worker = runner.invoke(
        app, ["worker", "--project", "cli_p", "--db", str(db), "--once", "--mock"]
    )
    assert r_worker.exit_code == 0
    assert "Worker tick:" in r_worker.stdout


def test_benchmark_catalog_schema_and_dois() -> None:
    data = yaml.safe_load(BENCHMARK_YAML.read_text(encoding="utf-8"))
    items = data["benchmarks"]
    assert 5 <= len(items) <= 10
    categories = {it["category"] for it in items}
    assert len(categories) >= 5
    for it in items:
        assert str(it["doi"]).startswith("10.")
        assert it["expected_multiplicity"] >= 1


def test_pipeline_marks_needs_human_instead_of_completed_on_failed_jobs(tmp_path: Path) -> None:
    db_path = tmp_path / "qcai.sqlite"
    store = JobStore(db_path)
    c1 = Cluster(
        symbols=["Na", "Na"],
        positions=[(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)],
        label="na2",
    )
    req = ResearchRequest(
        composition={"Na": 2},
        recipes=["stability"],
        accuracy="fast",
        structures=[c1],
    )
    plan = build_plan(req)
    proj = store.upsert_project(
        ProjectRecord(
            project_id="p_needs_human",
            title="Needs human status check",
            request_json=req.model_dump_json(),
            plan_json=plan.model_dump_json(),
            status="running",
        )
    )

    proj_dir = tmp_path / "p_needs_human"
    added = advance_pipeline(proj, store, project_dir=proj_dir)
    assert len(added) > 0

    for j in store.list_jobs(project_id="p_needs_human"):
        j.status = "done" if j.stage == "S0_reference" else "needs_human"
        store.upsert_job(j)

    proj = store.get_project("p_needs_human")  # type: ignore[assignment]
    more = advance_pipeline(proj, store, project_dir=proj_dir)
    assert more == []
    updated = store.get_project("p_needs_human")
    assert updated is not None
    assert updated.status == "needs_human"

    # Once marked needs_human, advance_pipeline stops enqueueing
    assert advance_pipeline(updated, store, project_dir=proj_dir) == []


def test_worker_run_loop_survives_transient_step_error(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "qcai.sqlite")

    class _DummySSH:
        def __init__(self) -> None:
            self.closed = 0

        def close(self) -> None:
            self.closed += 1

    ssh = _DummySSH()
    worker = PipelineWorker(store, MockRunner(), projects_root=tmp_path, ssh=ssh)  # type: ignore[arg-type]

    calls = {"n": 0}

    def _flaky_step(*, project_id: str | None = None) -> dict[str, int]:
        del project_id
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError(10054, "Transient reset")
        return {"collected": 0, "enqueued": 0, "submitted": 0}

    worker.step = _flaky_step  # type: ignore[method-assign]
    worker.run_loop(poll_interval=0.0, max_ticks=2)
    assert calls["n"] == 2
    assert ssh.closed == 1


def test_worker_elastic_scaling_updates_queued_gjf_on_submit(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "qcai.sqlite")
    runner = MockRunner()
    probe = ServerProbe(
        physical_cores=48,
        logical_cores=96,
        numa_nodes=2,
        cores_per_numa=[24, 24],
        total_mem_gb=251.0,
        available_mem_gb=230.0,
        load_avg=[2.0, 2.0, 2.0],
        scratch_free_gb=500.0,
        other_users=OtherUsersLoad(other_user_process_count=0, estimated_other_busy_cores=0.0),
    )

    store.upsert_project(
        ProjectRecord(
            project_id="p_elastic",
            title="ErAu5 elastic tail",
            request_json="{}",
            plan_json="{}",
            status="created",
        )
    )

    er_atom = Cluster(symbols=["Er"], positions=[(0.0, 0.0, 0.0)], label="atom_Er")
    er_au5 = Cluster(
        symbols=["Er", "Au", "Au", "Au", "Au", "Au"],
        positions=[
            (0.0, 0.0, 0.0),
            (2.7, 0.0, 0.0),
            (-2.7, 0.0, 0.0),
            (0.0, 2.7, 0.0),
            (0.0, -2.7, 0.0),
            (0.0, 0.0, 2.7),
        ],
        label="ErAu5",
    )
    ref_spec = CalcSpec(
        functional="PBE0",
        basis="def2-TZVP",
        dispersion="GD3BJ",
        tasks=["opt", "freq", "stable"],
        scf_strategy="robust",
        nosymm=True,
    )
    atom_spec = CalcSpec(
        functional="PBE0",
        basis="def2-TZVP",
        tasks=["sp"],
        scf_strategy="robust",
        nosymm=True,
    )

    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    s0_dir = tmp_path / "p_elastic" / "jobs" / "j_s0"
    write_gaussian_input(
        er_atom,
        ElectronicState(charge=0, multiplicity=3),
        atom_spec,
        s0_dir / "job.gjf",
        nproc=4,
        mem_gb=8,
    )
    store.upsert_job(
        JobRecord(
            job_id="j_s0",
            project_id="p_elastic",
            stage="S0_reference",
            cluster_label="atom_Er",
            job_kind="gaussian",
            charge=0,
            multiplicity=3,
            level="PBE0/def2-TZVP",
            status="queued",
            remote_dir="/tmp/qcai_work/p_elastic/j_s0",
            local_dir=str(s0_dir),
            meta_json=json.dumps({"atom_count": 1, "nproc": 4, "mem_gb": 8}),
            created_at=t0,
        )
    )

    s4_ids = ["j_s4_1", "j_s4_2", "j_s4_3"]
    for idx, jid in enumerate(s4_ids, start=1):
        j_dir = tmp_path / "p_elastic" / "jobs" / jid
        write_gaussian_input(
            er_au5,
            ElectronicState(charge=0, multiplicity=4),
            ref_spec,
            j_dir / "job.gjf",
            nproc=4,
            mem_gb=8,
        )
        store.upsert_job(
            JobRecord(
                job_id=jid,
                project_id="p_elastic",
                stage="S4_refine",
                cluster_label=f"ErAu5_i{idx}",
                job_kind="gaussian",
                charge=0,
                multiplicity=4,
                level="PBE0/def2-TZVP",
                status="queued",
                remote_dir=f"/tmp/qcai_work/p_elastic/{jid}",
                local_dir=str(j_dir),
                meta_json=json.dumps({"atom_count": 6, "nproc": 4, "mem_gb": 8}),
                created_at=t0 + timedelta(seconds=idx),
            )
        )

    worker = PipelineWorker(store, runner, projects_root=tmp_path, probe=probe)
    summary = worker.step(project_id="p_elastic")
    assert summary["submitted"] == 4

    s0_job = store.get_job("j_s0")
    assert s0_job is not None
    assert read_gaussian_nproc(s0_dir / "job.gjf") == 2
    assert json.loads(s0_job.meta_json)["nproc"] == 2

    total_cores = 2
    for jid in s4_ids:
        job = store.get_job(jid)
        assert job is not None
        gjf_path = tmp_path / "p_elastic" / "jobs" / jid / "job.gjf"
        gjf_text = gjf_path.read_text(encoding="utf-8")
        gjf_nproc = read_gaussian_nproc(gjf_path)
        meta = json.loads(job.meta_json)
        assert gjf_nproc in {14, 16}
        assert meta["nproc"] == gjf_nproc
        assert "--Link1--" in gjf_text
        assert "ER-ECP" in gjf_text.upper()
        total_cores += meta["nproc"]

    assert total_cores <= 47

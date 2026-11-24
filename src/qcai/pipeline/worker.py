"""Background scheduling loop (`qcai worker`) with pause/resume and cost calibration."""

from __future__ import annotations

import json
import time
from pathlib import Path, PurePosixPath
from typing import Any

from qcai.interfaces.runner import JobHandle, JobRunner
from qcai.pipeline.db import JobRecord, JobStore
from qcai.pipeline.stages import advance_pipeline
from qcai.planner.cost_model import CalibratedCostModel, calibrate_cost_model
from qcai.programs.gaussian.parser import parse_gaussian_log
from qcai.programs.gaussian.writer import (
    read_gaussian_nproc,
    update_gaussian_link0_resources,
)
from qcai.remote.deploy import deploy_and_probe
from qcai.remote.resources import ResourceManager, ServerProbe
from qcai.remote.ssh import SSHClient


def _parse_job_meta(job: JobRecord) -> dict[str, Any]:
    if not job.meta_json:
        return {}
    try:
        parsed = json.loads(job.meta_json)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _job_nproc(job: JobRecord) -> int:
    meta = _parse_job_meta(job)
    nproc = _positive_int(meta.get("nproc"))
    if nproc is not None:
        return nproc
    if job.job_kind == "gaussian" and job.local_dir:
        from_gjf = read_gaussian_nproc(Path(job.local_dir) / "job.gjf")
        if from_gjf is not None:
            return from_gjf
    if job.stage == "S0_reference":
        return 2
    if job.job_kind == "search":
        return 1
    return 4


def _job_atom_count(job: JobRecord) -> int:
    meta = _parse_job_meta(job)
    atom_count = _positive_int(meta.get("atom_count"))
    if atom_count is not None:
        return atom_count
    return 1 if job.stage == "S0_reference" else 6


class PipelineWorker:
    """Polls jobs, parses outputs, enforces concurrency limits, and advances S0-S7 stages."""

    def __init__(
        self,
        store: JobStore,
        runner: JobRunner,
        *,
        projects_root: Path = Path("projects"),
        remote_work_root: str = "/tmp/qcai_work",
        ssh: SSHClient | None = None,
        probe: ServerProbe | None = None,
        remote_python: str | None = None,
        resource_manager: ResourceManager | None = None,
        probe_refresh_seconds: float = 180.0,
    ) -> None:
        self.store = store
        self.runner = runner
        self.projects_root = Path(projects_root)
        self.remote_work_root = remote_work_root
        self.ssh = ssh
        self.probe = probe
        self.remote_python = remote_python
        self.resource_manager = resource_manager or ResourceManager()
        self.probe_refresh_seconds = probe_refresh_seconds
        self._last_probe_ts: float = time.monotonic() if probe is not None else 0.0
        self.cost_model = CalibratedCostModel()
        self._stop_requested = False

    def _refresh_probe_if_needed(self) -> None:
        if self.ssh is None:
            return
        now = time.monotonic()
        if self.probe is None or (now - self._last_probe_ts) >= self.probe_refresh_seconds:
            self.probe, py_exe = deploy_and_probe(self.ssh, install_env=False)
            if py_exe:
                self.remote_python = py_exe
            self._last_probe_ts = now

    def request_stop(self) -> None:
        self._stop_requested = True

    def _collect_finished_job(self, job: JobRecord) -> None:
        if job.job_kind == "gaussian":
            j_local = Path(job.local_dir)
            r_dir = PurePosixPath(job.remote_dir)
            log_local = j_local / "job.log"
            if self.ssh is not None:
                for fn in ("job.log", "status.json", "job.fchk", "custodian.json"):
                    try:
                        self.ssh.download_file(r_dir / fn, j_local / fn)
                    except Exception:
                        pass
            if log_local.exists():
                result = parse_gaussian_log(log_local, job_id=job.job_id)
                result.fixes = json.loads(job.fixes) if job.fixes else []
                res_dir = self.projects_root / job.project_id / "results"
                res_dir.mkdir(parents=True, exist_ok=True)
                res_path = res_dir / f"{job.job_id}.json"
                res_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                job.result_path = str(res_path)
                self.store.upsert_job(job)
        elif job.job_kind == "search":
            j_local = Path(job.local_dir)
            r_dir = PurePosixPath(job.remote_dir)
            if self.ssh is not None:
                for fn in ("candidates.xyz", "status.json"):
                    try:
                        self.ssh.download_file(r_dir / fn, j_local / fn)
                    except Exception:
                        pass

    def _calibrate_from_completed(self) -> None:
        done_jobs = self.store.list_jobs(status="done")
        obs: list[tuple[int, list[str], int, float]] = []
        for j in done_jobs:
            if j.job_kind != "gaussian" or j.duration_seconds is None:
                continue
            actual_ch = (j.duration_seconds / 3600.0) * float(_job_nproc(j))
            obs.append((40, ["opt"], j.multiplicity, actual_ch))
        if obs:
            self.cost_model = calibrate_cost_model(obs)

    def step(self, *, project_id: str | None = None) -> dict[str, int]:
        """Run one scheduler tick: reconcile, collect, advance stages, and submit queued jobs."""
        self._refresh_probe_if_needed()
        # 1. Reconcile running jobs
        before_running = {
            j.job_id for j in self.store.list_jobs(project_id=project_id, status="running")
        }
        reconciled = self.store.reconcile(self.runner, project_id=project_id)
        collected = 0
        for j in reconciled:
            if j.job_id in before_running and j.status in {"done", "needs_human"}:
                self._collect_finished_job(j)
                collected += 1

        if collected:
            self._calibrate_from_completed()

        # 2. Advance active projects
        projects = (
            [self.store.get_project(project_id)]
            if project_id is not None
            else self.store.list_projects()
        )
        initial_running = self.store.list_jobs(status="running")
        alloc = (
            self.resource_manager.plan(
                self.probe,
                active_jobs=len(initial_running),
                active_cores=sum(_job_nproc(j) for j in initial_running),
            )
            if self.probe is not None
            else None
        )
        nproc = alloc.nproc_per_job if alloc else 4
        mem_gb = alloc.mem_gb_per_job if alloc else 8

        # Clean .rwf on completed jobs if scratch space is tight
        if alloc and alloc.needs_scratch_cleanup and self.ssh is not None:
            for done_j in self.store.list_jobs(status="done"):
                if done_j.remote_dir:
                    try:
                        self.ssh.clean_rwf_files(done_j.remote_dir)
                    except Exception:
                        pass

        enqueued = 0
        for proj in projects:
            if proj is None or proj.status != "running":
                continue
            added = advance_pipeline(
                proj,
                self.store,
                project_dir=self.projects_root / proj.project_id,
                remote_work_root=self.remote_work_root,
                probe=self.probe,
                remote_python=self.remote_python,
                nproc=nproc,
                mem_gb=mem_gb,
            )
            enqueued += len(added)

        # 3. Submit queued jobs up to concurrency limit (skipping paused projects)
        running_jobs = self.store.list_jobs(status="running")
        running_count = len(running_jobs)
        running_cores = sum(_job_nproc(j) for j in running_jobs)
        queued_jobs = self.store.list_jobs(project_id=project_id, status="queued")
        eligible_queued: list[JobRecord] = []
        for qj in queued_jobs:
            proj = self.store.get_project(qj.project_id)
            if proj is not None and proj.status == "paused":
                continue
            eligible_queued.append(qj)

        submitted = 0
        for idx, qj in enumerate(eligible_queued):
            assigned_nproc: int | None = None
            assigned_mem_gb: int | None = None
            if self.probe is None:
                if submitted >= 4:
                    break
            else:
                remaining_pending = len(eligible_queued) - idx
                job_alloc = self.resource_manager.plan(
                    self.probe,
                    active_jobs=running_count,
                    active_cores=running_cores,
                    pending_jobs=remaining_pending,
                    atom_count=_job_atom_count(qj),
                )
                if job_alloc.allowed_new_jobs <= 0:
                    break
                if qj.job_kind == "gaussian":
                    if qj.stage == "S0_reference":
                        assigned_nproc = min(2, job_alloc.nproc_per_job)
                        assigned_mem_gb = min(4, job_alloc.mem_gb_per_job)
                    else:
                        assigned_nproc = job_alloc.nproc_per_job
                        assigned_mem_gb = job_alloc.mem_gb_per_job
                    gjf_path = Path(qj.local_dir) / "job.gjf"
                    if gjf_path.exists():
                        update_gaussian_link0_resources(
                            gjf_path,
                            nproc=assigned_nproc,
                            mem_gb=assigned_mem_gb,
                        )
                else:
                    assigned_nproc = 1
                    assigned_mem_gb = job_alloc.mem_gb_per_job

            handle: JobHandle = self.runner.submit(
                qj.job_id,
                Path(qj.local_dir),
                Path(qj.remote_dir),
                qj.command,
            )
            if assigned_nproc is not None and assigned_mem_gb is not None:
                meta = _parse_job_meta(qj)
                meta["nproc"] = assigned_nproc
                meta["mem_gb"] = assigned_mem_gb
                qj.meta_json = json.dumps(meta, ensure_ascii=False)
                running_cores += assigned_nproc
            qj.status = "running"
            qj.pid = handle.pid
            qj.attempts += 1
            self.store.upsert_job(qj)
            running_count += 1
            submitted += 1

        return {"collected": collected, "enqueued": enqueued, "submitted": submitted}

    def run_loop(
        self,
        *,
        project_id: str | None = None,
        poll_interval: float = 10.0,
        max_ticks: int | None = None,
    ) -> None:
        """Continuously execute scheduler ticks until stopped or all projects finish."""
        tick = 0
        while not self._stop_requested:
            try:
                self.step(project_id=project_id)
            except Exception as exc:
                print(
                    f"[qcai worker] tick error (will retry): {type(exc).__name__}: {exc}",
                    flush=True,
                )
                if self.ssh is not None:
                    try:
                        self.ssh.close()
                    except Exception:
                        pass
            tick += 1
            if max_ticks is not None and tick >= max_ticks:
                break
            active = self.store.list_jobs(project_id=project_id, status="running")
            queued = self.store.list_jobs(project_id=project_id, status="queued")
            if project_id is not None:
                proj = self.store.get_project(project_id)
                if (
                    proj is not None
                    and proj.status in {"completed", "failed", "needs_human"}
                    and not active
                    and not queued
                ):
                    break
            time.sleep(poll_interval)

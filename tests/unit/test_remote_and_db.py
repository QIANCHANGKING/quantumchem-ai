"""Unit tests for P3 remote execution, security, ResourceManager, handlers, and DB reconciliation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest
from typer.testing import CliRunner

from qcai.cli import app
from qcai.config import SSHSettings
from qcai.pipeline.db import JobRecord, JobStore
from qcai.remote import (
    DirectRunner,
    MockRunner,
    ResourceManager,
    SecurityError,
    ServerProbe,
    SSHClient,
    validate_remote_path,
)
from qcai.remote.resources import OtherUsersLoad
from qcai_remote.handlers import (
    ImaginaryFreqHandler,
    InstabilityHandler,
    restore_gjf_tail_if_lost,
    upgrade_scf_route_line,
)


@dataclass
class _FakeExecResult:
    exited: int = 0
    stdout: str = ""
    stderr: str = ""


class _FakeFabricConn:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.files: dict[str, str] = {}
        self.ps_alive = True

    def run(
        self,
        cmd: str,
        hide: bool = True,
        warn: bool = True,
        in_stream: bool = False,
    ) -> _FakeExecResult:
        self.commands.append(cmd)
        if "nohup " in cmd:
            return _FakeExecResult(0, "43210\n", "")
        if cmd.startswith("ps "):
            if self.ps_alive:
                return _FakeExecResult(
                    0, "  PID USER     ELAPSED S COMMAND\n43210 user 00:10 R python\n", ""
                )
            return _FakeExecResult(1, "", "")
        if cmd.startswith("cat "):
            target = cmd.split("cat ", 1)[1].strip().strip("'")
            if target in self.files:
                return _FakeExecResult(0, self.files[target], "")
            return _FakeExecResult(1, "", "No such file")
        return _FakeExecResult(0, "", "")

    def put(self, local: str, remote: str) -> None:
        self.files[remote] = Path(local).read_text(encoding="utf-8")

    def get(self, remote: str, local: str) -> None:
        Path(local).write_text(self.files[remote], encoding="utf-8")

    def close(self) -> None:
        pass


def test_ssh_path_isolation_and_whitelist() -> None:
    root = "/home/user/qcai_work"
    assert validate_remote_path("/home/user/qcai_work/proj/j1", root) == PurePosixPath(
        "/home/user/qcai_work/proj/j1"
    )
    with pytest.raises(SecurityError):
        validate_remote_path("/home/user/qcai_work/../etc/passwd", root)
    with pytest.raises(SecurityError):
        validate_remote_path("/tmp/outside", root)
    with pytest.raises(SecurityError):
        validate_remote_path(root, root, allow_root=False)

    fake = _FakeFabricConn()
    ssh = SSHClient(SSHSettings(host="h", username="u", work_root=root), connection=fake)
    with pytest.raises(SecurityError):
        ssh.launch_background("/home/user/qcai_work/j1", "rm -rf /")
    with pytest.raises(SecurityError):
        ssh.query_ps("ps -ef; rm -rf /")
    with pytest.raises(SecurityError):
        ssh.kill_process_group("123;whoami")
    with pytest.raises(SecurityError):
        ssh.clean_rwf_files(root)


def test_resource_manager_numa_and_throttling() -> None:
    rm = ResourceManager(
        min_mem_per_job_gb=4.0, mem_per_disk_slot_gb=10.0, min_scratch_free_gb=20.0
    )
    probe = ServerProbe(
        physical_cores=32,
        logical_cores=64,
        numa_nodes=2,
        cores_per_numa=[16, 16],
        total_mem_gb=128.0,
        available_mem_gb=100.0,
        load_avg=[2.0, 2.0, 2.0],
        scratch_free_gb=200.0,
        other_users=OtherUsersLoad(other_user_process_count=0, estimated_other_busy_cores=0.0),
    )
    alloc = rm.plan(probe, active_jobs=1, atom_count=13)
    assert alloc.nproc_per_job == 8
    assert alloc.nproc_per_job <= 16  # Never crosses NUMA node
    assert alloc.max_concurrent_jobs == 3  # (32 - 1) // 8 = 3
    assert alloc.allowed_new_jobs == 2
    assert alloc.needs_scratch_cleanup is False

    # High load stops new jobs
    busy_probe = probe.model_copy(update={"load_avg": [31.5, 30.0, 28.0]})
    busy_alloc = rm.plan(busy_probe, active_jobs=1)
    assert busy_alloc.allowed_new_jobs == 0
    assert busy_alloc.throttle_reason is not None

    # Low scratch triggers cleanup flag and pauses submissions
    low_disk = probe.model_copy(update={"scratch_free_gb": 12.0})
    disk_alloc = rm.plan(low_disk, active_jobs=0)
    assert disk_alloc.allowed_new_jobs == 0
    assert disk_alloc.needs_scratch_cleanup is True


def test_resource_manager_elastic_scaling() -> None:
    rm = ResourceManager()
    probe = ServerProbe(
        physical_cores=48,
        logical_cores=96,
        numa_nodes=2,
        cores_per_numa=[24, 24],
        total_mem_gb=251.0,
        available_mem_gb=230.0,
        load_avg=[4.0, 3.5, 3.0],
        scratch_free_gb=500.0,
        other_users=OtherUsersLoad(other_user_process_count=0, estimated_other_busy_cores=0.0),
    )

    # Baseline (pending_jobs=None) stays backward-compatible
    baseline = rm.plan(probe, atom_count=6)
    assert baseline.nproc_per_job == 4
    assert baseline.elastic_scaled is False

    # 3 pending jobs -> 47 // 3 = 15 -> snapped to even 14 cores
    alloc3 = rm.plan(probe, active_jobs=0, active_cores=0, pending_jobs=3, atom_count=6)
    assert alloc3.nproc_per_job == 14
    assert alloc3.allowed_new_jobs == 3
    assert alloc3.elastic_scaled is True
    assert alloc3.mem_gb_per_job <= 42

    # 2 pending jobs -> capped at max_nproc_per_job=16
    alloc2 = rm.plan(probe, active_jobs=0, active_cores=0, pending_jobs=2, atom_count=6)
    assert alloc2.nproc_per_job == 16
    assert alloc2.allowed_new_jobs == 2
    assert alloc2.elastic_scaled is True

    # 12 pending jobs -> busy queue keeps baseline 4 cores & allows max 11 concurrent jobs
    alloc12 = rm.plan(probe, active_jobs=0, active_cores=0, pending_jobs=12, atom_count=6)
    assert alloc12.nproc_per_job == 4
    assert alloc12.max_concurrent_jobs == 11
    assert alloc12.elastic_scaled is False

    # Quiet -> Busy transition: 2 wide jobs using 32 cores leave 15 cores for 10 pending jobs
    q2b = rm.plan(probe, active_jobs=2, active_cores=32, pending_jobs=10, atom_count=6)
    assert q2b.nproc_per_job == 4
    assert q2b.allowed_new_jobs == 3  # 32 + 3*4 = 44 <= 47
    assert q2b.elastic_scaled is False

    # Busy -> Quiet tail: 8 jobs using 32 cores leave 15 cores for 1 final pending job
    b2q = rm.plan(probe, active_jobs=8, active_cores=32, pending_jobs=1, atom_count=6)
    assert b2q.nproc_per_job == 14
    assert b2q.allowed_new_jobs == 1  # 32 + 14 = 46 <= 47
    assert b2q.elastic_scaled is True

    # Respects NUMA boundary even when queue is quiet
    small_numa = probe.model_copy(update={"physical_cores": 16, "cores_per_numa": [8, 8]})
    numa_alloc = rm.plan(small_numa, active_jobs=0, active_cores=0, pending_jobs=1, atom_count=6)
    assert numa_alloc.nproc_per_job == 8


def test_custom_custodian_handlers(tmp_path: Path) -> None:
    gjf = tmp_path / "job.gjf"
    gjf.write_text(
        "#p PBEPBE/def2SVP freq nosymm\n\nAu4\n\n0 1\n"
        "Au  -1.350000  0.000000  0.000000\n"
        "Au   1.350000  0.000000  0.000000\n"
        "Au   0.000000  1.350000  0.000000\n"
        "Au   0.000000 -1.350000  0.000000\n\n",
        encoding="utf-8",
    )
    log = tmp_path / "job.log"
    log.write_text(
        "Harmonic frequencies (cm**-1)\n"
        " Frequencies --   -84.2150   45.1200\n"
        " Atom  AN      X      Y      Z\n"
        "   1   79     0.00   0.00   0.50\n"
        "   2   79     0.00   0.00  -0.50\n"
        "   3   79     0.00   0.00   0.50\n"
        "   4   79     0.00   0.00  -0.50\n"
        "Normal termination of Gaussian 16.\n",
        encoding="utf-8",
    )
    freq_h = ImaginaryFreqHandler(input_file=str(gjf), output_file=str(log))
    assert freq_h.check() is True
    fix = freq_h.correct()
    assert fix["errors"] == ["imaginary_freq"]
    updated_gjf = gjf.read_text(encoding="utf-8")
    assert " opt" in updated_gjf.lower()
    assert "0.125000" in updated_gjf  # 0.50 * 0.25 step

    # Instability handler
    log.write_text("The wavefunction has an RHF -> UHF instability.\n", encoding="utf-8")
    inst_h = InstabilityHandler(input_file=str(gjf), output_file=str(log))
    assert inst_h.check() is True
    inst_h.correct()
    assert "stable=opt" in gjf.read_text(encoding="utf-8")

    # Already re-stabilized -> should not trigger
    log.write_text(
        "The wavefunction has an RHF -> UHF instability.\nThe wavefunction is stable.\n",
        encoding="utf-8",
    )
    assert inst_h.check() is False


def test_mock_runner_fault_repair_and_db_reconciliation(tmp_path: Path) -> None:
    db_path = tmp_path / "qcai.sqlite"
    store = JobStore(db_path)
    runner = MockRunner(max_repairs=2)

    runner.inject_fault("j_repair", "scf_l502", recoverable=True, repair_steps=1)
    runner.inject_fault("j_fatal", "opt_l9999", recoverable=False, repair_steps=3)

    for jid in ("j_ok", "j_repair", "j_fatal"):
        jdir = tmp_path / jid
        jdir.mkdir()
        handle = runner.submit(jid, jdir, Path(f"/mock/p1/{jid}"), "")
        store.upsert_job(
            JobRecord(
                job_id=jid,
                project_id="p1",
                stage="S4_refine",
                cluster_label="Al4",
                status="running",
                pid=handle.pid,
                remote_dir=handle.remote_dir.as_posix(),
                local_dir=str(jdir),
            )
        )

    # First reconcile: j_ok -> done, j_repair -> running (repairing), j_fatal -> running
    store.reconcile(runner, project_id="p1")
    assert store.get_job("j_ok").status == "done"  # type: ignore[union-attr]
    assert store.get_job("j_repair").status == "running"  # type: ignore[union-attr]

    # Simulate process restart by opening a fresh JobStore instance
    store2 = JobStore(db_path)
    store2.reconcile(runner, project_id="p1")
    store2.reconcile(runner, project_id="p1")
    store2.reconcile(runner, project_id="p1")

    repaired = store2.get_job("j_repair")
    fatal = store2.get_job("j_fatal")
    assert repaired is not None and repaired.status == "done"
    assert len(json.loads(repaired.fixes)) == 1
    assert fatal is not None and fatal.status == "needs_human"
    assert "Exceeded max repairs" in (fatal.error_message or "")


def test_direct_runner_fake_ssh_submit_poll_crash_and_cancel(tmp_path: Path) -> None:
    root = "/home/user/qcai_work"
    fake = _FakeFabricConn()
    ssh = SSHClient(SSHSettings(host="h", username="u", work_root=root), connection=fake)
    runner = DirectRunner(ssh, remote_python="/opt/qcai/bin/python")

    local_dir = tmp_path / "j1"
    local_dir.mkdir()
    (local_dir / "job.gjf").write_text("#p sp\n", encoding="utf-8")
    (local_dir / "job.json").write_text("{}", encoding="utf-8")
    (local_dir / "job.log").write_text("stale error\n", encoding="utf-8")

    r_dir = Path(f"{root}/proj/j1")
    handle = runner.submit("j1", local_dir, r_dir, "")
    assert handle.pid == "43210"
    assert f"{root}/proj/j1/job.log" not in fake.files
    assert json.loads(fake.files[f"{root}/proj/j1/status.json"])["state"] == "queued"
    assert "</dev/null" in fake.files[f"{root}/proj/j1/submit.sh"]
    assert any(
        "&& { nohup " in c and "</dev/null" in c and c.endswith("; }") for c in fake.commands
    )

    # Simulate running status.json while PID is alive -> running
    fake.files[f"{root}/proj/j1/status.json"] = json.dumps({"state": "running", "fixes": []})
    assert runner.poll(handle).state == "running"

    # Simulate remote process crash (ps no longer finds PID while status.json says running)
    fake.ps_alive = False
    crashed = runner.poll(handle)
    assert crashed.state == "failed"

    assert runner.cancel(handle) is True
    assert any("kill -TERM -- -43210" in c for c in fake.commands)


def test_cli_doctor_local_only(tmp_path: Path) -> None:
    doc = tmp_path / "env.md"
    runner = CliRunner()
    res = runner.invoke(app, ["doctor", "--local-only", "--out", str(doc)])
    assert res.exit_code == 0
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "环境诊断报告" in text
    assert "Python 运行时" in text


def test_gjf_tail_preservation_and_scf_escalation() -> None:
    original_gjf = (
        "%chk=job.chk\n"
        "%mem=4GB\n"
        "%nprocshared=2\n"
        "#P UPBE1PBE/GenECP EmpiricalDispersion=GD3BJ nosymm\n"
        " scf=(xqc,maxcycle=500) opt\n\n"
        "TbAu5 q=0 M=6\n\n"
        "0 6\n"
        "Tb 0.000000 0.000000 0.000000\n"
        "Au 2.700000 0.000000 0.000000\n\n"
        "Tb     0\n"
        "S    1   1.00\n"
        "  1.000 1.000\n"
        "****\n\n"
        "TB     0\n"
        "TB-ECP     5     28\n"
        "f potential\n"
        "  1\n"
        "2 1.0 1.0\n\n"
        "--Link1--\n"
        "%chk=job.chk\n"
        "#P UPBE1PBE/chkbasis geom=allcheck guess=read scf=(xqc,maxcycle=500) freq\n\n"
    )
    stripped_gjf = (
        "%chk=job.chk\n"
        "%mem=4GB\n"
        "%nprocshared=2\n"
        "#P UPBE1PBE/Gen empiricaldispersion=gd3bj nosymm scf=(maxcycle=100,xqc) opt\n\n"
        "TbAu5 q=0 M=6\n\n"
        "0 6\n"
        "Tb 0.000000 0.000000 0.000000\n"
        "Au 2.700000 0.000000 0.000000\n\n"
    )

    restored = restore_gjf_tail_if_lost(original_gjf, stripped_gjf)
    assert "#P UPBE1PBE/GenECP" in restored
    assert "TB-ECP     5     28" in restored
    assert "****" in restored
    assert "--Link1--" in restored
    assert "freq" in restored

    step0, kw0 = upgrade_scf_route_line(original_gjf, 0)
    assert kw0 == "scf=(xqc,maxcycle=512,vshift=500,fermi,novaracc)"
    assert step0.count(kw0) == 2
    assert "TB-ECP     5     28" in step0
    assert "--Link1--" in step0

    # Passing step0 with attempt_index=0 skips the already-active strategy
    dedup, kw_dedup = upgrade_scf_route_line(step0, 0)
    assert kw_dedup == "scf=(xqc,maxcycle=512,vshift=800,fermi,novaracc,ndamp=30)"
    assert dedup.count(kw_dedup) == 2

    step1, kw1 = upgrade_scf_route_line(step0, 1)
    assert kw1 == "scf=(xqc,maxcycle=512,vshift=800,fermi,novaracc,ndamp=30)"
    assert step1.count(kw1) == 2

    step2, kw2 = upgrade_scf_route_line(step1, 5)
    assert kw2 == "scf=(maxcycle=512,vshift=1000,fermi,novaracc,ndamp=40)"
    assert step2.count(kw2) == 2
    assert "TB-ECP     5     28" in step2


def test_ssh_client_reconnects_on_transient_connection_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0, "closed": 0}

    class _DroppingConn:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            attempts["count"] += 1
            self.idx = attempts["count"]
            self.transport = None

        def run(self, cmd: str, **kwargs: object) -> _FakeExecResult:
            del cmd, kwargs
            if self.idx == 1:
                raise ConnectionResetError(10054, "Connection reset by peer")
            return _FakeExecResult(0, '{"state": "running"}', "")

        def close(self) -> None:
            attempts["closed"] += 1

    monkeypatch.setattr("qcai.remote.ssh.Connection", _DroppingConn)
    ssh = SSHClient(SSHSettings(host="h", username="u", work_root="/home/user/qcai_work"))
    text = ssh.read_remote_text("/home/user/qcai_work/p1/j1/status.json")
    assert text == '{"state": "running"}'
    assert attempts["count"] == 2
    assert attempts["closed"] == 1


def test_direct_runner_poll_handles_exit_toctou_race(tmp_path: Path) -> None:
    root = "/home/user/qcai_work"
    status_path = f"{root}/proj/j_race/status.json"

    class _RaceConn(_FakeFabricConn):
        def run(
            self,
            cmd: str,
            hide: bool = True,
            warn: bool = True,
            in_stream: bool = False,
        ) -> _FakeExecResult:
            if cmd.startswith("ps "):
                # Simulate remote run_job finishing and writing status.json="done" as PID exits.
                self.files[status_path] = json.dumps(
                    {"state": "done", "phase": "finished", "pid": 43210, "fixes": []}
                )
                return _FakeExecResult(1, "", "")
            return super().run(cmd, hide=hide, warn=warn, in_stream=in_stream)

    fake = _RaceConn()
    ssh = SSHClient(SSHSettings(host="h", username="u", work_root=root), connection=fake)
    runner = DirectRunner(ssh, remote_python="/opt/qcai/bin/python")

    local_dir = tmp_path / "j_race"
    local_dir.mkdir()
    (local_dir / "job.gjf").write_text("#p sp\n", encoding="utf-8")
    (local_dir / "job.json").write_text("{}", encoding="utf-8")

    handle = runner.submit("j_race", local_dir, Path(f"{root}/proj/j_race"), "")
    fake.files[status_path] = json.dumps({"state": "running", "pid": 43210, "fixes": []})
    polled = runner.poll(handle)
    assert polled.state == "done"

    # Real crash: PID is dead and status.json remains "running" after re-read -> failed.
    crash_conn = _FakeFabricConn()
    crash_conn.ps_alive = False
    crash_ssh = SSHClient(
        SSHSettings(host="h", username="u", work_root=root), connection=crash_conn
    )
    crash_runner = DirectRunner(crash_ssh, remote_python="/opt/qcai/bin/python")
    crash_handle = crash_runner.submit("j_crash", local_dir, Path(f"{root}/proj/j_crash"), "")
    crash_conn.files[f"{root}/proj/j_crash/status.json"] = json.dumps(
        {"state": "running", "pid": 43210, "fixes": []}
    )
    crashed = crash_runner.poll(crash_handle)
    assert crashed.state == "failed"
    assert "terminated unexpectedly" in (crashed.message or "")

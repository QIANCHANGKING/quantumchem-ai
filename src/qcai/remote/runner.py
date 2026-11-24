"""Job runners: DirectRunner (SSH + qtoolkit ShellIO) and MockRunner for tests."""

from __future__ import annotations

import json
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

from qtoolkit.core.data_objects import QState
from qtoolkit.io.shell import ShellIO

from qcai.interfaces import RUNNERS
from qcai.interfaces.runner import JobHandle, JobRunner, JobStatus
from qcai.remote.ssh import SSHClient, validate_remote_path

_SKIP_UPLOAD_NAMES = frozenset(
    {
        "status.json",
        "job.log",
        "job.fchk",
        "job.chk",
        "custodian.json",
        "submit.sh",
        "job.out",
        "job.err",
    }
)


class DirectRunner(JobRunner):
    """Submit, poll, and cancel Gaussian jobs directly over SSH without a batch scheduler."""

    name = "direct"

    def __init__(
        self,
        ssh: SSHClient,
        *,
        remote_python: str | None = None,
        remote_pkg_parent: PurePosixPath | None = None,
    ) -> None:
        self.ssh = ssh
        self.remote_python = remote_python
        self.remote_pkg_parent = remote_pkg_parent or (ssh.work_root / "_qcai_remote")
        self.shell_io = ShellIO(stdout_path="job.out", stderr_path="job.err")  # type: ignore[no-untyped-call]

    def submit(
        self,
        job_id: str,
        local_dir: Path,
        remote_dir: Path,
        command: str = "",
    ) -> JobHandle:
        r_dir = PurePosixPath(remote_dir.as_posix())
        safe_dir = validate_remote_path(r_dir, self.ssh.work_root, allow_root=False)
        self.ssh.ensure_dir(safe_dir)

        for item in sorted(Path(local_dir).iterdir()):
            if item.is_file() and item.name not in _SKIP_UPLOAD_NAMES:
                self.ssh.upload_file(item, safe_dir / item.name)

        initial_status = json.dumps(
            {"job_id": job_id, "state": "queued", "fixes": [], "error": None},
            ensure_ascii=False,
            indent=2,
        )
        local_status = Path(local_dir) / "status.json"
        local_status.write_text(initial_status, encoding="utf-8", newline="\n")
        self.ssh.upload_file(local_status, safe_dir / "status.json")

        py = shlex.quote(self.remote_python or "python3")
        run_cmd = command or f"{py} -m qcai_remote.run_job job.json"
        script_body = (
            "#!/bin/bash\n"
            '[ -f "$HOME/.bashrc" ] && source "$HOME/.bashrc" >/dev/null 2>&1 || true\n'
            'export PATH="$HOME/.local/bin:$HOME/bin:$PATH"\n'
            f"export PYTHONPATH={shlex.quote(str(self.remote_pkg_parent))}:${{PYTHONPATH:-}}\n"
            "rm -f job.log job.fchk job.chk custodian.json\n"
            f"exec setsid {run_cmd} </dev/null\n"
        )
        local_submit = Path(local_dir) / "submit.sh"
        local_submit.write_text(script_body, encoding="utf-8", newline="\n")
        self.ssh.upload_file(local_submit, safe_dir / "submit.sh")

        submit_cmd = self.shell_io.get_submit_cmd("submit.sh")
        if "/dev/null" not in submit_cmd:
            if " > " in submit_cmd:
                submit_cmd = submit_cmd.replace(" > ", " </dev/null > ", 1)
            elif " & " in submit_cmd:
                submit_cmd = submit_cmd.replace(" & ", " </dev/null & ", 1)
        res = self.ssh.launch_background(safe_dir, submit_cmd)
        parsed = self.shell_io.parse_submit_output(res.exit_code, res.stdout, res.stderr)
        if parsed.job_id is None:
            raise RuntimeError(
                f"Failed to submit job {job_id!r}: exit={res.exit_code}, stderr={res.stderr}"
            )
        return JobHandle(
            job_id=job_id,
            pid=str(parsed.job_id),
            remote_dir=Path(str(safe_dir)),
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        r_dir = PurePosixPath(handle.remote_dir.as_posix())
        status_raw = self.ssh.read_remote_text(r_dir / "status.json")
        if status_raw is not None:
            data = json.loads(status_raw)
            state = str(data.get("state", "unknown"))
            fixes = [str(f) for f in data.get("fixes", [])]
            msg = data.get("error")
            if state == "running":
                check_pid = str(data.get("pid") or handle.pid or "")
                if check_pid and not self._is_pid_alive(check_pid):
                    # Re-read status.json in case run_job wrote final state just as it exited.
                    recheck_raw = self.ssh.read_remote_text(r_dir / "status.json")
                    if recheck_raw is not None:
                        recheck_data = json.loads(recheck_raw)
                        recheck_state = str(recheck_data.get("state", "unknown"))
                        if recheck_state in {"done", "failed", "cancelled"}:
                            recheck_fixes = [str(f) for f in recheck_data.get("fixes", [])]
                            recheck_msg = recheck_data.get("error")
                            return JobStatus(
                                job_id=handle.job_id,
                                state=recheck_state,  # type: ignore[arg-type]
                                fixes=recheck_fixes,
                                message=str(recheck_msg) if recheck_msg else None,
                            )
                    return JobStatus(
                        job_id=handle.job_id,
                        state="failed",
                        fixes=fixes,
                        message="Remote process terminated unexpectedly before updating status.json",
                    )
            if state in {"queued", "running", "done", "failed", "cancelled"}:
                return JobStatus(
                    job_id=handle.job_id,
                    state=state,  # type: ignore[arg-type]
                    fixes=fixes,
                    message=str(msg) if msg else None,
                )

        if handle.pid and self._is_pid_alive(handle.pid):
            return JobStatus(job_id=handle.job_id, state="running", fixes=[])
        return JobStatus(job_id=handle.job_id, state="unknown", fixes=[])

    def _is_pid_alive(self, pid: str) -> bool:
        ps_cmd = self.shell_io._get_job_cmd(pid)
        res = self.ssh.query_ps(ps_cmd)
        qjob = self.shell_io.parse_job_output(res.exit_code, res.stdout, res.stderr, job_id=pid)
        return qjob is not None and qjob.state in {QState.RUNNING, QState.SUSPENDED}

    def cancel(self, handle: JobHandle) -> bool:
        if not handle.pid:
            return False
        res = self.ssh.kill_process_group(handle.pid)
        return res.exit_code == 0


class MockRunner(JobRunner):
    """In-memory / local mock runner for fault-injection and reconciliation tests."""

    name = "mock"

    def __init__(self, *, max_repairs: int = 2) -> None:
        self.max_repairs = max_repairs
        self._jobs: dict[str, dict[str, Any]] = {}
        self._next_pid = 10000

    def inject_fault(
        self, job_id: str, fault: str, *, recoverable: bool = True, repair_steps: int = 1
    ) -> None:
        """Pre-configure fault behavior for a job before or during polling."""
        self._jobs[job_id] = {
            "fault": fault,
            "recoverable": recoverable,
            "repair_steps": repair_steps,
            "polls": 0,
            "fixes": [],
            "state": "queued",
        }

    def submit(
        self,
        job_id: str,
        local_dir: Path,
        remote_dir: Path,
        command: str = "",
    ) -> JobHandle:
        self._next_pid += 1
        pid = str(self._next_pid)
        entry = self._jobs.setdefault(
            job_id,
            {"fault": None, "recoverable": True, "repair_steps": 0, "polls": 0, "fixes": []},
        )
        entry["state"] = "running"
        entry["pid"] = pid
        return JobHandle(job_id=job_id, pid=pid, remote_dir=remote_dir)

    def poll(self, handle: JobHandle) -> JobStatus:
        entry = self._jobs.get(handle.job_id)
        if entry is None:
            return JobStatus(job_id=handle.job_id, state="unknown", fixes=[])
        if entry["state"] in {"done", "failed", "cancelled"}:
            return JobStatus(
                job_id=handle.job_id,
                state=entry["state"],
                fixes=list(entry["fixes"]),
                message=entry.get("message"),
            )

        entry["polls"] += 1
        fault = entry.get("fault")
        if fault:
            needed = int(entry.get("repair_steps", 1))
            if entry["polls"] <= min(needed, self.max_repairs):
                entry["fixes"].append(f"custodian_fix:{fault}:attempt_{entry['polls']}")
                return JobStatus(
                    job_id=handle.job_id,
                    state="running",
                    fixes=list(entry["fixes"]),
                    message=f"Repairing {fault}",
                )
            if not entry.get("recoverable", True) or needed > self.max_repairs:
                entry["state"] = "failed"
                entry["message"] = f"Exceeded max repairs ({self.max_repairs}) for {fault}"
                return JobStatus(
                    job_id=handle.job_id,
                    state="failed",
                    fixes=list(entry["fixes"]),
                    message=entry["message"],
                )

        entry["state"] = "done"
        return JobStatus(
            job_id=handle.job_id,
            state="done",
            fixes=list(entry["fixes"]),
        )

    def cancel(self, handle: JobHandle) -> bool:
        entry = self._jobs.get(handle.job_id)
        if entry is None:
            return False
        entry["state"] = "cancelled"
        return True


if "mock" not in RUNNERS:
    RUNNERS.register("mock", MockRunner())

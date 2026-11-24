"""Server-side Gaussian job wrapper using custodian, formchk, cubegen, and Multiwfn."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qcai_remote.handlers import (
    ImaginaryFreqHandler,
    InstabilityHandler,
    restore_gjf_tail_if_lost,
    upgrade_scf_route_line,
)


def _write_status(status_path: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = datetime.now(UTC).isoformat()
    tmp = status_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, status_path)


def _format_fixes(custodian_log: Path) -> tuple[list[str], int]:
    if not custodian_log.exists():
        return [], 1
    try:
        entries = json.loads(custodian_log.read_text(encoding="utf-8"))
        fixes: list[str] = []
        for entry in entries:
            for corr in entry.get("corrections") or []:
                errs = corr.get("errors") or []
                acts = corr.get("actions") or []
                if errs or acts:
                    fixes.append(f"errors={errs} -> actions={acts}")
        return fixes, max(1, len(fixes) + 1)
    except Exception:
        return [], 1


def _run_postprocessing(
    job_dir: Path, spec: dict[str, Any], status: dict[str, Any], status_path: Path
) -> None:
    chk_name = str(spec.get("chk_file") or f"{Path(spec.get('gjf_file', 'job.gjf')).stem}.chk")
    chk_path = job_dir / chk_name
    fchk_path = job_dir / f"{chk_path.stem}.fchk"

    if spec.get("run_formchk", True) and chk_path.exists() and shutil.which("formchk"):
        status["phase"] = "formchk"
        _write_status(status_path, status)
        proc = subprocess.run(
            ["formchk", str(chk_path), str(fchk_path)],
            cwd=job_dir,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"formchk failed: {proc.stderr.strip()}")

    cubes = spec.get("cubes", [])
    if cubes and fchk_path.exists() and shutil.which("cubegen"):
        status["phase"] = "cubegen"
        _write_status(status_path, status)
        npts = str(spec.get("cube_grid", "80"))
        for kind in cubes:
            cube_out = job_dir / f"{fchk_path.stem}_{kind.lower().replace('=', '_')}.cube"
            proc = subprocess.run(
                ["cubegen", "0", str(kind), str(fchk_path), str(cube_out), npts, "h"],
                cwd=job_dir,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"cubegen ({kind}) failed: {proc.stderr.strip()}")

    mwfn_tasks = spec.get("multiwfn_tasks", [])
    if mwfn_tasks and fchk_path.exists():
        from qcai_remote.mwfn import run_multiwfn_template

        status["phase"] = "multiwfn"
        _write_status(status_path, status)
        for task in mwfn_tasks:
            tname = str(task["name"])
            run_multiwfn_template(
                fchk_path,
                str(task["stdin"]),
                job_dir / f"mwfn_{tname}.txt",
                extra_rename=task.get("rename"),
            )


def _normalize_gjf_newlines(gjf_path: Path) -> None:
    if gjf_path.exists():
        raw = gjf_path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        gjf_path.write_text(raw.rstrip() + "\n\n", encoding="utf-8", newline="\n")


def run_job(job_json_path: Path) -> int:
    """Run Gaussian job via custodian and execute server-side postprocessing."""
    job_dir = job_json_path.resolve().parent
    spec = json.loads(job_json_path.read_text(encoding="utf-8"))
    job_id = str(spec.get("job_id") or job_dir.name)
    gjf_file = str(spec.get("gjf_file") or "job.gjf")
    _normalize_gjf_newlines(job_dir / gjf_file)
    log_file = str(spec.get("log_file") or "job.log")
    max_errors = int(spec.get("max_errors", 3))
    status_path = job_dir / "status.json"

    status: dict[str, Any] = {
        "job_id": job_id,
        "state": "running",
        "phase": "g16",
        "pid": os.getpid(),
        "attempts": 0,
        "fixes": [],
        "needs_human": False,
        "error": None,
    }
    _write_status(status_path, status)

    try:
        from custodian.custodian import Custodian
        from custodian.gaussian.handlers import GaussianErrorHandler
        from custodian.gaussian.jobs import GaussianJob

        class _SafeGaussianErrorHandler(GaussianErrorHandler):  # type: ignore[misc]
            def check(self, directory: str = "./") -> bool:
                try:
                    return bool(super().check(directory))
                except ValueError:
                    txt = (Path(directory) / self.output_file).read_text(
                        encoding="utf-8", errors="replace"
                    )
                    if "Normal termination of Gaussian" in txt:
                        return False
                    raise

            def correct(self, directory: str = "./") -> dict[str, Any]:
                gjf_path = Path(directory) / self.input_file
                orig_text = (
                    gjf_path.read_text(encoding="utf-8", errors="replace")
                    if gjf_path.exists()
                    else ""
                )
                err_list = list(getattr(self, "errors", []) or [])

                # Lossless fast path for pure SCF convergence: escalate SCF without
                # invoking pymatgen's GaussianInput rewriter (which strips GenECP/--Link1--).
                if err_list and set(err_list) == {"scf_convergence"} and orig_text:
                    attempt = int(getattr(self, "_scf_attempt", 0))
                    new_text, scf_kw = upgrade_scf_route_line(orig_text, attempt)
                    self._scf_attempt = attempt + 1
                    (Path(directory) / f"{self.input_file}.prev").write_text(
                        orig_text, encoding="utf-8", newline="\n"
                    )
                    gjf_path.write_text(new_text, encoding="utf-8", newline="\n")
                    return {"errors": err_list, "actions": [{"scf_strategy": scf_kw}]}

                if getattr(self, "gin", None) is not None:
                    rp = self.gin.route_parameters
                    for key in ("opt", "scf"):
                        if key in rp and not isinstance(rp[key], dict):
                            rp[key] = {}
                result: dict[str, Any] = super().correct(directory)

                if orig_text and gjf_path.exists():
                    rewritten = gjf_path.read_text(encoding="utf-8", errors="replace")
                    fixed = restore_gjf_tail_if_lost(orig_text, rewritten)
                    if "scf_convergence" in err_list:
                        attempt = int(getattr(self, "_scf_attempt", 0))
                        fixed, _ = upgrade_scf_route_line(fixed, attempt)
                        self._scf_attempt = attempt + 1
                    gjf_path.write_text(fixed, encoding="utf-8", newline="\n")
                return result

        handlers = [
            _SafeGaussianErrorHandler(
                input_file=gjf_file,
                output_file=log_file,
                stderr_file="job.err",
            ),
            InstabilityHandler(input_file=gjf_file, output_file=log_file),
            ImaginaryFreqHandler(input_file=gjf_file, output_file=log_file),
        ]
        base_cmd = str(spec.get("gaussian_cmd") or "g16")
        gaussian_cmd = base_cmd if "<" in base_cmd else f"{base_cmd} < {shlex.quote(gjf_file)}"
        jobs = [
            GaussianJob(
                gaussian_cmd=gaussian_cmd,
                input_file=gjf_file,
                output_file=log_file,
                stderr_file="job.err",
            )
        ]
        c = Custodian(handlers=handlers, jobs=jobs, max_errors=max_errors)
        c.run()
        fixes, attempts = _format_fixes(job_dir / "custodian.json")
        status["fixes"] = fixes
        status["attempts"] = attempts
        _run_postprocessing(job_dir, spec, status, status_path)
        status["state"] = "done"
        status["phase"] = "finished"
        _write_status(status_path, status)
        return 0
    except Exception as exc:
        fixes, attempts = _format_fixes(job_dir / "custodian.json")
        status["fixes"] = fixes
        status["attempts"] = attempts
        status["state"] = "failed"
        status["needs_human"] = True
        status["error"] = f"{type(exc).__name__}: {exc}"
        _write_status(status_path, status)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute Gaussian job with custodian.")
    parser.add_argument("job_json", type=Path, help="Path to job.json")
    args = parser.parse_args(argv)
    return run_job(args.job_json)


if __name__ == "__main__":
    raise SystemExit(main())

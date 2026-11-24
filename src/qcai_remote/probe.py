"""Server-side hardware, load, and software probe using psutil and lscpu -J."""

from __future__ import annotations

import argparse
import getpass
import importlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil

_COMPUTE_PROCS = ("g16", "l502", "l9999", "xtb", "multiwfn", "geom", "isomer")


def _probe_numa_lscpu() -> tuple[int, list[int]]:
    """Query NUMA topology via `lscpu -J`; return (numa_nodes, cores_per_node)."""
    try:
        proc = subprocess.run(
            ["lscpu", "-J"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return 1, []
        data = json.loads(proc.stdout)
        numa_nodes = 1
        cores_per_socket: int | None = None
        for item in data.get("lscpu", []):
            field = str(item.get("field", "")).rstrip(":").strip().lower()
            val = str(item.get("data", "")).strip()
            if field == "numa node(s)" and val.isdigit():
                numa_nodes = max(1, int(val))
            elif field == "core(s) per socket" and val.isdigit():
                cores_per_socket = int(val)
        physical = psutil.cpu_count(logical=False) or os.cpu_count() or 1
        if cores_per_socket and numa_nodes >= 1:
            return numa_nodes, [cores_per_socket] * numa_nodes
        per_node = max(1, physical // numa_nodes)
        return numa_nodes, [per_node] * numa_nodes
    except Exception:
        physical = psutil.cpu_count(logical=False) or os.cpu_count() or 1
        return 1, [physical]


def _probe_other_users_compute() -> dict[str, Any]:
    """Inspect active high-CPU processes owned by other users."""
    current_user = getpass.getuser()
    other_procs: list[dict[str, Any]] = []
    other_cpu_pct = 0.0
    try:
        proc = subprocess.run(
            ["ps", "-eo", "user=,pcpu=,comm="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                parts = line.split(None, 2)
                if len(parts) < 3:
                    continue
                user, cpu_s, comm = parts
                if user == current_user:
                    continue
                try:
                    cpu = float(cpu_s)
                except ValueError:
                    continue
                if cpu >= 20.0 or any(tok in comm.lower() for tok in _COMPUTE_PROCS):
                    other_cpu_pct += cpu
                    other_procs.append({"name": comm, "cpu_percent": cpu})
            return {
                "other_user_process_count": len(other_procs),
                "estimated_other_busy_cores": round(other_cpu_pct / 100.0, 2),
            }
    except Exception:
        pass

    for p in psutil.process_iter(["pid", "name", "username", "cpu_percent"]):
        try:
            info = p.info
            name = str(info.get("name") or "").lower()
            user = str(info.get("username") or "")
            if user and user != current_user and any(tok in name for tok in _COMPUTE_PROCS):
                cpu = float(info.get("cpu_percent") or 0.0)
                other_cpu_pct += cpu
                other_procs.append({"name": name, "cpu_percent": cpu})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {
        "other_user_process_count": len(other_procs),
        "estimated_other_busy_cores": round(other_cpu_pct / 100.0, 2),
    }


def _probe_executable(names: list[str], version_args: list[str] | None = None) -> dict[str, Any]:
    for name in names:
        found = shutil.which(name)
        if found:
            ver = None
            if version_args:
                try:
                    proc = subprocess.run(
                        [found, *version_args],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    out = (proc.stdout or proc.stderr or "").strip().splitlines()
                    if out:
                        ver = out[0][:120]
                except Exception:
                    ver = None
            return {"available": True, "path": found, "version": ver}
    return {"available": False, "path": None, "version": None}


def _probe_python_packages(names: list[str]) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            mod = importlib.import_module(name)
            versions[name] = str(getattr(mod, "__version__", "installed"))
        except Exception:
            versions[name] = None
    return versions


def collect_probe(work_root: str | None = None) -> dict[str, Any]:
    """Collect hardware, load, scratch, and software availability metrics."""
    physical_cores = int(psutil.cpu_count(logical=False) or os.cpu_count() or 1)
    logical_cores = int(psutil.cpu_count(logical=True) or physical_cores)
    numa_nodes, cores_per_node = _probe_numa_lscpu()

    vm = psutil.virtual_memory()
    total_mem_gb = round(vm.total / (1024**3), 2)
    available_mem_gb = round(vm.available / (1024**3), 2)

    try:
        load_1m, load_5m, load_15m = os.getloadavg()  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        load_1m = load_5m = load_15m = 0.0

    scratch_dir = os.environ.get("GAUSS_SCRDIR") or work_root or "/tmp"
    scratch_path = Path(scratch_dir)
    if not scratch_path.exists():
        scratch_path = Path(work_root) if work_root and Path(work_root).exists() else Path("/")
    disk = shutil.disk_usage(scratch_path)
    scratch_free_gb = round(disk.free / (1024**3), 2)

    other_compute = _probe_other_users_compute()

    software = {
        "g16": _probe_executable(["g16"]),
        "formchk": _probe_executable(["formchk"]),
        "cubegen": _probe_executable(["cubegen"]),
        "Multiwfn": _probe_executable(["Multiwfn", "multiwfn"]),
        "xtb": _probe_executable(["xtb"], ["--version"]),
        "abcluster_geom": _probe_executable(["geom"]),
        "abcluster_isomer": _probe_executable(["isomer"]),
        "molclus": _probe_executable(["molclus"]),
        "micromamba": _probe_executable(["micromamba"], ["--version"]),
    }

    py_packages = _probe_python_packages(
        ["custodian", "pymatgen", "cclib", "ase", "psutil", "tblite"]
    )

    return {
        "physical_cores": physical_cores,
        "logical_cores": logical_cores,
        "numa_nodes": numa_nodes,
        "cores_per_numa": cores_per_node or [max(1, physical_cores // numa_nodes)],
        "total_mem_gb": total_mem_gb,
        "available_mem_gb": available_mem_gb,
        "load_avg": [round(load_1m, 2), round(load_5m, 2), round(load_15m, 2)],
        "scratch_dir": str(scratch_path),
        "scratch_free_gb": scratch_free_gb,
        "other_users": other_compute,
        "software": software,
        "python_packages": py_packages,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe server resources and software.")
    parser.add_argument("--work-root", default=None, help="Project work root on server.")
    args = parser.parse_args(argv)
    print(json.dumps(collect_probe(work_root=args.work_root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

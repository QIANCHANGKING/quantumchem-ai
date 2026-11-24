"""Server-side P3 capability verification: custodian, tblite, Multiwfn, ABCluster."""

from __future__ import annotations

import inspect
import json
import subprocess
from typing import Any


def check_custodian_gaussian() -> dict[str, Any]:
    from custodian.gaussian.handlers import GaussianErrorHandler
    from custodian.gaussian.jobs import GaussianJob

    src = inspect.getsource(GaussianErrorHandler)
    return {
        "handler_init_sig": str(inspect.signature(GaussianErrorHandler.__init__)),
        "job_init_sig": str(inspect.signature(GaussianJob.__init__)),
        "error_defs": GaussianErrorHandler.error_defs,
        "source_lines": len(src.splitlines()),
    }


def check_tblite_ase() -> dict[str, Any]:
    from ase import Atoms
    from tblite.ase import TBLite

    h2 = Atoms("H2", positions=[(0.0, 0.0, 0.0), (0.0, 0.0, 0.74)])
    h2.calc = TBLite(method="GFN2-xTB", verbosity=0)
    energy = float(h2.get_potential_energy())  # type: ignore[no-untyped-call]
    forces = h2.get_forces().tolist()  # type: ignore[no-untyped-call]
    return {"method": "GFN2-xTB", "h2_energy_ev": energy, "forces": forces}


def check_multiwfn_version() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["Multiwfn"],
            input="q\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        ver_lines = [
            ln for ln in lines[:25] if "Multiwfn" in ln or "Version" in ln or "Release" in ln
        ]
        return {"exit_code": proc.returncode, "banner": ver_lines[:5]}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def check_abcluster_version() -> dict[str, Any]:
    info: dict[str, Any] = {}
    for exe in ("geom", "isomer"):
        try:
            proc = subprocess.run(
                [exe],
                capture_output=True,
                text=True,
                timeout=5,
            )
            out = (proc.stdout or proc.stderr or "").strip().splitlines()
            info[exe] = out[:6]
        except Exception as exc:
            info[exe] = [f"{type(exc).__name__}: {exc}"]
    return info


def main() -> int:
    report = {
        "custodian": check_custodian_gaussian(),
        "tblite": check_tblite_ase(),
        "multiwfn": check_multiwfn_version(),
        "abcluster": check_abcluster_version(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Server-side ASE genetic algorithm + tblite fallback global cluster search."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ase import Atoms
from ase.io import write as ase_write


def run_ase_ga_search(
    composition: dict[str, int],
    out_xyz: Path,
    *,
    charge: int = 0,
    multiplicity: int = 1,
    population_size: int = 12,
    n_generations: int = 4,
    calculator: Any = None,
) -> Path:
    """Run an ASE genetic algorithm global search for atomic clusters using tblite GFN2-xTB."""
    import numpy as np
    from ase.data import atomic_numbers, covalent_radii
    from ase.optimize import BFGS
    from ase_ga.cutandsplicepairing import CutAndSplicePairing
    from ase_ga.data import DataConnection, PrepareDB
    from ase_ga.offspring_creator import OperationSelector
    from ase_ga.population import Population
    from ase_ga.standard_comparators import InteratomicDistanceComparator
    from ase_ga.standardmutations import MirrorMutation, PermutationMutation, RattleMutation
    from ase_ga.startgenerator import StartGenerator
    from ase_ga.utilities import closest_distances_generator, get_all_atom_types

    out_xyz = Path(out_xyz)
    out_xyz.parent.mkdir(parents=True, exist_ok=True)
    db_file = out_xyz.parent / "ga.db"
    if db_file.exists():
        db_file.unlink()

    atom_numbers: list[int] = []
    for sym, cnt in composition.items():
        atom_numbers.extend([int(atomic_numbers[sym])] * int(cnt))

    unique_z = list(dict.fromkeys(atom_numbers))
    r_max = max(float(covalent_radii[z]) for z in unique_z)
    box_len = max(8.0, 2.6 * r_max * (len(atom_numbers) ** (1.0 / 3.0)) + 4.0)
    cell = np.eye(3) * box_len
    slab = Atoms("", cell=cell, pbc=False)
    blmin = closest_distances_generator(atom_numbers=unique_z, ratio_of_covalent_radii=0.65)
    sg = StartGenerator(
        slab=slab,
        blocks=atom_numbers,
        blmin=blmin,
        box_to_place_in=[
            [2.0, 2.0, 2.0],
            [[box_len - 4.0, 0, 0], [0, box_len - 4.0, 0], [0, 0, box_len - 4.0]],
        ],
    )

    if calculator is None:
        from tblite.ase import TBLite

        def _make_calc() -> Any:
            return TBLite(
                method="GFN2-xTB",
                charge=float(charge),
                multiplicity=int(multiplicity),
                verbosity=0,
            )
    else:

        def _make_calc() -> Any:
            return calculator

    PrepareDB(
        db_file_name=str(db_file),
        simulation_cell=slab,
        stoichiometry=atom_numbers,
    )
    conn = DataConnection(str(db_file))
    for _ in range(population_size):
        cand = sg.get_new_candidate()
        if cand is None:
            continue
        cand.calc = _make_calc()
        opt = BFGS(cand, logfile=None)
        opt.run(fmax=0.08, steps=40)  # type: ignore[no-untyped-call]
        e_ev = float(cand.get_potential_energy())
        cand.info["key_value_pairs"] = {"raw_score": -e_ev}
        cand.info["data"] = {}
        conn.add_relaxed_candidate(cand)
    all_atom_types = get_all_atom_types(slab, atom_numbers)
    comp = InteratomicDistanceComparator(
        n_top=len(atom_numbers), pair_cor_cum_diff=0.03, pair_cor_max=0.7, dE=0.05
    )
    pop = Population(data_connection=conn, population_size=population_size, comparator=comp)
    pairing = CutAndSplicePairing(slab, len(atom_numbers), blmin)
    mutations = OperationSelector(
        [1.0, 1.0, 1.0] if len(unique_z) > 1 else [1.5, 1.5],
        [
            RattleMutation(blmin, len(atom_numbers)),
            MirrorMutation(blmin, len(atom_numbers)),
            *([PermutationMutation(len(atom_numbers))] if len(unique_z) > 1 else []),
        ],
    )

    for _gen in range(n_generations):
        for _ in range(max(2, population_size // 2)):
            a1, a2 = pop.get_two_candidates()
            child, _desc = pairing.get_new_individual([a1, a2])
            if child is None:
                child, _ = mutations.get_new_individual([a1])
            elif len(all_atom_types) >= 1 and (_ % 2 == 1):
                mutated, _ = mutations.get_new_individual([a1])
                if mutated is not None:
                    child = mutated
            if child is None:
                continue
            child.calc = _make_calc()
            opt = BFGS(child, logfile=None)
            opt.run(fmax=0.08, steps=40)  # type: ignore[no-untyped-call]
            e_ev = float(child.get_potential_energy())
            child.info["key_value_pairs"] = {"raw_score": -e_ev}
            child.info["data"] = {}
            conn.add_relaxed_candidate(child)
        pop.update()

    # Export all relaxed structures sorted by energy (stored in comment as eV)
    relaxed = list(conn.get_all_relaxed_candidates())
    relaxed.sort(key=lambda a: float(a.get_potential_energy()))
    for atoms in relaxed:
        e_ev = float(atoms.get_potential_energy())
        atoms.info["comment"] = f"energy={e_ev:.8f} eV"
    ase_write(str(out_xyz), relaxed, format="extxyz")
    return out_xyz


def _write_status(status_path: Path, payload: dict[str, Any]) -> None:
    import os
    from datetime import UTC, datetime

    payload["updated_at"] = datetime.now(UTC).isoformat()
    tmp = status_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, status_path)


def _run_abcluster_isomer(work_dir: Path, inp_file: str, result_name: str, out_xyz: Path) -> None:
    import shutil
    import subprocess

    proc = subprocess.run(
        ["isomer", inp_file],
        cwd=work_dir,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ABCluster isomer failed: {proc.stderr or proc.stdout}")
    lm_dir = work_dir / f"{result_name}-LM"
    xyzs = sorted(lm_dir.glob("*.xyz"), key=lambda f: int(f.stem) if f.stem.isdigit() else 10**9)
    if not xyzs:
        raise RuntimeError(f"ABCluster produced no structures in {lm_dir}")
    chunks = [p.read_text(encoding="utf-8", errors="replace").strip() for p in xyzs]
    out_xyz.write_text("\n".join(chunks) + "\n", encoding="utf-8", newline="\n")
    if shutil.which("rm") is None:
        return


def main(argv: list[str] | None = None) -> int:
    import os

    parser = argparse.ArgumentParser(description="Run server-side structure search job.")
    parser.add_argument("search_json", type=Path)
    args = parser.parse_args(argv)
    cfg = json.loads(args.search_json.read_text(encoding="utf-8"))
    work_dir = args.search_json.resolve().parent
    status_path = work_dir / "status.json"
    status: dict[str, Any] = {
        "job_id": str(cfg.get("job_id") or work_dir.name),
        "state": "running",
        "phase": "search",
        "pid": os.getpid(),
        "fixes": [],
        "error": None,
    }
    _write_status(status_path, status)
    out_xyz = work_dir / str(cfg.get("out_xyz", "candidates.xyz"))
    try:
        engine = str(cfg.get("engine", "ase_ga"))
        if engine == "abcluster":
            try:
                _run_abcluster_isomer(
                    work_dir,
                    str(cfg.get("inp_file", "abc.inp")),
                    str(cfg.get("result_name", "abc")),
                    out_xyz,
                )
            except Exception as exc:
                status["fixes"].append(f"abcluster_fallback_ase_ga: {exc}")
                run_ase_ga_search(
                    composition=cfg["composition"],
                    out_xyz=out_xyz,
                    charge=int(cfg.get("charge", 0)),
                    multiplicity=int(cfg.get("multiplicity", 1)),
                    population_size=int(cfg.get("population_size", 12)),
                    n_generations=int(cfg.get("n_generations", 4)),
                )
        else:
            run_ase_ga_search(
                composition=cfg["composition"],
                out_xyz=out_xyz,
                charge=int(cfg.get("charge", 0)),
                multiplicity=int(cfg.get("multiplicity", 1)),
                population_size=int(cfg.get("population_size", 12)),
                n_generations=int(cfg.get("n_generations", 4)),
            )
        status["state"] = "done"
        status["phase"] = "finished"
        _write_status(status_path, status)
        return 0
    except Exception as exc:
        status["state"] = "failed"
        status["error"] = f"{type(exc).__name__}: {exc}"
        _write_status(status_path, status)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

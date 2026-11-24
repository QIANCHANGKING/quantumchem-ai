"""Structure generators implementing StructureGenerator interface (Section 6.1)."""

from __future__ import annotations

import shutil
from pathlib import Path

from qcai.core.models import Cluster
from qcai.core.physics import covalent_radius
from qcai.interfaces import GENERATORS, StructureGenerator
from qcai.remote.resources import ServerProbe
from qcai.structure.readers import ScoredCluster, read_abcluster_lm_dir, read_clusters_from_file


class ImportGenerator(StructureGenerator):
    """User-supplied initial cluster geometries (highest priority)."""

    name = "import"
    priority = 10

    def __init__(self, structures: list[Cluster] | None = None) -> None:
        self._structures = list(structures or [])

    def is_available(self) -> bool:
        return bool(self._structures)

    def generate(
        self,
        composition: dict[str, int],
        *,
        max_candidates: int = 20,
        charge: int = 0,
        multiplicity: int = 1,
    ) -> list[Cluster]:
        return list(self._structures[:max_candidates])


class ABClusterGenerator(StructureGenerator):
    """Adapter generating ABCluster `isomer` + `runxTB.sh` inputs and reading `-LM/*.xyz`."""

    name = "abcluster"
    priority = 20

    def __init__(self, available: bool | None = None) -> None:
        self._available = available

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        return shutil.which("isomer") is not None

    @staticmethod
    def build_isomer_files(
        composition: dict[str, int],
        work_dir: Path,
        *,
        result_name: str = "abc",
        max_calcs: int = 60,
        charge: int = 0,
        multiplicity: int = 1,
        gfn: int = 2,
    ) -> tuple[Path, Path]:
        """Generate `isomer` input and `runxTB.sh` matching ABCluster official testfiles."""
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        symbols_str = " ".join(f"{el} {cnt}" for el, cnt in composition.items())
        n_total = sum(composition.values())
        avg_r = sum(covalent_radius(el) * cnt for el, cnt in composition.items()) / max(1, n_total)
        side = max(2, int(round((n_total ** (1.0 / 3.0)) * avg_r * 1.4)))

        inp_text = (
            f"{result_name}          # Result file name\n"
            f"{symbols_str}          # Symbols\n"
            f"cube {side} {side} {side}  # Structure types\n"
            f"{max_calcs}            # Maximal number of calculations\n"
            ">>>>\n"
            "bash runxTB.sh $inp$ $out$ $xxx$\n"
            ">>>>\n"
        )
        uhf = max(0, multiplicity - 1)
        run_xtb = (
            "#!/bin/bash\n"
            'TMPD="tmp_${3}_$$"\n'
            'mkdir -p "$TMPD"\n'
            'cp "$1" "$TMPD/in.xyz"\n'
            f'(cd "$TMPD" && OMP_NUM_THREADS=1 xtb --opt --chrg {charge} --uhf {uhf} --gfn {gfn} in.xyz > xtb.out 2>&1)\n'
            'if [ -f "$TMPD/xtbopt.xyz" ]; then\n'
            '  energy=$(awk \'NR==2{for(i=1;i<=NF;i++) if($i=="energy:"){print $(i+1); exit} print $2}\' "$TMPD/xtbopt.xyz")\n'
            '  [ -z "$energy" ] && energy="99999.0"\n'
            '  sed "2s/^.*/${energy}/g" "$TMPD/xtbopt.xyz" > "$2"\n'
            "else\n"
            '  sed "2s/^.*/99999.0/g" "$1" > "$2"\n'
            "fi\n"
            'rm -rf "$TMPD"\n'
        )
        inp_path = work_dir / f"{result_name}.inp"
        sh_path = work_dir / "runxTB.sh"
        inp_path.write_text(inp_text, encoding="utf-8", newline="\n")
        sh_path.write_text(run_xtb, encoding="utf-8", newline="\n")
        return inp_path, sh_path

    @staticmethod
    def parse_results(work_dir: Path, *, result_name: str = "abc") -> list[ScoredCluster]:
        return read_abcluster_lm_dir(Path(work_dir) / f"{result_name}-LM")

    def generate(
        self,
        composition: dict[str, int],
        *,
        max_candidates: int = 20,
        charge: int = 0,
        multiplicity: int = 1,
    ) -> list[Cluster]:
        raise RuntimeError(
            "ABClusterGenerator runs remotely on the Linux server; "
            "use build_isomer_files() + server execution or PipelineWorker."
        )


class MolclusGenerator(StructureGenerator):
    """Optional molclus adapter reading `isomers.xyz` and writing gentor config."""

    name = "molclus"
    priority = 30

    def __init__(self, available: bool | None = None) -> None:
        self._available = available

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        return shutil.which("molclus") is not None

    @staticmethod
    def parse_results(isomers_xyz: Path) -> list[ScoredCluster]:
        items = read_clusters_from_file(isomers_xyz, label_prefix="molclus")
        items.sort(
            key=lambda sc: sc.energy_hartree if sc.energy_hartree is not None else float("inf")
        )
        return items

    def generate(
        self,
        composition: dict[str, int],
        *,
        max_candidates: int = 20,
        charge: int = 0,
        multiplicity: int = 1,
    ) -> list[Cluster]:
        raise RuntimeError(
            "MolclusGenerator runs remotely on the Linux server; "
            "use parse_results() after remote execution."
        )


class AseGaGenerator(StructureGenerator):
    """Fallback ASE genetic algorithm + tblite generator (can also run locally for small tests)."""

    name = "ase_ga"
    priority = 40

    def is_available(self) -> bool:
        try:
            import ase_ga  # noqa: F401

            return True
        except ImportError:
            return False

    def generate(
        self,
        composition: dict[str, int],
        *,
        max_candidates: int = 20,
        charge: int = 0,
        multiplicity: int = 1,
    ) -> list[Cluster]:
        import tempfile

        from qcai_remote.search import run_ase_ga_search

        with tempfile.TemporaryDirectory() as tmp:
            out_xyz = Path(tmp) / "candidates.xyz"
            run_ase_ga_search(
                composition,
                out_xyz,
                charge=charge,
                multiplicity=multiplicity,
                population_size=max(6, min(12, max_candidates)),
                n_generations=2,
            )
            scored = read_clusters_from_file(out_xyz, label_prefix="asega")
            return [sc.cluster for sc in scored[:max_candidates]]


def select_generator_name(
    probe: ServerProbe | None = None,
    *,
    has_imported_structures: bool = False,
) -> str:
    """Select highest-priority available structure generator per Section 6.1."""
    if has_imported_structures:
        return "import"
    if probe is not None:
        abc = probe.software.get("abcluster_isomer") or probe.software.get("abcluster_geom")
        if abc and abc.available:
            return "abcluster"
        mol = probe.software.get("molclus")
        if mol and mol.available:
            return "molclus"
        return "ase_ga"
    return "ase_ga"


for _gen in (
    ImportGenerator(),
    ABClusterGenerator(),
    MolclusGenerator(),
    AseGaGenerator(),
):
    if _gen.name not in GENERATORS:
        GENERATORS.register(_gen.name, _gen)

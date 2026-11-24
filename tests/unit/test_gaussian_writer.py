"""Unit tests for Gaussian input writer, BSE coverage checks, and `qcai gen` CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from ase.io import read as ase_read
from ase.io import write as ase_write
from pymatgen.io.gaussian import GaussianInput
from typer.testing import CliRunner

from qcai.cli import app
from qcai.core.models import CalcSpec, Cluster, ElectronicState
from qcai.interfaces import QCPROGRAMS
from qcai.programs.gaussian.writer import (
    BasisCoverageError,
    check_basis_coverage,
    read_gaussian_nproc,
    update_gaussian_link0_resources,
    write_gaussian_input,
)


def test_basis_coverage_check_and_block() -> None:
    ok = check_basis_coverage("def2-TZVP", ["H", "Al", "Fe", "Au", "Gd"])
    assert ok.covered is True

    bad = check_basis_coverage("6-31G*", ["Al", "Au"])
    assert bad.covered is False
    assert "Au" in bad.missing_by_basis["6-31G*"]
    assert any("def2" in alt.lower() for alt in bad.alternatives)


def test_writer_roundtrip_closed_open_and_genecp(tmp_path: Path) -> None:
    # 1. Open-shell Al2Ni- (26 + 28 + 1 = 55 electrons -> mult=2)
    cluster = Cluster(
        symbols=["Al", "Al", "Ni"],
        positions=[(0.0, 0.0, 0.0), (2.5, 0.0, 0.0), (1.25, 2.1, 0.0)],
        label="Al2Ni_anion",
    )
    spec = CalcSpec(
        functional="PBE0",
        basis="def2-TZVP",
        dispersion="GD3BJ",
        tasks=["opt", "freq", "stable"],
        scf_strategy="robust",
        nosymm=True,
    )
    gjf = tmp_path / "al2ni.gjf"
    write_gaussian_input(
        cluster,
        ElectronicState(charge=-1, multiplicity=2),
        spec,
        gjf,
        nproc=12,
        mem_gb=24,
    )
    text = gjf.read_text(encoding="utf-8")
    assert "%nprocshared=12" in text
    assert "%mem=24GB" in text
    assert "#P UPBE1PBE/def2TZVP" in text
    assert "nosymm" in text
    assert "stable=opt" in text
    assert "scf=(xqc,maxcycle=500)" in text

    gin_back = GaussianInput.from_file(gjf)
    assert gin_back.charge == -1
    assert gin_back.spin_multiplicity == 2
    assert [s.specie.symbol for s in gin_back.molecule] == cluster.symbols

    atoms_back = ase_read(str(gjf))
    assert list(atoms_back.get_chemical_symbols()) == cluster.symbols

    # 2. Mixed per-element basis with Au -> must emit GenECP
    au_cluster = Cluster(
        symbols=["Al", "Au"],
        positions=[(0.0, 0.0, 0.0), (2.5, 0.0, 0.0)],
        label="AlAu",
    )
    mixed_spec = CalcSpec(
        functional="PBE",
        basis={"Al": "def2-SVP", "Au": "def2-TZVP"},
        tasks=["sp"],
    )
    gjf_genecp = tmp_path / "alau.gjf"
    write_gaussian_input(
        au_cluster,
        ElectronicState(charge=0, multiplicity=1),
        mixed_spec,
        gjf_genecp,
    )
    gen_text = gjf_genecp.read_text(encoding="utf-8")
    assert "PBEPBE/GenECP" in gen_text
    assert "AU-ECP" in gen_text.upper()


def test_writer_blocks_uncovered_basis(tmp_path: Path) -> None:
    cluster = Cluster(
        symbols=["Au", "Au"],
        positions=[(0.0, 0.0, 0.0), (2.5, 0.0, 0.0)],
        label="Au2",
    )
    spec = CalcSpec(functional="PBE0", basis="6-31G*", tasks=["sp"])
    with pytest.raises(BasisCoverageError) as exc_info:
        write_gaussian_input(
            cluster, ElectronicState(charge=0, multiplicity=1), spec, tmp_path / "bad.gjf"
        )
    assert "Au" in exc_info.value.missing_elements
    assert len(exc_info.value.alternatives) > 0


def test_qcprogram_registry_and_cli_gen(tmp_path: Path) -> None:
    prog = QCPROGRAMS.get("gaussian")
    assert prog.name == "gaussian"

    xyz_path = tmp_path / "al3.xyz"
    c = Cluster(
        symbols=["Al", "Al", "Al"],
        positions=[(0.0, 0.0, 0.0), (2.5, 0.0, 0.0), (1.25, 2.1, 0.0)],
        label="Al3",
    )
    ase_write(str(xyz_path), c.to_ase())

    out_gjf = tmp_path / "al3_out.gjf"
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "gen",
            str(xyz_path),
            "--functional",
            "PBE0",
            "--basis",
            "def2-SVP",
            "--charge",
            "0",
            "--tasks",
            "opt,freq",
            "--out",
            str(out_gjf),
        ],
    )
    assert res.exit_code == 0
    assert out_gjf.exists()
    gin = GaussianInput.from_file(out_gjf)
    assert gin.spin_multiplicity == 2  # 39 electrons -> doublet
    assert "UPBE1PBE" in gin.functional


def test_lanthanide_and_builtin_gap_fallback_to_bse_genecp(tmp_path: Path) -> None:
    # 1. TmAu cluster with def2-TZVP must fall back to BSE GenECP (G16 built-in lacks Ce-Lu)
    tm_au = Cluster(
        symbols=["Au", "Tm"],
        positions=[(0.0, 0.0, 0.0), (0.0, 0.0, 2.7)],
        label="TmAu",
    )
    spec_tz = CalcSpec(
        functional="PBE0",
        basis="def2-TZVP",
        dispersion="GD3BJ",
        tasks=["opt", "freq", "stable"],
        scf_strategy="robust",
        nosymm=True,
    )
    gjf_tm_au = tmp_path / "tmau.gjf"
    write_gaussian_input(tm_au, ElectronicState(charge=0, multiplicity=1), spec_tz, gjf_tm_au)
    txt = gjf_tm_au.read_text(encoding="utf-8")
    assert "#P PBE1PBE/GenECP" in txt
    assert "EmpiricalDispersion=GD3BJ" in txt
    assert "TM-ECP" in txt.upper()
    assert "AU-ECP" in txt.upper()
    assert "TM-ECP     5     28" in txt.upper()
    assert "--Link1--" in txt
    assert "chkbasis" in txt

    # 2. Isolated Tm atom with def2-SVP also emits GenECP (no built-in def2SVP)
    tm_atom = Cluster(symbols=["Tm"], positions=[(0.0, 0.0, 0.0)], label="atom_Tm")
    gjf_tm = tmp_path / "tm.gjf"
    write_gaussian_input(
        tm_atom,
        ElectronicState(charge=0, multiplicity=2),
        CalcSpec(functional="PBE", basis="def2-SVP", tasks=["sp"]),
        gjf_tm,
    )
    txt_tm = gjf_tm.read_text(encoding="utf-8")
    assert "#P UPBEPBE/GenECP" in txt_tm
    assert "TM-ECP" in txt_tm.upper()

    # 3. CeAl cluster uses GenECP for def2-TZVP while AlAu keeps built-in def2TZVP
    ce_al = Cluster(
        symbols=["Ce", "Al"],
        positions=[(0.0, 0.0, 0.0), (2.6, 0.0, 0.0)],
        label="CeAl",
    )
    gjf_ce = tmp_path / "ceal.gjf"
    write_gaussian_input(
        ce_al,
        ElectronicState(charge=0, multiplicity=2),
        CalcSpec(functional="PBE0", basis="def2-TZVP", tasks=["sp"]),
        gjf_ce,
    )
    assert "#P UPBE1PBE/GenECP" in gjf_ce.read_text(encoding="utf-8")

    al_au = Cluster(
        symbols=["Al", "Au"],
        positions=[(0.0, 0.0, 0.0), (2.5, 0.0, 0.0)],
        label="AlAu_builtin",
    )
    gjf_al_au = tmp_path / "alau_builtin.gjf"
    write_gaussian_input(
        al_au,
        ElectronicState(charge=0, multiplicity=1),
        CalcSpec(functional="PBE0", basis="def2-TZVP", tasks=["sp"]),
        gjf_al_au,
    )
    assert "#P PBE1PBE/def2TZVP" in gjf_al_au.read_text(encoding="utf-8")

    # 4. LANL2DZ on U+O falls back to BSE GenECP because G16 built-in LANL2DZ lacks U
    uo = Cluster(
        symbols=["U", "O"],
        positions=[(0.0, 0.0, 0.0), (1.8, 0.0, 0.0)],
        label="UO",
    )
    gjf_uo = tmp_path / "uo.gjf"
    write_gaussian_input(
        uo,
        ElectronicState(charge=0, multiplicity=3),
        CalcSpec(functional="PBE0", basis="LANL2DZ", dispersion="GD3BJ", tasks=["sp"]),
        gjf_uo,
    )
    txt_uo = gjf_uo.read_text(encoding="utf-8")
    assert "#P UPBE1PBE/GenECP" in txt_uo
    assert "EmpiricalDispersion=GD3BJ" in txt_uo


def test_gd3_dispersion_dropped_above_z94(tmp_path: Path) -> None:
    am = Cluster(symbols=["Am"], positions=[(0.0, 0.0, 0.0)], label="atom_Am")
    gjf_am = tmp_path / "am.gjf"
    write_gaussian_input(
        am,
        ElectronicState(charge=0, multiplicity=8),
        CalcSpec(
            functional="PBE0",
            basis="SARC-DKH2",
            dispersion="GD3BJ",
            tasks=["opt", "stable"],
        ),
        gjf_am,
    )
    txt_am = gjf_am.read_text(encoding="utf-8")
    assert "#P UPBE1PBE/Gen" in txt_am
    assert "EmpiricalDispersion" not in txt_am


def test_update_gaussian_link0_resources_preserves_link1_and_genecp(tmp_path: Path) -> None:
    tm_au5 = Cluster(
        symbols=["Tm", "Au", "Au", "Au", "Au", "Au"],
        positions=[
            (0.0, 0.0, 0.0),
            (2.7, 0.0, 0.0),
            (-2.7, 0.0, 0.0),
            (0.0, 2.7, 0.0),
            (0.0, -2.7, 0.0),
            (0.0, 0.0, 2.7),
        ],
        label="TmAu5",
    )
    spec = CalcSpec(
        functional="PBE0",
        basis="def2-TZVP",
        dispersion="GD3BJ",
        tasks=["opt", "freq", "stable"],
        scf_strategy="robust",
        nosymm=True,
    )
    gjf = tmp_path / "tma5.gjf"
    write_gaussian_input(
        tm_au5,
        ElectronicState(charge=0, multiplicity=3),
        spec,
        gjf,
        nproc=4,
        mem_gb=8,
    )
    assert read_gaussian_nproc(gjf) == 4
    before = gjf.read_text(encoding="utf-8")

    update_gaussian_link0_resources(gjf, nproc=14, mem_gb=42)
    assert read_gaussian_nproc(gjf) == 14
    after = gjf.read_text(encoding="utf-8")
    assert "%nprocshared=4" not in after
    assert "%mem=8GB" not in after
    assert after.count("%nprocshared=14") == 3
    assert after.count("%mem=42GB") == 3
    assert after.count("--Link1--") == 2
    assert "TM-ECP" in after.upper()
    assert "AU-ECP" in after.upper()
    assert (
        after.replace("%nprocshared=14", "%nprocshared=4").replace("%mem=42GB", "%mem=8GB")
        == before
    )

    # Missing directives are prepended cleanly
    plain = tmp_path / "plain.gjf"
    plain.write_text("#P PBE1PBE/def2SVP sp\n\ntest\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    assert read_gaussian_nproc(plain) is None
    update_gaussian_link0_resources(plain, nproc=8, mem_gb=16)
    assert read_gaussian_nproc(plain) == 8
    plain_lines = plain.read_text(encoding="utf-8").splitlines()
    assert plain_lines[0] == "%nprocshared=8"
    assert plain_lines[1] == "%mem=16GB"

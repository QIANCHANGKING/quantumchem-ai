"""Unit tests for Gaussian output parsing and golden input validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pymatgen.io.gaussian import GaussianInput, GaussianOutput

from qcai.core.models import ElectronicState
from qcai.core.physics import validate_electronic_state
from qcai.programs.gaussian.parser import parse_gaussian_log

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.mark.parametrize(
    ("filename", "expected_charge", "expected_mult", "expected_channels"),
    [
        ("dvb_sp.out", 0, 1, 1),
        ("dvb_gopt.out", 0, 1, 1),
        ("dvb_ir.out", 0, 1, 1),
        ("dvb_un_sp.log", 1, 2, 2),
        ("Mo4OCl4-sp.log", -2, 1, 1),
    ],
)
def test_parse_cclib_gaussian_samples(
    filename: str,
    expected_charge: int,
    expected_mult: int,
    expected_channels: int,
) -> None:
    log_path = DATA_DIR / "cclib" / filename
    res = parse_gaussian_log(log_path)

    assert res.normal_termination is True
    assert res.error_code is None
    assert res.state.charge == expected_charge
    assert res.state.multiplicity == expected_mult
    assert len(res.mo_energies_hartree) == expected_channels
    assert len(res.homo_indices) == expected_channels
    assert res.metadata["link1_sections"] == 1
    assert res.energy_hartree is not None
    # pymatgen GaussianOutput fails on dvb_ir.out missing frequency symmetry labels
    if filename != "dvb_ir.out":
        gout = GaussianOutput(str(log_path))
        assert res.energy_hartree == pytest.approx(gout.final_energy, abs=1e-6)
    else:
        assert res.energy_hartree == pytest.approx(-382.308266602, abs=1e-6)


def test_parse_open_shell_spin_and_thermo() -> None:
    un_res = parse_gaussian_log(DATA_DIR / "cclib" / "dvb_un_sp.log")
    assert un_res.s2_before == pytest.approx(0.7778)
    assert un_res.s2_after == pytest.approx(0.7504)
    assert "mulliken" in un_res.spins
    assert sum(un_res.spins["mulliken"]) == pytest.approx(1.0, abs=1e-4)

    ir_res = parse_gaussian_log(DATA_DIR / "cclib" / "dvb_ir.out")
    assert ir_res.zpe_hartree == pytest.approx(0.177132)
    assert len(ir_res.freqs_cm1) == 54
    assert ir_res.imag_freqs == []


def test_parse_fault_and_link1_logs() -> None:
    scf = parse_gaussian_log(DATA_DIR / "faults" / "scf_l502.log")
    assert scf.normal_termination is False
    assert scf.error_code == "L502"
    assert "scf_not_converged" in scf.metadata["error_hints"]

    opt = parse_gaussian_log(DATA_DIR / "faults" / "opt_l9999.log")
    assert opt.normal_termination is False
    assert opt.error_code == "L9999"
    assert "max_steps_exceeded" in opt.metadata["error_hints"]

    imag = parse_gaussian_log(DATA_DIR / "faults" / "imag_freq.log")
    assert imag.normal_termination is True
    assert imag.imag_freqs == pytest.approx([-84.215])

    link1 = parse_gaussian_log(DATA_DIR / "faults" / "link1_stable_opt.log")
    assert link1.normal_termination is True
    assert link1.stable is True
    assert link1.metadata["link1_sections"] == 2
    assert link1.metadata["normal_terminations_count"] == 2
    assert link1.s2_before == pytest.approx(2.06)
    assert link1.s2_after == pytest.approx(2.0015)


def test_golden_inputs_manifest_and_gjf_validity() -> None:
    golden_dir = DATA_DIR / "golden_inputs"
    manifest = yaml.safe_load((golden_dir / "manifest.yaml").read_text(encoding="utf-8"))
    samples = manifest["samples"]
    assert len(samples) >= 10

    for entry in samples:
        gjf_path = golden_dir / entry["file"]
        assert gjf_path.exists()
        raw = gjf_path.read_text(encoding="utf-8")
        first_step = raw.split("--Link1--")[0]
        gin = GaussianInput.from_str(first_step)
        assert gin.charge == entry["charge"]
        assert gin.spin_multiplicity == entry["multiplicity"]
        symbols = [site.specie.symbol for site in gin.molecule]
        validate_electronic_state(
            symbols,
            ElectronicState(charge=gin.charge, multiplicity=gin.spin_multiplicity),
        )

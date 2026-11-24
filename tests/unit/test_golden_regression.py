"""Golden regression tests against real Gaussian 16 outputs collected in P3."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qcai.programs.gaussian.parser import parse_gaussian_log

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "data" / "golden"


@pytest.mark.parametrize(
    (
        "job_id",
        "expected_normal",
        "expected_error",
        "expected_charge",
        "expected_mult",
        "expected_energy",
        "expected_channels",
        "expected_link1",
        "expected_stable",
        "expected_runner_state",
    ),
    [
        ("na6", True, None, 0, 1, -972.741909254, 1, 1, None, "done"),
        ("al13_anion", True, None, -1, 1, -3149.26587145, 1, 1, None, "done"),
        ("fe4", True, None, 0, 13, -5053.21283749, 2, 1, None, "done"),
        ("w_au12", True, None, 0, 1, -1696.51646613, 1, 1, None, "done"),
        ("cu3ag3", True, None, 0, 1, -5361.21337775, 1, 1, None, "done"),
        ("al12cu", True, None, 0, 2, -4546.98150054, 2, 1, None, "done"),
        ("fault_scf_noconv", False, "L502", 0, 5, -5052.84602977, 0, 1, None, "failed"),
        ("fault_opt_maxsteps", True, None, 0, 2, -3427.04243091, 2, 1, None, "done"),
        ("fault_imag_freq", True, None, 0, 1, -543.167627755, 1, 1, None, "done"),
        ("link1_stable_opt", True, None, 0, 3, -3015.64810298, 2, 2, True, "done"),
    ],
)
def test_golden_outputs_parse_and_match_expectations(
    job_id: str,
    expected_normal: bool,
    expected_error: str | None,
    expected_charge: int,
    expected_mult: int,
    expected_energy: float,
    expected_channels: int,
    expected_link1: int,
    expected_stable: bool | None,
    expected_runner_state: str,
) -> None:
    job_dir = GOLDEN_DIR / job_id
    res = parse_gaussian_log(job_dir / "job.log", job_id=job_id)

    assert res.normal_termination is expected_normal
    assert res.error_code == expected_error
    assert res.state.charge == expected_charge
    assert res.state.multiplicity == expected_mult
    assert res.energy_hartree == pytest.approx(expected_energy, abs=1e-6)
    assert len(res.mo_energies_hartree) == expected_channels
    assert res.metadata["link1_sections"] == expected_link1
    assert res.stable is expected_stable
    if expected_normal:
        assert res.imag_freqs == []

    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == expected_runner_state


def test_golden_self_healing_custodian_records() -> None:
    # al12cu recovered Jahn-Teller imaginary freq via ImaginaryFreqHandler
    al12cu_cust = json.loads((GOLDEN_DIR / "al12cu" / "custodian.json").read_text(encoding="utf-8"))
    assert al12cu_cust[0]["corrections"][0]["errors"] == ["imaginary_freq"]

    # fault_imag_freq recovered square Au4 via ImaginaryFreqHandler
    imag_st = json.loads(
        (GOLDEN_DIR / "fault_imag_freq" / "status.json").read_text(encoding="utf-8")
    )
    assert imag_st["state"] == "done"
    assert len(imag_st["fixes"]) == 1

    # fault_opt_maxsteps recovered L9999 via SafeGaussianErrorHandler
    opt_st = json.loads(
        (GOLDEN_DIR / "fault_opt_maxsteps" / "status.json").read_text(encoding="utf-8")
    )
    assert opt_st["state"] == "done"
    assert "opt_steps" in opt_st["fixes"][0]

    # fault_scf_noconv hit max_errors and flagged needs_human=True
    scf_st = json.loads(
        (GOLDEN_DIR / "fault_scf_noconv" / "status.json").read_text(encoding="utf-8")
    )
    assert scf_st["state"] == "failed"
    assert scf_st["needs_human"] is True
    assert len(scf_st["fixes"]) == 2

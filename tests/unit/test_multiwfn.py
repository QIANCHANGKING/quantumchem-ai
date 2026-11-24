"""Unit tests for Multiwfn 3.8(dev) templates, real-output parsers, version guards, and cubegen."""

from __future__ import annotations

from pathlib import Path

import pytest

from qcai.programs.multiwfn import (
    MultiwfnVersionError,
    build_charge_spin_stdin,
    build_cubegen_jobs,
    build_orb_comp_stdin,
    build_pdos_stdin,
    parse_charge_spin,
    parse_orb_comp,
    parse_pdos,
)

MWFN_DATA = Path(__file__).resolve().parents[1] / "data" / "multiwfn" / "al12cu"


def test_multiwfn_templates_build() -> None:
    cs_in = build_charge_spin_stdin(open_shell=True)
    assert "7\n1\n" in cs_in
    assert "15\n-1\n3\n1\n5\n" in cs_in

    pdos_in, frags = build_pdos_stdin(["Cu", "Al"], spin="beta", fwhm_ev=0.35)
    assert frags == ["Cu", "Al", "s", "p", "d"]
    assert "e Cu" in pdos_in and "l d" in pdos_in
    assert "\n6\n2\n" in pdos_in

    orb_in = build_orb_comp_stdin(open_shell=True)
    assert "ha\nhb\nla\nlb\n" in orb_in


def test_parse_real_multiwfn_al12cu_outputs() -> None:
    # 1. Charge + spin (Hirshfeld, ADCH, and Menu 15 Hirshfeld spin density)
    out_7 = (MWFN_DATA / "out_7.txt").read_text(encoding="utf-8")
    out_15 = (MWFN_DATA / "out_15_spin.txt").read_text(encoding="utf-8")
    charges, spins = parse_charge_spin(out_7 + "\n" + out_15)
    assert len(charges["hirshfeld"]) == 13
    assert len(charges["adch"]) == 13
    assert charges["hirshfeld"][0] == pytest.approx(0.15967046)
    assert len(spins["hirshfeld"]) == 13
    assert sum(spins["hirshfeld"]) == pytest.approx(1.0, abs=1e-4)

    # 2. PDOS (Menu 10 export)
    out_10 = (MWFN_DATA / "out_10_exp.txt").read_text(encoding="utf-8")
    curve = MWFN_DATA / "DOS_curve.txt"
    frags = ["Al", "Cu", "s", "p", "d"]
    pdos = parse_pdos(out_10, curve, frags)
    assert len(pdos.energies_ev) == 3000
    assert len(pdos.tdos_alpha) == 3000
    assert pdos.tdos_beta is None
    assert set(pdos.pdos_series.keys()) == {"Al", "Cu", "s", "p", "d"}

    # Open-shell alpha + beta PDOS negation
    pdos_ab = parse_pdos(out_10, curve, frags, curve_beta_path=curve)
    assert pdos_ab.tdos_beta is not None
    assert pdos_ab.tdos_beta[1500] == pytest.approx(-pdos_ab.tdos_alpha[1500])
    assert "Al_alpha" in pdos_ab.pdos_series and "Al_beta" in pdos_ab.pdos_series

    # 3. Frontier orbital composition (Menu 8)
    out_8 = (MWFN_DATA / "out_8_frontier.txt").read_text(encoding="utf-8")
    comps = parse_orb_comp(out_8)
    assert len(comps) >= 4
    first = comps[0]
    assert first.spin == "alpha"
    assert first.contributions["shell_s"] + first.contributions["shell_p"] + first.contributions[
        "shell_d"
    ] == pytest.approx(100.0, abs=0.2)
    atom_sum = sum(v for k, v in first.contributions.items() if not k.startswith("shell_"))
    assert atom_sum == pytest.approx(100.0, abs=0.2)


def test_multiwfn_version_mismatch_errors() -> None:
    wrong_ver = "Multiwfn\nVersion 3.7, update date: 2020-Jan-01\nFinal atomic charges:\n"
    no_ver = "Final atomic charges:\nAtom 1(Al): 0.0\n"
    for text in (wrong_ver, no_ver):
        with pytest.raises(MultiwfnVersionError):
            parse_charge_spin(text)
        with pytest.raises(MultiwfnVersionError):
            parse_orb_comp(text)
        with pytest.raises(MultiwfnVersionError):
            parse_pdos(text, MWFN_DATA / "DOS_curve.txt", ["Al"])


def test_cubegen_presets() -> None:
    os_jobs = build_cubegen_jobs("job.fchk", open_shell=True, quality="publication")
    labels = [lbl for lbl, _ in os_jobs]
    assert labels == ["spin", "homo_alpha", "homo_beta", "lumo_alpha", "lumo_beta"]
    assert all(cmd[-2] == "100" for _, cmd in os_jobs)
    assert os_jobs[0][1][2] == "Spin=SCF"
    assert os_jobs[1][1][2] == "AMO=HOMO"

    cs_jobs = build_cubegen_jobs("job.fchk", open_shell=False, quality="preview")
    assert [lbl for lbl, _ in cs_jobs] == ["homo", "lumo"]
    assert all(cmd[-2] == "40" for _, cmd in cs_jobs)

"""Hand-calculated unit tests for Section 5.6 physical quantities and summaries."""

from __future__ import annotations

import pytest

from qcai.analysis import (
    ade_ev,
    average_binding_energy_ha,
    charge_transfer_by_element,
    embedding_energy_ha,
    fragmentation_energy_ha,
    homo_lumo_gap_ev,
    is_jellium_magic,
    minority_dopant_charge_transfer,
    mixing_energy_ha,
    second_order_energy_diff_ha,
    spin_localization,
    substitution_energy_ha,
    summarize_cluster,
    summarize_project,
    valence_electron_count,
    vde_ev,
    vea_ev,
    vip_ev,
)
from qcai.core.models import CalcResult, Cluster, ElectronicState
from qcai.core.physics import HA_TO_EV


def test_hand_calculated_energetics_formulas() -> None:
    # Eb = (4 * (-162.0) - (-648.4)) / 4 = 0.4 / 4 = 0.1 Ha/atom
    eb = average_binding_energy_ha(-648.4, {"Na": -162.0}, {"Na": 4})
    assert eb == pytest.approx(0.1)

    with pytest.raises(KeyError):
        average_binding_energy_ha(-100.0, {}, {"Al": 2})

    # Delta_2 E(n) = E(n+1) + E(n-1) - 2*E(n) = (-10.5) + (-8.0) - 2*(-9.5) = +0.5 Ha
    assert second_order_energy_diff_ha(-8.0, -9.5, -10.5) == pytest.approx(0.5)

    # Fragmentation E_f = E(n-1) + E(1) - E(n) = (-8.0) + (-1.0) - (-9.5) = +0.5 Ha
    assert fragmentation_energy_ha(-8.0, -1.0, -9.5) == pytest.approx(0.5)

    # Embedding E_emb = E(H_n) + E(D) - E(DH_n) = (-20.0) + (-5.0) - (-25.3) = +0.3 Ha
    assert embedding_energy_ha(-20.0, -5.0, -25.3) == pytest.approx(0.3)

    # Substitution E_sub = E(DH_{n-1}) + E(H) - E(H_n) - E(D) = (-23.2) + (-2.0) - (-24.0) - (-1.5) = +0.3 Ha
    assert substitution_energy_ha(-23.2, -2.0, -24.0, -1.5) == pytest.approx(0.3)

    # Mixing Delta = E(A2B4) - (2/6)*E(A6) - (4/6)*E(B6) = (-60.5) - (1/3)*(-30.0) - (2/3)*(-75.0) = -0.5 Ha
    assert mixing_energy_ha(-60.5, 2, -30.0, 4, -75.0) == pytest.approx(-0.5)

    # Vertical / adiabatic detachment & ionization & EA (in eV)
    assert vde_ev(-100.1, -100.0) == pytest.approx(0.1 * HA_TO_EV)
    assert ade_ev(-100.12, -100.05) == pytest.approx(0.07 * HA_TO_EV)
    assert vip_ev(-100.0, -99.7) == pytest.approx(0.3 * HA_TO_EV)
    assert vea_ev(-100.0, -100.05) == pytest.approx(0.05 * HA_TO_EV)


def test_jellium_valence_charge_transfer_and_spin_localization() -> None:
    assert valence_electron_count(["Na"] * 6, charge=0) == 6
    assert is_jellium_magic(6) is False
    assert valence_electron_count(["Li"] * 8, charge=0) == 8
    assert is_jellium_magic(8) is True
    assert valence_electron_count(["Al"] * 13, charge=-1) == 40
    assert is_jellium_magic(40) is True
    assert valence_electron_count(["W"] + ["Au"] * 12, charge=0) == 18
    assert is_jellium_magic(18) is True

    syms = ["Ni", "Al", "Al", "Al"]
    charges = {
        "mulliken": [-0.10, 0.03, 0.03, 0.04],
        "hirshfeld": [-0.30, 0.10, 0.10, 0.10],
    }
    by_el = charge_transfer_by_element(charges, syms)
    assert by_el["Ni"] == pytest.approx(-0.30)
    assert by_el["Al"] == pytest.approx(0.30)
    assert minority_dopant_charge_transfer(charges, syms) == pytest.approx(-0.30)

    # Spin localization f_D = 1.6 / (1.6 + 0.2 + 0.1 + 0.1) = 0.80
    f_d = spin_localization([1.6, 0.2, 0.1, 0.1], syms)
    assert f_d == pytest.approx(0.80)


def test_cluster_and_project_summary_with_all_issue_flags() -> None:
    c_al2ni = Cluster(
        symbols=["Ni", "Al", "Al"],
        positions=[(0.0, 0.0, 0.0), (2.4, 0.0, 0.0), (1.2, 2.1, 0.0)],
        label="Al2Ni",
    )
    r_gs = CalcResult(
        job_id="gs_m4",
        normal_termination=True,
        state=ElectronicState(charge=0, multiplicity=4),
        final_geometry=c_al2ni,
        energy_hartree=-200.5,
        mo_energies_hartree=[[-0.3, -0.2, -0.1], [-0.32, -0.22, -0.15]],
        homo_indices=[1, 1],
        s2_before=4.30,
        s2_after=4.25,  # ideal=3.75, +13.3% -> spin contaminated
        charges={"hirshfeld": [-0.4, 0.2, 0.2]},
        spins={"hirshfeld": [2.4, 0.3, 0.3]},
    )
    r_low_m2 = CalcResult(
        job_id="iso_m2",
        normal_termination=True,
        state=ElectronicState(charge=0, multiplicity=2),
        final_geometry=c_al2ni,
        energy_hartree=-200.4,
        imag_freqs=[-45.0],
        stable=False,
    )
    r_failed = CalcResult(
        job_id="bad_l502",
        normal_termination=False,
        error_code="L502",
        state=ElectronicState(charge=0, multiplicity=2),
        final_geometry=c_al2ni,
        energy_hartree=None,
    )

    assert homo_lumo_gap_ev(r_gs) == pytest.approx(0.07 * HA_TO_EV)

    cs = summarize_cluster(
        "Al2Ni",
        [r_gs, r_low_m2, r_failed],
        atom_energies_ha={"Al": -66.0, "Ni": -68.0},
    )
    assert cs.ground_state_job_id == "gs_m4"
    assert cs.ground_state_multiplicity == 4
    assert cs.magnetic_moment_mu_b == pytest.approx(3.0)
    assert cs.binding_energy_ev_per_atom == pytest.approx((0.5 / 3.0) * HA_TO_EV)
    assert cs.spin_localization == pytest.approx(0.8)
    assert cs.dopant_charge_transfer == pytest.approx(-0.4)

    codes = {iss.code for iss in cs.issues}
    assert {
        "ABNORMAL_TERMINATION",
        "IMAGINARY_FREQUENCY",
        "WAVEFUNCTION_UNSTABLE",
        "SPIN_CONTAMINATION",
        "MULTIPLICITY_BOUNDARY_UNCAPPED",
    }.issubset(codes)

    # Test ProjectSummary size evolution and mixing energy
    cs_a1 = summarize_cluster(
        "Na2",
        [
            CalcResult(
                job_id="na2",
                normal_termination=True,
                state=ElectronicState(charge=0, multiplicity=1),
                final_geometry=Cluster(
                    symbols=["Na", "Na"], positions=[(0, 0, 0), (3, 0, 0)], label="Na2"
                ),
                energy_hartree=-324.0,
            )
        ],
    )
    cs_a2 = summarize_cluster(
        "Na3",
        [
            CalcResult(
                job_id="na3",
                normal_termination=True,
                state=ElectronicState(charge=0, multiplicity=2),
                final_geometry=Cluster(
                    symbols=["Na", "Na", "Na"],
                    positions=[(0, 0, 0), (3, 0, 0), (1.5, 2.5, 0)],
                    label="Na3",
                ),
                energy_hartree=-486.2,
            )
        ],
    )
    cs_a3 = summarize_cluster(
        "Na4",
        [
            CalcResult(
                job_id="na4",
                normal_termination=True,
                state=ElectronicState(charge=0, multiplicity=1),
                final_geometry=Cluster(
                    symbols=["Na", "Na", "Na", "Na"],
                    positions=[(0, 0, 0), (3, 0, 0), (1.5, 2.5, 0), (1.5, 1.0, 2.5)],
                    label="Na4",
                ),
                energy_hartree=-648.6,
            )
        ],
    )
    ps = summarize_project(
        "na_evo",
        {"Na2": cs_a1, "Na3": cs_a2, "Na4": cs_a3, "Al2Ni": cs},
        monomer_energy_ha=-161.9,
        pure_endmembers_by_size={("Al", 3): -198.5, ("Ni", 3): -204.2},
    )
    pts_by_n = {pt.size_n: pt for pt in ps.size_evolution}
    # For Na3 (n=3): delta2_e = (-648.6) + (-324.0) - 2*(-486.2) = -0.2 Ha
    assert pts_by_n[3].delta2_e_ev == pytest.approx(-0.2 * HA_TO_EV)
    assert pts_by_n[3].fragmentation_energy_ev == pytest.approx(
        ((-324.0) + (-161.9) - (-486.2)) * HA_TO_EV
    )
    assert "Al2Ni" in ps.mixing_energies_ev

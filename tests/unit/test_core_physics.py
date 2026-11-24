"""Unit tests for core models, registry, and hand-calculated physics functions."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pymatgen.core.periodic_table import Element

from qcai.core.models import Cluster, ElectronicState
from qcai.core.physics import (
    HA_TO_EV,
    atomic_ground_state_multiplicity,
    covalent_radius,
    homo_lumo_gap_hartree,
    ideal_s_squared,
    is_spin_contaminated,
    is_valid_parity,
    spin_contamination_deviation,
    total_electrons,
    total_magnetic_moment_mu_b,
    validate_electronic_state,
)
from qcai.core.registry import Registry


def test_cluster_ase_and_pymatgen_roundtrip() -> None:
    c = Cluster(
        symbols=["Al", "Al", "Ni"],
        positions=[(0.0, 0.0, 0.0), (2.5, 0.0, 0.0), (1.25, 2.1, 0.0)],
        label="Al2Ni",
        source="unit-test",
    )
    atoms = c.to_ase()
    c_from_ase = Cluster.from_ase(atoms, label="Al2Ni")
    assert c_from_ase.symbols == c.symbols
    assert [x for p in c_from_ase.positions for x in p] == pytest.approx(
        [x for p in c.positions for x in p]
    )

    mol = c.to_pymatgen(charge=0, spin_multiplicity=1)
    c_from_pmg = Cluster.from_pymatgen(mol, label="Al2Ni")
    assert c_from_pmg.symbols == c.symbols
    assert [x for p in c_from_pmg.positions for x in p] == pytest.approx(
        [x for p in c.positions for x in p]
    )


def test_hand_calculated_electron_count_and_parity() -> None:
    # Al13-: 13 * 13 + 1 = 170 electrons (even -> odd mult)
    assert total_electrons(["Al"] * 13, charge=-1) == 170
    assert is_valid_parity(170, 1)
    assert is_valid_parity(170, 3)
    assert not is_valid_parity(170, 2)

    # Al12Cu: 12 * 13 + 29 = 185 electrons (odd -> even mult)
    assert total_electrons(["Al"] * 12 + ["Cu"], charge=0) == 185
    assert is_valid_parity(185, 2)
    assert not is_valid_parity(185, 1)

    # H2 (2 electrons) cannot have multiplicity 5 (4 unpaired > 2)
    assert not is_valid_parity(2, 5)
    with pytest.raises(ValueError):
        validate_electronic_state(["H", "H"], ElectronicState(charge=0, multiplicity=5))


@given(
    n_elec=st.integers(min_value=0, max_value=200),
    mult=st.integers(min_value=1, max_value=20),
)
def test_parity_property(n_elec: int, mult: int) -> None:
    valid = is_valid_parity(n_elec, mult)
    expected = (mult - 1 <= n_elec) and ((n_elec + mult) % 2 == 1)
    assert valid == expected


@pytest.mark.parametrize(
    ("mult", "expected_s2", "expected_mu"),
    [
        (1, 0.0, 0.0),
        (2, 0.75, 1.0),
        (3, 2.0, 2.0),
        (4, 3.75, 3.0),
        (5, 6.0, 4.0),
    ],
)
def test_hand_calculated_spin_metrics(mult: int, expected_s2: float, expected_mu: float) -> None:
    assert ideal_s_squared(mult) == pytest.approx(expected_s2)
    assert total_magnetic_moment_mu_b(mult) == pytest.approx(expected_mu)


def test_spin_contamination_threshold() -> None:
    # Doublet ideal = 0.75; 10% above is 0.825
    assert not is_spin_contaminated(0.78, multiplicity=2)
    assert is_spin_contaminated(0.84, multiplicity=2)
    assert spin_contamination_deviation(0.825, multiplicity=2) == pytest.approx(0.10)
    # Singlet ideal = 0.0; open-shell singlet broken-symmetry <S^2>=0.5 is contaminated
    assert not is_spin_contaminated(0.05, multiplicity=1)
    assert is_spin_contaminated(0.50, multiplicity=1)


@pytest.mark.parametrize(
    ("symbol", "expected_mult"),
    [("Fe", 5), ("Co", 4), ("Ni", 3), ("Cu", 2), ("Au", 2), ("Pt", 3)],
)
def test_atomic_ground_state_multiplicity_spot_check(symbol: str, expected_mult: int) -> None:
    assert atomic_ground_state_multiplicity(symbol) == expected_mult
    assert covalent_radius(symbol) > 0.5


def test_atomic_ground_state_multiplicity_all_elements_valid_parity() -> None:
    for z in range(1, 104):
        sym = Element.from_Z(z).symbol
        mult = atomic_ground_state_multiplicity(sym)
        assert is_valid_parity(z, mult), f"Parity mismatch for Z={z} ({sym}): mult={mult}"

    assert atomic_ground_state_multiplicity("Ce") == 3
    assert atomic_ground_state_multiplicity("Es") == 4
    assert atomic_ground_state_multiplicity("Lr") == 2
    assert atomic_ground_state_multiplicity("Tm") == 2


def test_homo_lumo_gap_closed_and_open_shell() -> None:
    # Closed-shell: gap = -0.10 - (-0.25) = 0.15 Ha
    gap_cs = homo_lumo_gap_hartree([[-0.40, -0.25, -0.10, 0.05]], [1])
    assert gap_cs == pytest.approx(0.15)
    # Open-shell: alpha gap = 0.20, beta gap = 0.08 -> min = 0.08 Ha
    gap_os = homo_lumo_gap_hartree([[-0.30, -0.10, 0.10], [-0.32, -0.20, -0.12]], [1, 1])
    assert gap_os == pytest.approx(0.08)
    assert HA_TO_EV == pytest.approx(27.211386, rel=1e-5)


def test_registry_operations() -> None:
    reg: Registry[str] = Registry("demo")
    reg.register("Mpl", "mpl_impl")
    assert "mpl" in reg
    assert reg.get("MPL") == "mpl_impl"
    assert reg.list_names() == ["mpl"]
    with pytest.raises(KeyError):
        reg.register("mpl", "dup")
    with pytest.raises(KeyError):
        reg.get("missing")

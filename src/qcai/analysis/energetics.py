"""Pure cluster energetics inductive functions (Section 5.6)."""

from __future__ import annotations

from qcai.core.physics import HA_TO_EV


def average_binding_energy_ha(
    cluster_energy_ha: float,
    atom_energies_ha: dict[str, float],
    stoichiometry: dict[str, int],
) -> float:
    """Compute average binding energy per atom in Hartree:

    Eb = (sum_i n_i * E(X_i) - E(cluster)) / sum_i n_i.
    """
    n_total = sum(stoichiometry.values())
    if n_total <= 0:
        raise ValueError("Total atom count must be positive")
    atom_sum = 0.0
    for el, count in stoichiometry.items():
        if el not in atom_energies_ha:
            raise KeyError(f"Missing isolated atom reference energy for {el!r} (Axiom A4)")
        atom_sum += count * atom_energies_ha[el]
    return (atom_sum - cluster_energy_ha) / n_total


def second_order_energy_diff_ha(e_minus1_ha: float, e_n_ha: float, e_plus1_ha: float) -> float:
    """Compute second-order energy difference: Delta_2 E(n) = E(n+1) + E(n-1) - 2*E(n)."""
    return e_plus1_ha + e_minus1_ha - 2.0 * e_n_ha


def fragmentation_energy_ha(e_n_minus1_ha: float, e_monomer_ha: float, e_n_ha: float) -> float:
    """Compute fragmentation / monomer detachment energy: E_f = E(n-1) + E(1) - E(n)."""
    return e_n_minus1_ha + e_monomer_ha - e_n_ha


def embedding_energy_ha(
    e_host_hn_ha: float, e_dopant_atom_ha: float, e_doped_dhn_ha: float
) -> float:
    """Compute dopant embedding energy: E_emb = E(H_n) + E(D) - E(DH_n)."""
    return e_host_hn_ha + e_dopant_atom_ha - e_doped_dhn_ha


def substitution_energy_ha(
    e_doped_dhn_minus1_ha: float,
    e_host_atom_ha: float,
    e_host_hn_ha: float,
    e_dopant_atom_ha: float,
) -> float:
    """Compute substitution energy: E_sub = E(DH_{n-1}) + E(H) - E(H_n) - E(D)."""
    return e_doped_dhn_minus1_ha + e_host_atom_ha - e_host_hn_ha - e_dopant_atom_ha


def mixing_energy_ha(
    e_alloy_ha: float,
    m_a: int,
    e_pure_a_n_ha: float,
    n_b: int,
    e_pure_b_n_ha: float,
) -> float:
    """Compute bimetallic mixing energy:

    Delta = E(A_m B_n) - (m/N)*E(A_N) - (n/N)*E(B_N), where N = m + n.
    """
    n_total = m_a + n_b
    if n_total <= 0:
        raise ValueError("Total atom count m + n must be positive")
    return e_alloy_ha - (m_a / n_total) * e_pure_a_n_ha - (n_b / n_total) * e_pure_b_n_ha


def vde_ev(e_anion_at_anion_ha: float, e_neutral_at_anion_ha: float) -> float:
    """Vertical detachment energy (eV): E(neutral @ anion geom) - E(anion)."""
    return (e_neutral_at_anion_ha - e_anion_at_anion_ha) * HA_TO_EV


def ade_ev(e_anion_ha: float, e_neutral_ha: float) -> float:
    """Adiabatic detachment energy (eV): E(neutral min) - E(anion min)."""
    return (e_neutral_ha - e_anion_ha) * HA_TO_EV


def vip_ev(e_neutral_ha: float, e_cation_at_neutral_ha: float) -> float:
    """Vertical ionization potential (eV): E(cation @ neutral geom) - E(neutral)."""
    return (e_cation_at_neutral_ha - e_neutral_ha) * HA_TO_EV


def vea_ev(e_neutral_ha: float, e_anion_at_neutral_ha: float) -> float:
    """Vertical electron affinity (eV): E(neutral) - E(anion @ neutral geom)."""
    return (e_neutral_ha - e_anion_at_neutral_ha) * HA_TO_EV

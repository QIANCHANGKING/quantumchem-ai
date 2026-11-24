"""Pure physical and chemical constants and helper functions.

All atomic data are obtained from pymatgen.core.Element and ase.data;
unit conversions come from ase.units. No element-specific branches are permitted.
"""

from __future__ import annotations

import math

from ase import units as ase_units
from ase.data import atomic_numbers, covalent_radii, ground_state_magnetic_moments
from pymatgen.core.periodic_table import Element

from qcai.core.models import ElectronicState

HA_TO_EV: float = float(ase_units.Hartree)
EV_TO_HA: float = 1.0 / HA_TO_EV


def total_electrons(symbols: list[str], charge: int = 0) -> int:
    """Return total number of electrons for the given atomic symbols and net charge."""
    n_protons = sum(int(Element(sym).Z) for sym in symbols)
    return n_protons - charge


def is_valid_parity(n_electrons: int, multiplicity: int) -> bool:
    """Check electron-count / spin-multiplicity parity and physical bounds.

    Even N requires odd multiplicity; odd N requires even multiplicity;
    and unpaired electrons (M - 1) cannot exceed N.
    """
    if n_electrons < 0 or multiplicity < 1:
        return False
    unpaired = multiplicity - 1
    if unpaired > n_electrons:
        return False
    return (n_electrons % 2) == (unpaired % 2)


def validate_electronic_state(symbols: list[str], state: ElectronicState) -> None:
    """Validate that ElectronicState is physically consistent with composition."""
    n_elec = total_electrons(symbols, state.charge)
    if not is_valid_parity(n_elec, state.multiplicity):
        raise ValueError(
            f"Invalid electronic state (charge={state.charge}, multiplicity={state.multiplicity}) "
            f"for total_electrons={n_elec}"
        )


def ideal_s_squared(multiplicity: int) -> float:
    """Compute ideal spin-squared expectation value S(S+1) from multiplicity 2S+1."""
    if multiplicity < 1:
        raise ValueError(f"multiplicity must be >= 1, got {multiplicity}")
    spin = (multiplicity - 1) / 2.0
    return spin * (spin + 1.0)


def spin_contamination_deviation(s2_actual: float, multiplicity: int) -> float:
    """Return relative deviation (or absolute deviation when S=0) from ideal S(S+1)."""
    ideal = ideal_s_squared(multiplicity)
    if ideal == 0.0:
        return abs(s2_actual)
    return (s2_actual - ideal) / ideal


def is_spin_contaminated(s2_actual: float, multiplicity: int, threshold: float = 0.10) -> bool:
    """Flag spin contamination when <S^2> deviates from S(S+1) beyond threshold (default 10%)."""
    ideal = ideal_s_squared(multiplicity)
    if ideal == 0.0:
        return abs(s2_actual) > threshold
    return abs(s2_actual - ideal) > threshold * ideal


def total_magnetic_moment_mu_b(multiplicity: int) -> float:
    """Return spin-only total magnetic moment in Bohr magnetons: mu = 2S = M - 1."""
    if multiplicity < 1:
        raise ValueError(f"multiplicity must be >= 1, got {multiplicity}")
    return float(multiplicity - 1)


_SUBSHELL_CAP: dict[str, int] = {"s": 2, "p": 6, "d": 10, "f": 14}


def _hund_ground_state_multiplicity(symbol: str, z: int) -> int:
    """Derive ground-state spin multiplicity from pymatgen subshell occupation via Hund's rule."""
    try:
        el = Element(symbol)
        unpaired = sum(
            min(cnt, _SUBSHELL_CAP[orb] - cnt)
            for _, orb, cnt in el.full_electronic_structure
            if orb in _SUBSHELL_CAP
        )
        mult = unpaired + 1
        if is_valid_parity(z, mult):
            return mult
    except Exception:
        pass
    return 1 if (z % 2 == 0) else 2


def atomic_ground_state_multiplicity(symbol: str) -> int:
    """Return ground-state spin multiplicity of an isolated neutral atom from ASE/pymatgen data."""
    z = atomic_numbers.get(symbol)
    if z is None:
        raise ValueError(f"Unknown chemical symbol: {symbol!r}")
    z_int = int(z)
    if z_int < len(ground_state_magnetic_moments):
        raw = float(ground_state_magnetic_moments[z_int])
        if not math.isnan(raw) and raw >= 0.0:
            mult = int(round(raw)) + 1
            if is_valid_parity(z_int, mult):
                return mult
    return _hund_ground_state_multiplicity(symbol, z_int)


def covalent_radius(symbol: str) -> float:
    """Return covalent radius in Angstrom from ASE data."""
    z = atomic_numbers.get(symbol)
    if z is None:
        raise ValueError(f"Unknown chemical symbol: {symbol!r}")
    return float(covalent_radii[z])


def homo_lumo_gap_hartree(
    mo_energies_hartree: list[list[float]], homo_indices: list[int]
) -> float | None:
    """Compute HOMO-LUMO gap in Hartree; for open-shell take min(alpha gap, beta gap)."""
    if not mo_energies_hartree or not homo_indices:
        return None
    gaps: list[float] = []
    for channel, homo_idx in zip(mo_energies_hartree, homo_indices, strict=False):
        lumo_idx = homo_idx + 1
        if 0 <= homo_idx and lumo_idx < len(channel):
            gaps.append(channel[lumo_idx] - channel[homo_idx])
    if not gaps:
        return None
    return min(gaps)

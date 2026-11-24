"""Core Pydantic v2 data models for QuantumChem AI.

Internal units: Energy in Hartree, length in Angstrom.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    import ase
    from pymatgen.core.structure import Molecule


class Cluster(BaseModel):
    """Atomic cluster geometry representation."""

    symbols: list[str]
    positions: list[tuple[float, float, float]]  # Angstrom
    label: str
    source: str | None = None

    @model_validator(mode="after")
    def _check_lengths(self) -> Cluster:
        if len(self.symbols) != len(self.positions):
            raise ValueError(
                f"symbols length ({len(self.symbols)}) must match "
                f"positions length ({len(self.positions)})"
            )
        if not self.symbols:
            raise ValueError("Cluster must contain at least one atom")
        return self

    def to_ase(self) -> ase.Atoms:
        """Convert to an ASE Atoms object."""
        from ase import Atoms

        return Atoms(symbols=self.symbols, positions=self.positions)

    @classmethod
    def from_ase(cls, atoms: ase.Atoms, label: str, source: str | None = None) -> Cluster:
        """Create a Cluster from an ASE Atoms object."""
        symbols = [str(s) for s in atoms.get_chemical_symbols()]  # type: ignore[no-untyped-call]
        coords = atoms.get_positions()  # type: ignore[no-untyped-call]
        positions = [(float(x), float(y), float(z)) for x, y, z in coords]
        return cls(symbols=symbols, positions=positions, label=label, source=source)

    def to_pymatgen(self, charge: int = 0, spin_multiplicity: int | None = None) -> Molecule:
        """Convert to a pymatgen Molecule object."""
        from pymatgen.core.structure import Molecule

        return Molecule(
            species=self.symbols,
            coords=self.positions,
            charge=charge,
            spin_multiplicity=spin_multiplicity,
        )

    @classmethod
    def from_pymatgen(cls, mol: Molecule, label: str, source: str | None = None) -> Cluster:
        """Create a Cluster from a pymatgen Molecule object."""
        symbols = [site.specie.symbol for site in mol]
        positions = [(float(c[0]), float(c[1]), float(c[2])) for c in mol.cart_coords]
        return cls(symbols=symbols, positions=positions, label=label, source=source)


class ElectronicState(BaseModel):
    """Total charge and spin multiplicity (2S + 1)."""

    charge: int = 0
    multiplicity: int = Field(default=1, ge=1)


class CalcSpec(BaseModel):
    """Quantum chemistry calculation specification."""

    functional: str
    basis: str | dict[str, str]
    dispersion: str | None = "GD3BJ"
    tasks: list[Literal["sp", "opt", "freq", "stable"]]
    scf_strategy: Literal["default", "robust"] = "default"
    nosymm: bool = True
    extra_keywords: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    """Auditable automatic planning decision."""

    key: str
    value: Any
    reason: str
    source_rule: str
    overridden: bool = False


class StagePlan(BaseModel):
    """Planned execution stage inside the funnel pipeline."""

    stage: str
    description: str
    estimated_jobs: int = 0


class ResearchRequest(BaseModel):
    """User-level research request."""

    composition: dict[str, int | tuple[int, int]]
    recipes: list[str]
    accuracy: Literal["fast", "standard", "high"] = "standard"
    time_budget_hours: float | None = None
    charges: list[int] | Literal["auto"] = "auto"
    structures: list[Cluster] | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    experimental: dict[str, float] | None = None

    @model_validator(mode="after")
    def _validate_composition(self) -> ResearchRequest:
        if not self.composition:
            raise ValueError("composition 不能为空")

        from ase.data import atomic_numbers

        invalid = [sym for sym in self.composition if int(atomic_numbers.get(sym, 0)) <= 0]
        if invalid:
            raise ValueError(
                f"composition 包含非法元素符号 {invalid}；请仅使用真实周期表元素符号，"
                "不可使用通配符或元素族群缩写（若需对比多个元素，请拆分为多个独立方案）。"
            )

        max_atoms = 0
        for sym, cnt in self.composition.items():
            if isinstance(cnt, tuple):
                lo, hi = cnt
                if lo < 0 or hi < lo:
                    raise ValueError(f"Invalid size range for {sym!r}: {cnt}")
                max_atoms += hi
            else:
                if cnt < 0:
                    raise ValueError(f"Invalid atom count for {sym!r}: {cnt}")
                max_atoms += cnt

        if max_atoms <= 0:
            raise ValueError("Total atom count must be positive")
        return self


class CalcPlan(BaseModel):
    """Full calculation plan produced by the rule engine and planner."""

    request: ResearchRequest
    decisions: list[Decision]
    stages: list[StagePlan]
    estimated_jobs: int
    estimated_core_hours: float


class PDOSData(BaseModel):
    """Total and projected density of states curves."""

    energies_ev: list[float]
    tdos_alpha: list[float]
    tdos_beta: list[float] | None = None
    pdos_series: dict[str, list[float]] = Field(default_factory=dict)


class OrbitalComposition(BaseModel):
    """Atomic and angular-momentum contribution to a molecular orbital."""

    mo_index: int
    spin: Literal["alpha", "beta", "restricted"]
    energy_ev: float
    contributions: dict[str, float]


class CalcResult(BaseModel):
    """Parsed output of a single quantum chemistry calculation."""

    job_id: str
    normal_termination: bool
    error_code: str | None = None
    state: ElectronicState
    final_geometry: Cluster | None = None
    energy_hartree: float | None = None
    zpe_hartree: float | None = None
    thermal_enthalpy_hartree: float | None = None
    thermal_free_energy_hartree: float | None = None
    freqs_cm1: list[float] = Field(default_factory=list)
    imag_freqs: list[float] = Field(default_factory=list)
    stable: bool | None = None
    mo_energies_hartree: list[list[float]] = Field(default_factory=list)
    homo_indices: list[int] = Field(default_factory=list)
    s2_before: float | None = None
    s2_after: float | None = None
    charges: dict[str, list[float]] = Field(default_factory=dict)
    spins: dict[str, list[float]] = Field(default_factory=dict)
    pdos: PDOSData | None = None
    orbital_composition: list[OrbitalComposition] | None = None
    cubes: dict[str, Path] = Field(default_factory=dict)
    fixes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

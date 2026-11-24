"""Multiwfn templates, version-strict parsers, and cubegen helpers."""

from qcai.programs.multiwfn.cubegen import CUBE_GRID_PRESETS, build_cubegen_jobs
from qcai.programs.multiwfn.parsers import (
    MultiwfnVersionError,
    parse_charge_spin,
    parse_orb_comp,
    parse_pdos,
    verify_multiwfn_version,
)
from qcai.programs.multiwfn.templates import (
    SUPPORTED_MULTIWFN_DATE,
    SUPPORTED_MULTIWFN_VERSION,
    build_charge_spin_stdin,
    build_orb_comp_stdin,
    build_pdos_stdin,
)

__all__ = [
    "CUBE_GRID_PRESETS",
    "MultiwfnVersionError",
    "SUPPORTED_MULTIWFN_DATE",
    "SUPPORTED_MULTIWFN_VERSION",
    "build_charge_spin_stdin",
    "build_cubegen_jobs",
    "build_orb_comp_stdin",
    "build_pdos_stdin",
    "parse_charge_spin",
    "parse_orb_comp",
    "parse_pdos",
    "verify_multiwfn_version",
]

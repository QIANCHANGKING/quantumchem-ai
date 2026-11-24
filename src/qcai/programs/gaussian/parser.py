"""Gaussian 16 output parser combining cclib with targeted regex supplements."""

from __future__ import annotations

import logging
import re
import warnings
from pathlib import Path
from typing import Any

import cclib
from pymatgen.core.periodic_table import Element

from qcai.core.models import CalcResult, Cluster, ElectronicState
from qcai.core.physics import EV_TO_HA

_NORMAL_TERM_RE = re.compile(r"Normal termination of Gaussian", re.IGNORECASE)
_ERROR_TERM_RE = re.compile(r"Error termination via Lnk1e in .*?[/\\](l\d+)\.exe", re.IGNORECASE)
_ERROR_GENERIC_RE = re.compile(r"Error termination", re.IGNORECASE)
_S2_RE = re.compile(
    r"S\*\*2 before annihilation\s+([+-]?\d+(?:\.\d+)?),\s+after\s+([+-]?\d+(?:\.\d+)?)"
)
_STABLE_OK_RE = re.compile(r"The wavefunction is (?:already )?stable(?:\.| under)", re.IGNORECASE)
_STABLE_BAD_RE = re.compile(r"The wavefunction has an .*?instability", re.IGNORECASE)
_CHARGE_MULT_RE = re.compile(r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)")
_SCF_DONE_RE = re.compile(r"SCF Done:\s+E\([^)]+\)\s*=\s*([+-]?\d+(?:\.\d+)?)")
_ZPE_RE = re.compile(r"Zero-point correction=\s*([+-]?\d+(?:\.\d+)?)")
_FREQS_LINE_RE = re.compile(r"Frequencies\s+--\s+(.*)")
_ENTHALPY_RE = re.compile(r"Thermal correction to Enthalpy=\s*([+-]?\d+(?:\.\d+)?)")
_GIBBS_RE = re.compile(r"Thermal correction to Gibbs Free Energy=\s*([+-]?\d+(?:\.\d+)?)")
_LINK1_SPLIT_RE = re.compile(r"(?=^\s*Entering Link 1\b)", re.MULTILINE)
_STEP_EXCEEDED_RE = re.compile(r"Number of steps exceeded", re.IGNORECASE)
_SCF_NOCONV_RE = re.compile(r"Convergence criterion not met", re.IGNORECASE)
_MEM_ERR_RE = re.compile(r"(?:galloc|Out-of-memory|insufficient memory)", re.IGNORECASE)


def _split_link1_sections(text: str) -> list[str]:
    """Split a Gaussian log into Link1 job sections."""
    parts = [p for p in _LINK1_SPLIT_RE.split(text) if "Entering Link 1" in p]
    return parts if parts else [text]


def _extract_error_hints(text: str) -> list[str]:
    hints: list[str] = []
    if _SCF_NOCONV_RE.search(text):
        hints.append("scf_not_converged")
    if _STEP_EXCEEDED_RE.search(text):
        hints.append("max_steps_exceeded")
    if _MEM_ERR_RE.search(text):
        hints.append("insufficient_memory")
    return hints


def _extract_regex_supplements(text: str) -> dict[str, Any]:
    """Extract fields that cclib does not consistently expose for Gaussian."""
    sections = _split_link1_sections(text)
    last_section = sections[-1]

    normal_count = len(_NORMAL_TERM_RE.findall(text))
    last_normal = bool(_NORMAL_TERM_RE.search(last_section))
    last_error_generic = bool(_ERROR_GENERIC_RE.search(last_section))
    normal_termination = last_normal and not last_error_generic

    error_code: str | None = None
    if not normal_termination:
        err_matches = _ERROR_TERM_RE.findall(last_section) or _ERROR_TERM_RE.findall(text)
        if err_matches:
            error_code = err_matches[-1].upper()
        elif last_error_generic:
            error_code = "UNKNOWN"

    s2_before: float | None = None
    s2_after: float | None = None
    s2_matches = _S2_RE.findall(last_section) or _S2_RE.findall(text)
    if s2_matches:
        s2_before = float(s2_matches[-1][0])
        s2_after = float(s2_matches[-1][1])

    stable: bool | None = None
    section_stabilities: list[bool | None] = []
    for sec in sections:
        sec_ok = _STABLE_OK_RE.search(sec)
        sec_bad = _STABLE_BAD_RE.search(sec)
        # In a single section with stable=opt, Gaussian prints instability first
        # and then "The wavefunction is stable." after re-optimization.
        if sec_ok and sec_bad:
            sec_stable: bool | None = sec_ok.start() > sec_bad.start()
        elif sec_ok:
            sec_stable = True
        elif sec_bad:
            sec_stable = False
        else:
            sec_stable = None
        section_stabilities.append(sec_stable)
        if sec_stable is not None:
            stable = sec_stable

    cm_matches = _CHARGE_MULT_RE.findall(last_section) or _CHARGE_MULT_RE.findall(text)
    charge = int(cm_matches[-1][0]) if cm_matches else 0
    mult = int(cm_matches[-1][1]) if cm_matches else 1

    scf_matches = _SCF_DONE_RE.findall(last_section) or _SCF_DONE_RE.findall(text)
    scf_hartree = float(scf_matches[-1]) if scf_matches else None

    zpe_matches = _ZPE_RE.findall(last_section) or _ZPE_RE.findall(text)
    zpe_hartree = float(zpe_matches[-1]) if zpe_matches else None

    fallback_freqs: list[float] = []
    for line in _FREQS_LINE_RE.findall(last_section):
        for tok in line.split():
            try:
                fallback_freqs.append(float(tok))
            except ValueError:
                continue

    return {
        "normal_termination": normal_termination,
        "error_code": error_code,
        "s2_before": s2_before,
        "s2_after": s2_after,
        "stable": stable,
        "charge": charge,
        "multiplicity": mult,
        "scf_hartree": scf_hartree,
        "zpe_hartree": zpe_hartree,
        "fallback_freqs": fallback_freqs,
        "link1_sections": len(sections),
        "normal_terminations_count": normal_count,
        "section_stabilities": section_stabilities,
        "error_hints": _extract_error_hints(last_section),
    }


def _extract_last_orientation(text: str) -> Cluster | None:
    """Fallback geometry extractor from Standard/Input orientation tables."""
    pattern = re.compile(
        r"(?:Standard|Input) orientation:.*?"
        r"Center\s+Atomic\s+Atomic\s+Coordinates.*?\n\s*-+\n(.*?)\n\s*-+",
        re.DOTALL,
    )
    matches = pattern.findall(text)
    if not matches:
        return None
    block = matches[-1]
    symbols: list[str] = []
    positions: list[tuple[float, float, float]] = []
    for line in block.splitlines():
        parts = line.split()
        if len(parts) >= 6:
            try:
                atomic_num = int(parts[1])
                x, y, z = float(parts[3]), float(parts[4]), float(parts[5])
            except ValueError:
                continue
            symbols.append(Element.from_Z(atomic_num).symbol)
            positions.append((x, y, z))
    if not symbols:
        return None
    return Cluster(symbols=symbols, positions=positions, label="parsed")


def _ccread_quiet(log_path: Path) -> Any:
    """Invoke cclib without polluting stdout/warnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return cclib.io.ccread(str(log_path), loglevel=logging.ERROR)  # type: ignore[attr-defined]


def parse_gaussian_log(log_path: Path, job_id: str | None = None) -> CalcResult:
    """Parse a Gaussian output log into a CalcResult.

    Uses cclib as the primary parser and supplements it with regex extraction
    for <S^2>, wavefunction stability, Lnnnn error codes, Link1 segmentation,
    and fault-log fallbacks.
    """
    path = Path(log_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    sup = _extract_regex_supplements(text)
    resolved_job_id = job_id or path.stem

    data = _ccread_quiet(path)

    if data is not None and hasattr(data, "atomnos") and hasattr(data, "atomcoords"):
        symbols = [Element.from_Z(int(z)).symbol for z in data.atomnos]
        coords = data.atomcoords[-1]
        positions = [(float(c[0]), float(c[1]), float(c[2])) for c in coords]
        geometry: Cluster | None = Cluster(
            symbols=symbols, positions=positions, label=resolved_job_id
        )
    else:
        fallback_geom = _extract_last_orientation(text)
        geometry = (
            fallback_geom.model_copy(update={"label": resolved_job_id})
            if fallback_geom is not None
            else None
        )

    charge = int(getattr(data, "charge", sup["charge"])) if data is not None else sup["charge"]
    mult = (
        int(getattr(data, "mult", sup["multiplicity"])) if data is not None else sup["multiplicity"]
    )
    state = ElectronicState(charge=charge, multiplicity=mult)

    energy_hartree: float | None = sup["scf_hartree"]
    if energy_hartree is None and data is not None and hasattr(data, "scfenergies"):
        if len(data.scfenergies) > 0:
            energy_hartree = float(data.scfenergies[-1]) * EV_TO_HA

    zpe_hartree: float | None = (
        float(data.zpve)
        if data is not None and getattr(data, "zpve", None) is not None
        else sup["zpe_hartree"]
    )
    enthalpy_hartree: float | None = (
        float(data.enthalpy)
        if data is not None and getattr(data, "enthalpy", None) is not None
        else None
    )
    free_energy_hartree: float | None = (
        float(data.freeenergy)
        if data is not None and getattr(data, "freeenergy", None) is not None
        else None
    )

    freqs_cm1: list[float] = []
    if data is not None and hasattr(data, "vibfreqs"):
        freqs_cm1 = [float(f) for f in data.vibfreqs]
    if not freqs_cm1 and sup["fallback_freqs"]:
        freqs_cm1 = [float(f) for f in sup["fallback_freqs"]]
    imag_freqs = [f for f in freqs_cm1 if f < 0.0]

    mo_energies_hartree: list[list[float]] = []
    if data is not None and hasattr(data, "moenergies"):
        for channel in data.moenergies:
            mo_energies_hartree.append([float(e) * EV_TO_HA for e in channel])

    homo_indices: list[int] = []
    if data is not None and hasattr(data, "homos"):
        homo_indices = [int(idx) for idx in data.homos]

    charges: dict[str, list[float]] = {}
    if data is not None and hasattr(data, "atomcharges"):
        for key, vals in data.atomcharges.items():
            charges[str(key)] = [float(v) for v in vals]

    spins: dict[str, list[float]] = {}
    if data is not None and hasattr(data, "atomspins"):
        for key, vals in data.atomspins.items():
            spins[str(key)] = [float(v) for v in vals]

    return CalcResult(
        job_id=resolved_job_id,
        normal_termination=bool(sup["normal_termination"]),
        error_code=sup["error_code"],
        state=state,
        final_geometry=geometry,
        energy_hartree=energy_hartree,
        zpe_hartree=zpe_hartree,
        thermal_enthalpy_hartree=enthalpy_hartree,
        thermal_free_energy_hartree=free_energy_hartree,
        freqs_cm1=freqs_cm1,
        imag_freqs=imag_freqs,
        stable=sup["stable"],
        mo_energies_hartree=mo_energies_hartree,
        homo_indices=homo_indices,
        s2_before=sup["s2_before"],
        s2_after=sup["s2_after"],
        charges=charges,
        spins=spins,
        metadata={
            "source_file": str(path),
            "link1_sections": sup["link1_sections"],
            "normal_terminations_count": sup["normal_terminations_count"],
            "section_stabilities": sup["section_stabilities"],
            "error_hints": sup["error_hints"],
        },
    )

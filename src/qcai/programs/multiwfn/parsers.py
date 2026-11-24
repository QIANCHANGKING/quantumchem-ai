"""Strict Multiwfn 3.8(dev) output parsers with mandatory version verification."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from qcai.core.models import OrbitalComposition, PDOSData
from qcai.core.physics import HA_TO_EV
from qcai.programs.multiwfn.templates import SUPPORTED_MULTIWFN_VERSION

_VERSION_RE = re.compile(r"Version\s+([^\s,]+)", re.IGNORECASE)
_CHARGE_ROW_RE = re.compile(r"^\s*Atom\s+(\d+)\(([A-Za-z]+)\):\s*([+-]?\d+(?:\.\d+)?)\s*$")
_FUZZY_SPIN_ROW_RE = re.compile(
    r"^\s*(\d+)\(([A-Za-z]+)\)\s+([+-]?\d+(?:\.\d+)?)\s+[+-]?\d+(?:\.\d+)?\s+[+-]?\d+(?:\.\d+)?"
)
_ORBITAL_HDR_RE = re.compile(
    r"Orbital:\s*(\d+)\s+Energy\(a\.u\.\):\s*([+-]?\d+(?:\.\d+)?)\s+"
    r"Occ:\s*([+-]?\d+(?:\.\d+)?)\s+Type:\s*(\S+)"
)
_SHELL_COMP_RE = re.compile(
    r"s:\s*([+-]?\d+(?:\.\d+)?)\s+p:\s*([+-]?\d+(?:\.\d+)?)\s+"
    r"d:\s*([+-]?\d+(?:\.\d+)?)\s+f:\s*([+-]?\d+(?:\.\d+)?)"
)
_ATOM_COMP_RE = re.compile(r"^\s*Atom\s+(\d+)\(([A-Za-z]+)\)\s*:\s*([+-]?\d+(?:\.\d+)?)\s*%")


class MultiwfnVersionError(RuntimeError):
    """Raised when Multiwfn version banner is missing or mismatches template version."""


def verify_multiwfn_version(stdout_text: str, expected: str = SUPPORTED_MULTIWFN_VERSION) -> str:
    """Verify Multiwfn banner matches the version our templates were built against."""
    match = _VERSION_RE.search(stdout_text)
    if match is None:
        raise MultiwfnVersionError(
            f"Multiwfn 输出缺少版本声明，无法验证是否匹配模板要求 {expected!r}"
        )
    found = match.group(1).strip()
    if found != expected:
        raise MultiwfnVersionError(
            f"Multiwfn 版本不匹配：模板绑定 {expected!r}，实际输出为 {found!r}，拒绝猜测式解析"
        )
    return found


def _extract_charge_blocks(stdout_text: str) -> list[list[float]]:
    blocks: list[list[float]] = []
    lines = stdout_text.splitlines()
    i = 0
    while i < len(lines):
        if "Final atomic charges:" in lines[i]:
            vals: list[float] = []
            i += 1
            while i < len(lines):
                m = _CHARGE_ROW_RE.match(lines[i])
                if m:
                    vals.append(float(m.group(3)))
                    i += 1
                elif not lines[i].strip() and not vals:
                    i += 1
                else:
                    break
            if vals:
                blocks.append(vals)
        else:
            i += 1
    return blocks


def _extract_fuzzy_spin_block(stdout_text: str) -> list[float] | None:
    lines = stdout_text.splitlines()
    for idx, line in enumerate(lines):
        if "Atomic space" in line and "% of sum" in line:
            vals: list[float] = []
            for row in lines[idx + 1 :]:
                m = _FUZZY_SPIN_ROW_RE.match(row)
                if m:
                    vals.append(float(m.group(3)))
                elif "Summing up" in row or not row.strip():
                    break
            if vals:
                return vals
    return None


def parse_charge_spin(
    stdout_text: str, *, expected_version: str = SUPPORTED_MULTIWFN_VERSION
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Parse Multiwfn `charge_spin` output into `(charges, spins)` dicts."""
    verify_multiwfn_version(stdout_text, expected=expected_version)

    blocks = _extract_charge_blocks(stdout_text)
    if not blocks:
        raise ValueError("Multiwfn charge_spin 输出中未找到 Final atomic charges 数据块")

    charges: dict[str, list[float]] = {"hirshfeld": blocks[0]}
    if len(blocks) >= 2:
        charges["adch"] = blocks[1]

    spins: dict[str, list[float]] = {}
    fuzzy_spin = _extract_fuzzy_spin_block(stdout_text)
    if fuzzy_spin is not None:
        spins["hirshfeld"] = fuzzy_spin
    return charges, spins


def _read_dos_curve_columns(curve_path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in curve_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s:
            continue
        # Multiwfn Fortran fixed-width formatting can abut negative values (e.g. "0.495860-1338.138")
        fixed = re.sub(r"(?<=\d)-", " -", s)
        parts = fixed.split()
        try:
            vals = [float(x) for x in parts]
        except ValueError as exc:
            raise ValueError(f"Unparseable row in {curve_path}: {s!r}") from exc
        rows.append(vals)
    if not rows:
        raise ValueError(f"DOS curve file is empty or invalid: {curve_path}")
    n_cols = len(rows[0])
    if any(len(r) != n_cols for r in rows):
        raise ValueError(f"Inconsistent column counts in {curve_path}")
    cols: list[list[float]] = [[r[c] for r in rows] for c in range(n_cols)]
    return cols


def parse_pdos(
    stdout_text: str,
    curve_alpha_path: Path,
    fragment_names: list[str],
    *,
    curve_beta_path: Path | None = None,
    expected_version: str = SUPPORTED_MULTIWFN_VERSION,
) -> PDOSData:
    """Parse Multiwfn Menu 10 DOS_curve.txt (and optional beta curve) into PDOSData."""
    verify_multiwfn_version(stdout_text, expected=expected_version)
    cols_a = _read_dos_curve_columns(curve_alpha_path)
    if len(cols_a) < 3:
        raise ValueError(f"Expected >=3 columns in {curve_alpha_path}, got {len(cols_a)}")

    energies_ev = cols_a[0]
    tdos_alpha = cols_a[1]
    pdos_series: dict[str, list[float]] = {}

    if curve_beta_path is None:
        for i, frag in enumerate(fragment_names):
            col_idx = 3 + i
            if col_idx < len(cols_a):
                pdos_series[frag] = cols_a[col_idx]
        return PDOSData(
            energies_ev=energies_ev,
            tdos_alpha=tdos_alpha,
            tdos_beta=None,
            pdos_series=pdos_series,
        )

    cols_b = _read_dos_curve_columns(curve_beta_path)
    if len(cols_b) < 3:
        raise ValueError(f"Expected >=3 columns in {curve_beta_path}, got {len(cols_b)}")
    tdos_beta = [-v for v in cols_b[1]]
    for i, frag in enumerate(fragment_names):
        col_idx = 3 + i
        if col_idx < len(cols_a):
            pdos_series[f"{frag}_alpha"] = cols_a[col_idx]
        if col_idx < len(cols_b):
            pdos_series[f"{frag}_beta"] = [-v for v in cols_b[col_idx]]

    return PDOSData(
        energies_ev=energies_ev,
        tdos_alpha=tdos_alpha,
        tdos_beta=tdos_beta,
        pdos_series=pdos_series,
    )


def parse_orb_comp(
    stdout_text: str, *, expected_version: str = SUPPORTED_MULTIWFN_VERSION
) -> list[OrbitalComposition]:
    """Parse Multiwfn Menu 8 orbital composition output into OrbitalComposition list."""
    verify_multiwfn_version(stdout_text, expected=expected_version)

    matches = list(_ORBITAL_HDR_RE.finditer(stdout_text))
    if not matches:
        raise ValueError("Multiwfn orb_comp 输出中未找到 Orbital: 块")

    results: list[OrbitalComposition] = []
    for idx, m in enumerate(matches):
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(stdout_text)
        block = stdout_text[start:end]

        mo_index = int(m.group(1))
        energy_au = float(m.group(2))
        raw_type = m.group(4).strip().lower()
        spin: Literal["alpha", "beta", "restricted"]
        if "alpha" in raw_type:
            spin = "alpha"
        elif "beta" in raw_type:
            spin = "beta"
        else:
            spin = "restricted"

        contributions: dict[str, float] = {}
        shell_m = _SHELL_COMP_RE.search(block)
        if shell_m:
            contributions["shell_s"] = float(shell_m.group(1))
            contributions["shell_p"] = float(shell_m.group(2))
            contributions["shell_d"] = float(shell_m.group(3))
            contributions["shell_f"] = float(shell_m.group(4))

        for line in block.splitlines():
            am = _ATOM_COMP_RE.match(line)
            if am:
                atom_key = f"{am.group(1)}{am.group(2)}"
                contributions[atom_key] = float(am.group(3))

        results.append(
            OrbitalComposition(
                mo_index=mo_index,
                spin=spin,
                energy_ev=round(energy_au * HA_TO_EV, 6),
                contributions=contributions,
            )
        )
    return results

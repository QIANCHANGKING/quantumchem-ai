"""Custom custodian-compatible Gaussian error handlers for cluster jobs."""

from __future__ import annotations

import math
import random
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:

    class _CustodianBase:
        pass
else:
    try:
        from custodian.custodian import ErrorHandler as _CustodianBase
    except ImportError:

        class _CustodianBase:
            pass


_FREQ_LINE_RE = re.compile(r"Frequencies\s+--\s+(.*)")
_MODE_TABLE_HDR_RE = re.compile(r"^\s*Atom\s+AN\s+X\s+Y\s+Z")
_INSTAB_RE = re.compile(r"The wavefunction has an .*?instability", re.IGNORECASE)
_STABLE_OK_RE = re.compile(r"The wavefunction is (?:already )?stable(?:\.| under)", re.IGNORECASE)
_NORMAL_TERM_RE = re.compile(r"Normal termination of Gaussian", re.IGNORECASE)
_SCF_KW_RE = re.compile(r"\bscf=(?:\([^)]*\)|[^\s]+)", re.IGNORECASE)
_GEN_KW_RE = re.compile(r"/gen\b", re.IGNORECASE)

_SCF_ESCALATION_LADDER: tuple[str, ...] = (
    "scf=(xqc,maxcycle=512,vshift=500,fermi,novaracc)",
    "scf=(xqc,maxcycle=512,vshift=800,fermi,novaracc,ndamp=30)",
    "scf=(maxcycle=512,vshift=1000,fermi,novaracc,ndamp=40)",
)


def _find_geometry_end_index(lines: list[str]) -> int | None:
    """Locate the line index right after the first Cartesian geometry block."""
    n = len(lines)
    start_scan = 0
    # Skip past first route block (#...) and title block so title text never tricks int parsing.
    hash_idx = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("#")), None)
    if hash_idx is not None:
        i = hash_idx
        while i < n and lines[i].strip():
            i += 1
        while i < n and not lines[i].strip():
            i += 1
        while i < n and lines[i].strip():
            i += 1
        while i < n and not lines[i].strip():
            i += 1
        start_scan = i

    cm_idx: int | None = None
    for idx in range(start_scan, n):
        parts = lines[idx].strip().split()
        if len(parts) == 2:
            try:
                int(parts[0])
                mult = int(parts[1])
                if mult >= 1:
                    cm_idx = idx
                    break
            except ValueError:
                continue
    if cm_idx is None:
        for idx, ln in enumerate(lines):
            parts = ln.strip().split()
            if len(parts) == 2:
                try:
                    int(parts[0])
                    mult = int(parts[1])
                    if mult >= 1:
                        cm_idx = idx
                        break
                except ValueError:
                    continue
    if cm_idx is None:
        return None

    end_idx = cm_idx + 1
    while end_idx < n and lines[end_idx].strip():
        end_idx += 1
    return end_idx


def extract_gjf_tail_after_geometry(gjf_text: str) -> str:
    """Return all Gen/GenECP/ECP/--Link1-- content following the first geometry block."""
    lines = gjf_text.replace("\r\n", "\n").splitlines()
    end_idx = _find_geometry_end_index(lines)
    if end_idx is None:
        return ""
    return "\n".join(lines[end_idx:]).strip()


def restore_gjf_tail_if_lost(original_text: str, rewritten_text: str) -> str:
    """Restore GenECP keyword and basis/ECP/--Link1-- tail if a handler stripped them."""
    orig_norm = original_text.replace("\r\n", "\n")
    rewritten_norm = rewritten_text.replace("\r\n", "\n")

    orig_lines = orig_norm.splitlines()
    new_lines = rewritten_norm.splitlines()

    # Preserve /GenECP on first route block if pymatgen/custodian downgraded it to /Gen
    orig_route = " ".join(ln.strip() for ln in orig_lines if ln.lstrip().startswith("#"))
    if "/genecp" in orig_route.lower():
        for idx, ln in enumerate(new_lines):
            if ln.lstrip().startswith("#"):
                if "/genecp" not in ln.lower() and _GEN_KW_RE.search(ln):
                    new_lines[idx] = _GEN_KW_RE.sub("/GenECP", ln, count=1)
                break

    rewritten_norm = "\n".join(new_lines)
    orig_tail = extract_gjf_tail_after_geometry(orig_norm)
    new_tail = extract_gjf_tail_after_geometry(rewritten_norm)

    lost = bool(orig_tail) and (
        not new_tail
        or ("-ECP" in orig_tail.upper() and "-ECP" not in new_tail.upper())
        or ("--LINK1--" in orig_tail.upper() and "--LINK1--" not in new_tail.upper())
        or ("****" in orig_tail and "****" not in new_tail)
    )
    if lost:
        end_idx = _find_geometry_end_index(new_lines)
        if end_idx is not None:
            head = "\n".join(new_lines[:end_idx]).rstrip()
            return f"{head}\n\n{orig_tail}\n\n"
    return rewritten_norm.rstrip() + "\n\n"


def _first_route_scf_keyword(lines: list[str]) -> str:
    n = len(lines)
    for i in range(n):
        if lines[i].lstrip().startswith("#"):
            block: list[str] = []
            j = i
            while j < n and lines[j].strip():
                block.append(lines[j].strip())
                j += 1
            match = _SCF_KW_RE.search(" ".join(block))
            if match:
                return match.group(0).lower().replace(" ", "")
            break
    return ""


def upgrade_scf_route_line(gjf_text: str, attempt_index: int) -> tuple[str, str]:
    """Escalate SCF convergence keywords on all route sections without touching basis/ECP."""
    lines = gjf_text.replace("\r\n", "\n").splitlines()
    current_scf = _first_route_scf_keyword(lines)
    idx = min(max(0, attempt_index), len(_SCF_ESCALATION_LADDER) - 1)
    if (
        current_scf
        and _SCF_ESCALATION_LADDER[idx].lower() == current_scf
        and idx + 1 < len(_SCF_ESCALATION_LADDER)
    ):
        idx += 1
    scf_kw = _SCF_ESCALATION_LADDER[idx]
    out_lines: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].lstrip().startswith("#"):
            block: list[str] = []
            while i < n and lines[i].strip():
                block.append(lines[i].strip())
                i += 1
            route_str = " ".join(block)
            if _SCF_KW_RE.search(route_str):
                route_str = _SCF_KW_RE.sub(scf_kw, route_str)
            else:
                route_str = f"{route_str} {scf_kw}"
            out_lines.append(route_str)
        else:
            out_lines.append(lines[i])
            i += 1
    return "\n".join(out_lines).rstrip() + "\n\n", scf_kw


def _extract_freqs(text: str) -> list[float]:
    freqs: list[float] = []
    for line in _FREQ_LINE_RE.findall(text):
        for tok in line.split():
            try:
                freqs.append(float(tok))
            except ValueError:
                continue
    return freqs


def _extract_first_mode_displacement(text: str) -> list[tuple[float, float, float]] | None:
    """Parse displacement vector of the first normal mode in Gaussian frequency output."""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if _MODE_TABLE_HDR_RE.match(line):
            disps: list[tuple[float, float, float]] = []
            for row in lines[idx + 1 :]:
                parts = row.split()
                if len(parts) < 5:
                    break
                try:
                    int(parts[0])
                    int(parts[1])
                    dx, dy, dz = float(parts[2]), float(parts[3]), float(parts[4])
                except ValueError:
                    break
                disps.append((dx, dy, dz))
            if disps:
                return disps
    return None


def _perturb_gjf_geometry(
    gjf_path: Path,
    disps: list[tuple[float, float, float]] | None,
    step_scale: float = 0.25,
) -> bool:
    """Perturb Cartesian geometry block in a .gjf file along disps (or random fallback)."""
    lines = gjf_path.read_text(encoding="utf-8", errors="replace").splitlines()
    # Locate charge/multiplicity line (e.g. "0 1" or "-1 2")
    cm_idx: int | None = None
    for i, line in enumerate(lines):
        parts = line.strip().split()
        if len(parts) == 2:
            try:
                int(parts[0])
                m = int(parts[1])
                if m >= 1:
                    cm_idx = i
                    break
            except ValueError:
                continue
    if cm_idx is None:
        return False

    coord_indices: list[int] = []
    for i in range(cm_idx + 1, len(lines)):
        if not lines[i].strip():
            break
        coord_indices.append(i)
    if not coord_indices:
        return False

    rng = random.Random(42)
    for atom_i, line_idx in enumerate(coord_indices):
        parts = lines[line_idx].split()
        if len(parts) < 4:
            continue
        try:
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError:
            continue
        if disps is not None and atom_i < len(disps):
            dx, dy, dz = disps[atom_i]
        else:
            dx, dy, dz = rng.uniform(-0.1, 0.1), rng.uniform(-0.1, 0.1), rng.uniform(-0.1, 0.1)
        norm = math.sqrt(dx * dx + dy * dy + dz * dz)
        if norm > 1e-8 and disps is not None:
            dx, dy, dz = dx * step_scale, dy * step_scale, dz * step_scale
        lines[line_idx] = f"{parts[0]:4s} {x + dx:12.6f} {y + dy:12.6f} {z + dz:12.6f}"

    gjf_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _add_route_keyword(gjf_path: Path, keyword: str) -> bool:
    """Ensure a keyword is present on the Gaussian route line (#...)."""
    lines = gjf_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            if keyword.lower() not in line.lower():
                lines[i] = f"{line.rstrip()} {keyword}"
                gjf_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return True
            return False
    return False


class ImaginaryFreqHandler(_CustodianBase):
    """Custodian handler that perturbs geometry along imaginary mode and re-optimizes."""

    is_monitor = False

    def __init__(
        self,
        input_file: str = "job.gjf",
        output_file: str = "job.log",
        threshold_cm1: float = -15.0,
        step_scale: float = 0.25,
    ) -> None:
        self.input_file = input_file
        self.output_file = output_file
        self.threshold_cm1 = threshold_cm1
        self.step_scale = step_scale

    def check(self, directory: str = "./") -> bool:
        log_path = Path(directory) / self.output_file
        if not log_path.exists():
            return False
        text = log_path.read_text(encoding="utf-8", errors="replace")
        if not _NORMAL_TERM_RE.search(text):
            return False
        freqs = _extract_freqs(text)
        return any(f < self.threshold_cm1 for f in freqs)

    def correct(self, directory: str = "./") -> dict[str, Any]:
        log_path = Path(directory) / self.output_file
        gjf_path = Path(directory) / self.input_file
        text = log_path.read_text(encoding="utf-8", errors="replace")
        disps = _extract_first_mode_displacement(text)
        perturbed = _perturb_gjf_geometry(gjf_path, disps, step_scale=self.step_scale)
        if "opt" not in gjf_path.read_text(encoding="utf-8", errors="replace").lower():
            _add_route_keyword(gjf_path, "opt=(maxcycles=100)")
        if "scf=" not in gjf_path.read_text(encoding="utf-8", errors="replace").lower():
            _add_route_keyword(gjf_path, "scf=(xqc,maxcycle=500)")
        return {
            "errors": ["imaginary_freq"],
            "actions": [
                {
                    "action": "perturb_along_imag_mode" if perturbed else "no_geom_block",
                    "step_scale": self.step_scale,
                }
            ],
        }


class InstabilityHandler(_CustodianBase):
    """Custodian handler that enables `stable=opt` when wavefunction instability is found."""

    is_monitor = False

    def __init__(
        self,
        input_file: str = "job.gjf",
        output_file: str = "job.log",
    ) -> None:
        self.input_file = input_file
        self.output_file = output_file

    def check(self, directory: str = "./") -> bool:
        log_path = Path(directory) / self.output_file
        gjf_path = Path(directory) / self.input_file
        if not log_path.exists():
            return False
        if (
            gjf_path.exists()
            and "stable=opt" in gjf_path.read_text(encoding="utf-8", errors="replace").lower()
        ):
            return False
        text = log_path.read_text(encoding="utf-8", errors="replace")
        bad_matches = list(_INSTAB_RE.finditer(text))
        if not bad_matches:
            return False
        ok_matches = list(_STABLE_OK_RE.finditer(text))
        if ok_matches and ok_matches[-1].start() > bad_matches[-1].start():
            return False
        return True

    def correct(self, directory: str = "./") -> dict[str, Any]:
        gjf_path = Path(directory) / self.input_file
        added = _add_route_keyword(gjf_path, "stable=opt")
        return {
            "errors": ["wavefunction_instability"],
            "actions": [{"action": "add_stable_opt", "modified": added}],
        }

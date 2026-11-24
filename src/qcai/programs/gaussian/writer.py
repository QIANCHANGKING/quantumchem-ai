"""Gaussian 16 input writer and basis_set_exchange coverage checker."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import basis_set_exchange as bse
from ase.data import atomic_numbers
from pymatgen.io.gaussian import GaussianInput

from qcai.core.models import CalcSpec, Cluster, ElectronicState
from qcai.core.physics import validate_electronic_state

_GAUSSIAN_BASIS_MAP: dict[str, str] = {
    "def2-svp": "def2SVP",
    "def2svp": "def2SVP",
    "def2-tzvp": "def2TZVP",
    "def2tzvp": "def2TZVP",
    "def2-qzvp": "def2QZVP",
    "def2qzvp": "def2QZVP",
    "def2-tzvpp": "def2TZVPP",
    "def2tzvpp": "def2TZVPP",
    "lanl2dz": "LANL2DZ",
    "6-31g*": "6-31G(d)",
    "6-31g(d)": "6-31G(d)",
    "6-31g**": "6-31G(d,p)",
    "6-31g(d,p)": "6-31G(d,p)",
    "6-311g**": "6-311G(d,p)",
    "6-311g(d,p)": "6-311G(d,p)",
    "cc-pvdz": "cc-pVDZ",
    "cc-pvtz": "cc-pVTZ",
}

# Gaussian 16 built-in element coverage by atomic number (excludes Ce-Lu for def2, etc.).
_G16_DEF2_BUILTIN = frozenset(range(1, 58)) | frozenset(range(72, 87))
_G16_LANL2DZ_BUILTIN = frozenset({1}) | frozenset(range(3, 58)) | frozenset(range(72, 84))
_G16_POPLE_BUILTIN = frozenset(range(1, 37))
_G16_CC_BUILTIN = frozenset(range(1, 19)) | frozenset(range(20, 37))

_GAUSSIAN_BUILTIN_ELEMENTS: dict[str, frozenset[int]] = {
    "def2SVP": _G16_DEF2_BUILTIN,
    "def2TZVP": _G16_DEF2_BUILTIN,
    "def2QZVP": _G16_DEF2_BUILTIN,
    "def2TZVPP": _G16_DEF2_BUILTIN,
    "LANL2DZ": _G16_LANL2DZ_BUILTIN,
    "6-31G(d)": _G16_POPLE_BUILTIN,
    "6-31G(d,p)": _G16_POPLE_BUILTIN,
    "6-311G(d,p)": _G16_POPLE_BUILTIN,
    "cc-pVDZ": _G16_CC_BUILTIN,
    "cc-pVTZ": _G16_CC_BUILTIN,
}

_G16_GD3_MAX_Z = 94

_BSE_ALIAS_MAP: dict[str, str] = {
    "def2svp": "def2-SVP",
    "def2tzvp": "def2-TZVP",
    "def2qzvp": "def2-QZVP",
    "def2tzvpp": "def2-TZVPP",
    "6-31g(d)": "6-31G*",
    "6-31g(d,p)": "6-31G**",
    "6-311g(d)": "6-311G*",
    "6-311g(d,p)": "6-311G**",
}

_FUNCTIONAL_MAP: dict[str, str] = {
    "PBE": "PBEPBE",
    "PBEPBE": "PBEPBE",
    "PBE0": "PBE1PBE",
    "PBE1PBE": "PBE1PBE",
    "TPSSH": "TPSSh",
    "B3LYP": "B3LYP",
    "BLYP": "BLYP",
    "BP86": "BP86",
    "M06": "M06",
    "M062X": "M062X",
    "WB97XD": "wB97XD",
}

_PREFERRED_ALTERNATIVES = [
    "def2-SVP",
    "def2-TZVP",
    "def2-QZVP",
    "LANL2DZ",
    "SARC-DKH2",
    "ANO-RCC",
]


class BasisCoverageError(ValueError):
    """Raised when a basis set does not cover all elements in the system."""

    def __init__(
        self,
        basis: str,
        missing_elements: list[str],
        alternatives: list[str],
    ) -> None:
        self.basis = basis
        self.missing_elements = missing_elements
        self.alternatives = alternatives
        alt_text = ", ".join(alternatives) if alternatives else "无推荐替代"
        super().__init__(f"基组 {basis!r} 不覆盖元素 {missing_elements}；可用替代基组: {alt_text}")


@dataclass(frozen=True)
class BasisCoverageReport:
    """Result of checking basis set element coverage via basis_set_exchange."""

    covered: bool
    missing_by_basis: dict[str, list[str]]
    alternatives: list[str]


def _to_bse_key(basis_name: str) -> str | None:
    stripped = basis_name.strip()
    aliased = _BSE_ALIAS_MAP.get(stripped.lower(), stripped)
    norm = str(bse.misc.transform_basis_name(aliased))
    meta = bse.get_metadata()
    if norm in meta:
        return norm
    return None


def _basis_supported_z(bse_key: str) -> set[int]:
    meta = bse.get_metadata()[bse_key]
    latest = meta["latest_version"]
    return {int(z) for z in meta["versions"][latest]["elements"]}


def find_covering_alternatives(elements: list[str], limit: int = 5) -> list[str]:
    """Query basis_set_exchange for basis sets covering all given elements."""
    req_z = {atomic_numbers[el] for el in elements}
    meta = bse.get_metadata()
    found: list[str] = []

    for cand in _PREFERRED_ALTERNATIVES:
        key = _to_bse_key(cand)
        if key and req_z.issubset(_basis_supported_z(key)):
            found.append(cand)
            if len(found) >= limit:
                return found

    for key, info in sorted(meta.items()):
        latest = info["latest_version"]
        supported = {int(z) for z in info["versions"][latest]["elements"]}
        if req_z.issubset(supported):
            disp = str(info.get("display_name", key))
            if disp not in found:
                found.append(disp)
            if len(found) >= limit:
                break
    return found


def check_basis_coverage(basis: str | dict[str, str], elements: list[str]) -> BasisCoverageReport:
    """Verify via basis_set_exchange that basis covers all elements."""
    unique_elements = list(dict.fromkeys(elements))
    missing_by_basis: dict[str, list[str]] = {}

    if isinstance(basis, str):
        bse_key = _to_bse_key(basis)
        if bse_key is None:
            raise ValueError(f"Unknown basis set in basis_set_exchange: {basis!r}")
        supported = _basis_supported_z(bse_key)
        missing = [el for el in unique_elements if atomic_numbers[el] not in supported]
        if missing:
            missing_by_basis[basis] = missing
    else:
        for el in unique_elements:
            if el not in basis:
                missing_by_basis.setdefault("<unassigned>", []).append(el)
                continue
            b_name = basis[el]
            bse_key = _to_bse_key(b_name)
            if bse_key is None:
                raise ValueError(f"Unknown basis set in basis_set_exchange: {b_name!r}")
            supported = _basis_supported_z(bse_key)
            if atomic_numbers[el] not in supported:
                missing_by_basis.setdefault(b_name, []).append(el)

    if missing_by_basis:
        alts = find_covering_alternatives(unique_elements)
        return BasisCoverageReport(
            covered=False,
            missing_by_basis=missing_by_basis,
            alternatives=alts,
        )
    return BasisCoverageReport(covered=True, missing_by_basis={}, alternatives=[])


def ensure_basis_coverage(basis: str | dict[str, str], elements: list[str]) -> None:
    """Validate basis coverage and raise BasisCoverageError if incomplete."""
    report = check_basis_coverage(basis, elements)
    if not report.covered:
        first_basis, missing = next(iter(report.missing_by_basis.items()))
        raise BasisCoverageError(first_basis, missing, report.alternatives)


def resolve_gaussian_functional(functional: str, multiplicity: int) -> str:
    """Map functional name to Gaussian keyword and apply U prefix for open-shell."""
    raw = functional.strip()
    upper = raw.upper()
    has_u = upper.startswith("U") and upper not in {"UGBS"}
    base_key = upper[1:] if has_u and upper[1:] in _FUNCTIONAL_MAP else upper
    mapped = _FUNCTIONAL_MAP.get(base_key, raw[1:] if has_u else raw)
    if multiplicity > 1:
        if not mapped.upper().startswith(("U", "RO")):
            return f"U{mapped}"
    return mapped


def _effective_dispersion(dispersion: str | None, elements: list[str]) -> str | None:
    """Drop GD3/GD3BJ when any element exceeds Gaussian 16's Z=94 (Pu) limit."""
    if not dispersion:
        return dispersion
    if dispersion.strip().upper() in {"GD3", "GD3BJ"}:
        if any(int(atomic_numbers[el]) > _G16_GD3_MAX_Z for el in elements):
            return None
    return dispersion


def resolve_gaussian_basis(
    basis: str | dict[str, str], elements: list[str]
) -> tuple[str, str | None]:
    """Return (route_basis_keyword, gen_basis_block_or_none)."""
    ensure_basis_coverage(basis, elements)
    unique_elements = list(dict.fromkeys(elements))

    if isinstance(basis, str):
        key = basis.strip().lower()
        builtin = _GAUSSIAN_BASIS_MAP.get(key)
        req_z = {int(atomic_numbers[el]) for el in unique_elements}
        if builtin is not None:
            supported_builtin = _GAUSSIAN_BUILTIN_ELEMENTS.get(builtin)
            if supported_builtin is not None and req_z.issubset(supported_builtin):
                return builtin, None
        # Generate explicit Gaussian94 block via BSE when outside G16 built-in coverage
        bse_name = _BSE_ALIAS_MAP.get(key, basis.strip())
        block = str(
            bse.get_basis(bse_name, elements=unique_elements, fmt="gaussian94", header=False)
        ).strip()
        keyword = "GenECP" if "-ECP" in block.upper() else "Gen"
        return keyword, block + "\n"

    # Per-element basis dictionary -> build combined Gen / GenECP block via BSE
    blocks: list[str] = []
    ecp_blocks: list[str] = []
    for el in unique_elements:
        b_name = basis[el]
        raw_block = str(
            bse.get_basis(b_name, elements=[el], fmt="gaussian94", header=False)
        ).strip()
        if "-ECP" in raw_block.upper():
            # Split basis part and ECP part on the first ECP header line
            lines = raw_block.splitlines()
            split_idx = next((i for i, ln in enumerate(lines) if "-ECP" in ln.upper()), len(lines))
            basis_part = "\n".join(lines[: max(0, split_idx - 1)]).strip()
            ecp_part = "\n".join(lines[max(0, split_idx - 1) :]).strip()
            if basis_part:
                blocks.append(basis_part)
            if ecp_part:
                ecp_blocks.append(ecp_part)
        else:
            blocks.append(raw_block)

    combined = "\n".join(blocks)
    if ecp_blocks:
        combined = combined + "\n\n" + "\n".join(ecp_blocks)
        return "GenECP", combined + "\n"
    return "Gen", combined + "\n"


def _format_link1_step(
    *,
    link0: dict[str, str],
    functional: str,
    basis_kw: str,
    dispersion: str | None,
    scf_strategy: str,
    nosymm: bool,
    extra_keywords: list[str],
    step_keywords: list[str],
    gen_basis: str | None = None,
) -> str:
    """Format a follow-up `--Link1--` Gaussian step reading geometry & guess from %chk."""
    lines: list[str] = []
    for k, v in sorted(link0.items()):
        lines.append(f"{k}={v}")
    parts = ["#P", f"{functional}/{basis_kw}"]
    parts.extend(step_keywords)
    if dispersion:
        parts.append(f"EmpiricalDispersion={dispersion}")
    if nosymm:
        parts.append("nosymm")
    if scf_strategy == "robust":
        parts.append("scf=(xqc,maxcycle=500)")
    parts.extend(kw.strip() for kw in extra_keywords if kw.strip())
    lines.append(" ".join(parts))
    lines.append("")
    if gen_basis is not None and basis_kw in {"Gen", "GenECP"}:
        lines.append(gen_basis.strip())
        lines.append("")
    return "\n".join(lines) + "\n"


def build_gaussian_input(
    cluster: Cluster,
    state: ElectronicState,
    spec: CalcSpec,
    *,
    nproc: int = 4,
    mem_gb: int = 8,
    chk_name: str | None = None,
    title: str | None = None,
) -> GaussianInput:
    """Build a pymatgen GaussianInput from Cluster, ElectronicState, and CalcSpec."""
    validate_electronic_state(cluster.symbols, state)
    mol = cluster.to_pymatgen(charge=state.charge, spin_multiplicity=state.multiplicity)
    functional = resolve_gaussian_functional(spec.functional, state.multiplicity)
    basis_kw, gen_basis = resolve_gaussian_basis(spec.basis, cluster.symbols)

    # Note: Gaussian forbids combining `opt` and `stable=opt` in one route line;
    # when both appear, build_gaussian_input emits the primary step and write_gaussian_input
    # appends `--Link1--` steps.
    has_stable = "stable" in spec.tasks
    has_opt_or_freq = any(t in spec.tasks for t in ("opt", "freq"))

    route_params: dict[str, str] = {}
    if has_stable and has_opt_or_freq:
        if "opt" in spec.tasks:
            route_params["opt"] = ""
        elif "freq" in spec.tasks:
            route_params["freq"] = ""
    else:
        for task in spec.tasks:
            if task == "sp":
                route_params["sp"] = ""
            elif task == "opt":
                route_params["opt"] = ""
            elif task == "freq":
                route_params["freq"] = ""
            elif task == "stable":
                route_params["stable"] = "opt"

    effective_dispersion = _effective_dispersion(spec.dispersion, cluster.symbols)
    if effective_dispersion:
        route_params["EmpiricalDispersion"] = effective_dispersion
    if spec.nosymm:
        route_params["nosymm"] = ""
    if spec.scf_strategy == "robust":
        route_params["scf"] = "(xqc,maxcycle=500)"
    for kw in spec.extra_keywords:
        if "=" in kw:
            k, v = kw.split("=", 1)
            route_params[k.strip()] = v.strip()
        elif kw.strip():
            route_params[kw.strip()] = ""

    link0: dict[str, str] = {
        "%nprocshared": str(nproc),
        "%mem": f"{mem_gb}GB",
    }
    if chk_name:
        link0["%chk"] = chk_name

    gin = GaussianInput(  # type: ignore[no-untyped-call]
        mol=mol,
        charge=state.charge,
        spin_multiplicity=state.multiplicity,
        title=title or f"{cluster.label} q={state.charge} M={state.multiplicity}",
        functional=functional,
        basis_set=basis_kw,
        route_parameters=route_params,
        link0_parameters=link0,
        dieze_tag="#P",
        gen_basis=gen_basis,
    )
    # GaussianInput forces basis_set='Gen' when gen_basis is given; restore GenECP if needed.
    if gen_basis is not None and basis_kw == "GenECP":
        gin.basis_set = "GenECP"
    return gin


def write_gaussian_input(
    cluster: Cluster,
    state: ElectronicState,
    spec: CalcSpec,
    out_path: Path,
    *,
    nproc: int = 4,
    mem_gb: int = 8,
    chk_name: str | None = None,
    title: str | None = None,
) -> Path:
    """Write a Gaussian .gjf file using Cartesian coordinates and return its path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    resolved_chk = chk_name or f"{out.stem}.chk"
    gin = build_gaussian_input(
        cluster,
        state,
        spec,
        nproc=nproc,
        mem_gb=mem_gb,
        chk_name=resolved_chk,
        title=title,
    )
    text = str(gin.to_str(cart_coords=True)).replace("\r\n", "\n").rstrip()  # type: ignore[no-untyped-call]

    has_stable = "stable" in spec.tasks
    has_opt = "opt" in spec.tasks
    has_freq = "freq" in spec.tasks
    if has_stable and (has_opt or has_freq):
        functional = resolve_gaussian_functional(spec.functional, state.multiplicity)
        basis_kw, _ = resolve_gaussian_basis(spec.basis, cluster.symbols)
        step_basis = "chkbasis" if basis_kw in {"Gen", "GenECP"} else basis_kw
        effective_dispersion = _effective_dispersion(spec.dispersion, cluster.symbols)
        link0 = {"%nprocshared": str(nproc), "%mem": f"{mem_gb}GB", "%chk": resolved_chk}
        sections = [text]
        sections.append(
            _format_link1_step(
                link0=link0,
                functional=functional,
                basis_kw=step_basis,
                dispersion=effective_dispersion,
                scf_strategy=spec.scf_strategy,
                nosymm=spec.nosymm,
                extra_keywords=spec.extra_keywords,
                step_keywords=["geom=allcheck", "guess=read", "stable=opt"],
            ).rstrip()
        )
        if has_opt and has_freq:
            sections.append(
                _format_link1_step(
                    link0=link0,
                    functional=functional,
                    basis_kw=step_basis,
                    dispersion=effective_dispersion,
                    scf_strategy=spec.scf_strategy,
                    nosymm=spec.nosymm,
                    extra_keywords=spec.extra_keywords,
                    step_keywords=["geom=allcheck", "guess=read", "freq"],
                ).rstrip()
            )
        full_text = "\n\n--Link1--\n".join(sections) + "\n\n"
    else:
        full_text = text + "\n\n"

    out.write_text(full_text, encoding="utf-8", newline="\n")
    return out


_NPROC_RE = re.compile(r"^\s*%nprocshared\s*=\s*(\d+)\s*$", re.IGNORECASE)
_NPROC_LINE_RE = re.compile(r"^\s*%nprocshared\s*=.*$", re.IGNORECASE)
_MEM_LINE_RE = re.compile(r"^\s*%mem\s*=.*$", re.IGNORECASE)


def read_gaussian_nproc(gjf_path: Path) -> int | None:
    """Return the first positive %nprocshared value from a Gaussian .gjf file."""
    p = Path(gjf_path)
    if not p.exists():
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        match = _NPROC_RE.match(line)
        if match:
            val = int(match.group(1))
            if val > 0:
                return val
    return None


def update_gaussian_link0_resources(gjf_path: Path, *, nproc: int, mem_gb: int) -> None:
    """Update %nprocshared and %mem across main and --Link1-- sections in a .gjf file."""
    p = Path(gjf_path)
    raw = p.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    saw_nproc = False
    saw_mem = False
    updated: list[str] = []
    for line in lines:
        if _NPROC_LINE_RE.match(line):
            updated.append(f"%nprocshared={nproc}")
            saw_nproc = True
        elif _MEM_LINE_RE.match(line):
            updated.append(f"%mem={mem_gb}GB")
            saw_mem = True
        else:
            updated.append(line)

    prefix: list[str] = []
    if not saw_nproc:
        prefix.append(f"%nprocshared={nproc}")
    if not saw_mem:
        prefix.append(f"%mem={mem_gb}GB")
    if prefix:
        updated = prefix + updated

    p.write_text("\n".join(updated), encoding="utf-8", newline="\n")

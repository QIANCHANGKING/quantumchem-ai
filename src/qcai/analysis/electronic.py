"""Electronic structure inductive functions (jellium electron count, gaps, charge transfer)."""

from __future__ import annotations

from collections import Counter

from pymatgen.core.periodic_table import Element

from qcai.core.models import CalcResult
from qcai.core.physics import HA_TO_EV, homo_lumo_gap_hartree

JELLIUM_SHELL_CLOSURES = frozenset({2, 8, 18, 20, 34, 40, 58})


def _element_jellium_valence(symbol: str) -> int:
    """Return itinerant valence electron count using periodic-table group only (Axiom A2)."""
    el = Element(symbol)
    grp = int(el.group)
    if grp in (1, 2):
        return grp
    if 11 <= grp <= 18:
        return grp - 10
    if 3 <= grp <= 10:
        return grp
    return 2


def valence_electron_count(symbols: list[str], charge: int = 0) -> int:
    """Compute cluster itinerant valence electron count for jellium shell analysis."""
    return sum(_element_jellium_valence(sym) for sym in symbols) - charge


def is_jellium_magic(n_valence: int) -> bool:
    """Return True if valence electron count matches spherical jellium shell closure."""
    return n_valence in JELLIUM_SHELL_CLOSURES


def homo_lumo_gap_ev(result: CalcResult) -> float | None:
    """Return HOMO-LUMO gap in eV (smaller of alpha/beta for open-shell)."""
    gap_ha = homo_lumo_gap_hartree(result.mo_energies_hartree, result.homo_indices)
    return gap_ha * HA_TO_EV if gap_ha is not None else None


def charge_transfer_by_element(
    charges: dict[str, list[float]], symbols: list[str]
) -> dict[str, float]:
    """Compute summed net atomic charge per chemical element (prefers Hirshfeld > ADCH > Mulliken)."""
    if not charges:
        return {}
    selected: list[float] | None = None
    for key in ("hirshfeld", "adch", "mulliken"):
        if key in charges and len(charges[key]) == len(symbols):
            selected = charges[key]
            break
    if selected is None:
        return {}
    totals: dict[str, float] = {}
    for sym, q in zip(symbols, selected, strict=True):
        totals[sym] = totals.get(sym, 0.0) + float(q)
    return {k: round(v, 6) for k, v in totals.items()}


def minority_dopant_charge_transfer(
    charges: dict[str, list[float]], symbols: list[str]
) -> float | None:
    """Return net charge on minority element(s) in multi-element clusters."""
    by_el = charge_transfer_by_element(charges, symbols)
    if len(by_el) <= 1:
        return None
    counts = Counter(symbols)
    min_cnt = min(counts.values())
    return round(sum(by_el[el] for el, cnt in counts.items() if cnt == min_cnt), 6)

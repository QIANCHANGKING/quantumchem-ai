"""Multiwfn stdin templates bound to Multiwfn Version 3.8(dev) (2025-Mar-10)."""

from __future__ import annotations

from typing import Literal

SUPPORTED_MULTIWFN_VERSION = "3.8(dev)"
SUPPORTED_MULTIWFN_DATE = "2025-Mar-10"


def build_charge_spin_stdin(*, open_shell: bool) -> str:
    """Build Multiwfn 3.8(dev) stdin script for Hirshfeld/ADCH charges and Hirshfeld spin."""
    lines = [
        "7",  # Population analysis and atomic charges
        "1",  # Hirshfeld atomic charge
        "1",  # Built-in atomic densities
        "n",  # Do not save .chg file
        "11",  # ADCH atomic charge
        "1",  # Built-in atomic densities
        "n",  # Do not save .chg file
        "0",  # Return to main menu
    ]
    if open_shell:
        lines.extend(
            [
                "15",  # Fuzzy atomic space analysis
                "-1",  # Partition method
                "3",  # Hirshfeld* (built-in atomic densities)
                "1",  # Integrate real-space function
                "5",  # Electron spin density
                "0",  # Return to main menu
            ]
        )
    lines.append("q")
    return "\n".join(lines) + "\n"


def build_pdos_stdin(
    elements: list[str],
    *,
    spin: Literal["restricted", "alpha", "beta"] = "restricted",
    fwhm_ev: float = 0.30,
) -> tuple[str, list[str]]:
    """Build Multiwfn 3.8(dev) stdin script for TDOS + PDOS (by element & s/p/d).

    Returns `(stdin_text, fragment_names)` matching columns 4..3+N of `DOS_curve.txt`.
    """
    unique_els = list(dict.fromkeys(elements))[:7]
    fragment_names: list[str] = [*unique_els, "s", "p", "d"]

    lines: list[str] = [
        "10",  # Plot DOS
        "8",  # Switch unit from a.u. to eV
        "3",  # Set FWHM in eV
        f"{fwhm_ev:.4f}",
    ]
    if spin == "alpha":
        lines.extend(["6", "1"])
    elif spin == "beta":
        lines.extend(["6", "2"])

    lines.append("-1")  # Define fragments
    frag_idx = 1
    for el in unique_els:
        lines.extend([str(frag_idx), f"e {el}", "q"])
        frag_idx += 1
    for ang in ("s", "p", "d"):
        lines.extend([str(frag_idx), f"l {ang}", "q"])
        frag_idx += 1
    lines.append("q")  # Save fragments and exit fragment menu

    lines.extend(
        [
            "0",  # Calculate and draw TDOS + PDOS + OPDOS
            "3",  # Export DOS_curve.txt and DOS_line.txt
            "0",  # Return from post-processing menu
            "-10",  # Return to main menu
            "q",  # Exit
        ]
    )
    return "\n".join(lines) + "\n", fragment_names


def build_orb_comp_stdin(*, open_shell: bool, targets: list[str] | None = None) -> str:
    """Build Multiwfn 3.8(dev) stdin script for frontier orbital composition (Menu 8)."""
    if targets is None:
        targets = ["ha-1", "ha", "hb", "la", "lb"] if open_shell else ["h-1", "h", "l", "l+1"]
    lines = ["8", "1", *targets, "0", "-10", "q"]
    return "\n".join(lines) + "\n"

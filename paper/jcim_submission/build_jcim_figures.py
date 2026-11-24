"""Generate pure-English publication-grade figures (Fig. 1-7) and ACS TOC graphic for JCIM."""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch
from PIL import Image
from playwright.sync_api import sync_playwright

from qcai.core.physics import HA_TO_EV, homo_lumo_gap_hartree
from qcai.programs.gaussian.parser import parse_gaussian_log
from qcai.programs.multiwfn import parse_charge_spin, parse_orb_comp, parse_pdos

matplotlib.use("Agg")

REPO_ROOT = Path(__file__).resolve().parents[2]
JCIM_DIR = Path(__file__).resolve().parent
FIG_DIR = JCIM_DIR / "figures"
GOLDEN_DIR = REPO_ROOT / "tests" / "data" / "golden"
MWFN_DIR = REPO_ROOT / "tests" / "data" / "multiwfn" / "al12cu"
VMD_TILES_DIR = REPO_ROOT / "projects" / "paper_tmp" / "vmd_tiles"
LN_SUMMARY_PATH = REPO_ROOT / "paper" / "data" / "ln_au5_summary.json"
ASSETS_DIR = REPO_ROOT / "assets"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "mathtext.fontset": "custom",
        "mathtext.rm": "Arial",
        "mathtext.it": "Arial:italic",
        "mathtext.bf": "Arial:bold",
        "axes.linewidth": 1.0,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "pdf.fonttype": 42,
        "svg.fonttype": "none",
    }
)


def _assert_no_cjk(text: str, label: str) -> None:
    if re.search(r"[\u4e00-\u9fff]", text):
        raise ValueError(f"CJK characters detected in {label}")


def _save_mpl_fig(fig: plt.Figure, stem: str, *, dpi: int = 600, tight: bool = True) -> list[Path]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    kw: dict[str, Any] = {"bbox_inches": "tight", "pad_inches": 0.06} if tight else {}
    for ext in ("png", "svg", "pdf"):
        out = FIG_DIR / f"{stem}.{ext}"
        fig.savefig(out, dpi=dpi, facecolor="white", **kw)
        paths.append(out)
    plt.close(fig)
    return paths


def build_fig1_architecture() -> list[Path]:
    """Generate pure-English Fig. 1 vector schematic (SVG, PDF, and 300-dpi PNG)."""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    svg_path = FIG_DIR / "fig1_architecture.svg"
    pdf_path = FIG_DIR / "fig1_architecture.pdf"
    png_path = FIG_DIR / "fig1_architecture.png"

    layers = [
        (
            "L1",
            "User Interface & Desktop Layer",
            "[C5, C6]",
            "6-Page Streamlit Workbench",
            "CLI &amp; Desktop Launcher",
            "OS Keyring · Credential Isolation",
            42,
        ),
        (
            "L2",
            "All-Element Rule Engine & Planner",
            "[C2, C3, C4]",
            "YAML Rules (AST 0-Elem Branch)",
            "Parity · Hund · BSE GenECP",
            "OLS Cost Fit · Budget Scaling",
            106,
        ),
        (
            "L3",
            "Idempotent Funnel & Deduplication",
            "[C7]",
            "SQLite State (Pause/Resume)",
            "Sym. Dopant · 3-Axis Kabsch",
            "S0–S7 Orchestration · Audits",
            170,
        ),
        (
            "L4",
            "Shared-HPC Scheduling & Self-Healing",
            "[C7, C8]",
            "ShellIO / setsid · Allowlist",
            "NUMA Probe · Load Throttle",
            "3-Step Link1 · 4f/Tail Repair",
            234,
        ),
        (
            "L5",
            "Deterministic Analysis & Visualization",
            "[C1, C4, C5, C8]",
            "cclib + Multiwfn 3.8(dev)",
            "FigureSpec → Origin / MPL",
            "Inertia-Aligned VMD · A4 PDF",
            298,
        ),
    ]

    contracts = [
        (86, 105, "ResearchRequest (composition, q, accuracy, budget)"),
        (150, 169, "CalcPlan + Decisions (Method, GenECP, Spin Window)"),
        (214, 233, "JobSpec + .gjf (3-section Link1, BSE ECP block)"),
        (278, 297, "CalcResult (.log / .fchk / .cube, all_issues)"),
    ]

    layer_svg_parts: list[str] = []
    for badge, title, clause, c1, c2, c3, y in layers:
        layer_svg_parts.append(
            f"""  <rect x="20" y="{y}" width="626" height="44" rx="1.5" fill="#ffffff" stroke="#334155" stroke-width="1"/>
  <rect x="20" y="{y}" width="32" height="44" rx="1" fill="#0f2557"/>
  <text x="36" y="{y + 26}" text-anchor="middle" fill="#ffffff" font-size="11.5" font-weight="bold">{badge}</text>
  <text x="60" y="{y + 15}" fill="#0f172a" font-size="10.4" font-weight="bold">{title}</text>
  <text x="638" y="{y + 14.5}" text-anchor="end" fill="#0f2557" font-size="9" font-weight="bold">{clause}</text>
  <rect x="60" y="{y + 20}" width="186" height="19" rx="1" fill="#f8fafc" stroke="#cbd5e1" stroke-width="0.75"/>
  <text x="153" y="{y + 33}" text-anchor="middle" fill="#334155" font-size="8.6">{c1}</text>
  <rect x="252" y="{y + 20}" width="190" height="19" rx="1" fill="#f8fafc" stroke="#cbd5e1" stroke-width="0.75"/>
  <text x="347" y="{y + 33}" text-anchor="middle" fill="#334155" font-size="8.6">{c2}</text>
  <rect x="448" y="{y + 20}" width="190" height="19" rx="1" fill="#f8fafc" stroke="#cbd5e1" stroke-width="0.75"/>
  <text x="543" y="{y + 33}" text-anchor="middle" fill="#334155" font-size="8.6">{c3}</text>"""
        )

    for y1, y2, label in contracts:
        ym = (y1 + y2) // 2 + 3
        layer_svg_parts.append(
            f"""  <line x1="156" y1="{y1}" x2="156" y2="{y2 - 2}" stroke="#1e293b" stroke-width="1.2" marker-end="url(#arr)"/>
  <rect x="166" y="{ym - 10}" width="368" height="13" rx="1" fill="#eff6ff" stroke="#bfdbfe" stroke-width="0.7"/>
  <text x="172" y="{ym}" fill="#1e3a8a" font-family="Consolas, 'Courier New', monospace" font-size="8.5">{label}</text>"""
        )

    stages = [
        ("S0 Plan", "Rule Engine", "YAML + BSE", "Budget Fit", "#e2e8f0", "#0f172a", "#64748b"),
        ("S1 Search", "ABCluster /", "Molclus /", "xTB · GA", "#e2e8f0", "#0f172a", "#64748b"),
        ("S2 Dedup", "Eigenvalue", "3-Axis Kabsch", "Sym. Dopant", "#cbd5e1", "#0f172a", "#475569"),
        ("S3 Screen", "PBE-D3BJ", "def2-SVP", "Energy Win.", "#cbd5e1", "#0f172a", "#475569"),
        ("S4 Refine", "PBE0 / TPSSh", "def2-TZVP", "Link1 + Stop", "#bfdbfe", "#0f2557", "#1e3a8a"),
        ("S5 Ref/Ion", "Free Atoms", "n±1 / VDE", "Level Parity", "#bfdbfe", "#0f2557", "#1e3a8a"),
        ("S6 Wavefn", "formchk", "Multiwfn", "PDOS / MO", "#93c5fd", "#0f2557", "#0f2557"),
        ("S7 Report", "10 Plot Kinds", "VMD + PDF", "Issue Audit", "#0f2557", "#ffffff", "#0f2557"),
    ]
    stage_svg_parts: list[str] = []
    for idx, (st_hdr, l1, l2, l3, hdr_fill, hdr_fg, brd) in enumerate(stages):
        sx = 22 + idx * 87
        stage_svg_parts.append(
            f"""  <rect x="{sx}" y="405" width="76" height="68" rx="1.5" fill="#ffffff" stroke="{brd}" stroke-width="1"/>
  <rect x="{sx}" y="405" width="76" height="19" rx="1" fill="{hdr_fill}"/>
  <text x="{sx + 38}" y="418" text-anchor="middle" fill="{hdr_fg}" font-size="9.3" font-weight="bold">{st_hdr}</text>
  <text x="{sx + 38}" y="436" text-anchor="middle" fill="#1e293b" font-size="8.3">{l1}</text>
  <text x="{sx + 38}" y="450" text-anchor="middle" fill="#1e293b" font-size="8.3">{l2}</text>
  <text x="{sx + 38}" y="464" text-anchor="middle" fill="#475569" font-size="8.1">{l3}</text>"""
        )
        if idx < len(stages) - 1:
            ax1 = sx + 76
            ax2 = sx + 85
            stage_svg_parts.append(
                f"""  <line x1="{ax1}" y1="439" x2="{ax2}" y2="439" stroke="#334155" stroke-width="1.15" marker-end="url(#arr)"/>"""
            )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1040 572" width="1040" height="572" font-family="Arial, Helvetica, sans-serif">
  <defs>
    <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#1e293b"/>
    </marker>
    <marker id="arr-crimson" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#881337"/>
    </marker>
    <marker id="arr-blue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#1e40af"/>
    </marker>
  </defs>

  <rect width="1040" height="572" fill="#ffffff"/>

  <!-- Panel (a) -->
  <rect x="10" y="8" width="646" height="350" rx="1.5" fill="#ffffff" stroke="#334155" stroke-width="1"/>
  <rect x="10" y="8" width="646" height="24" rx="1" fill="#f1f5f9"/>
  <line x1="10" y1="32" x2="656" y2="32" stroke="#0f2557" stroke-width="1.2"/>
  <text x="18" y="24" fill="#0f2557" font-size="11.2" font-weight="bold">(a) Five-Layer Deterministic Stack &amp; Inter-Layer Data Contracts</text>
{chr(10).join(layer_svg_parts)}

  <!-- Panel (b) -->
  <rect x="670" y="8" width="360" height="350" rx="1.5" fill="#ffffff" stroke="#334155" stroke-width="1"/>
  <rect x="670" y="8" width="360" height="24" rx="1" fill="#f1f5f9"/>
  <line x1="670" y1="32" x2="1030" y2="32" stroke="#0f2557" stroke-width="1.2"/>
  <text x="678" y="24" fill="#0f2557" font-size="11.2" font-weight="bold">(b) Design-Constitution LLM Closed-Loop Control (C1–C3, C6)</text>

  <rect x="682" y="42" width="256" height="46" rx="1.5" fill="#f8fafc" stroke="#334155" stroke-width="1"/>
  <text x="810" y="57" text-anchor="middle" fill="#0f172a" font-size="10.0" font-weight="bold">Intent Planning Agent (DeepSeek)</text>
  <text x="810" y="70" text-anchor="middle" fill="#1e3a8a" font-family="Consolas, 'Courier New', monospace" font-size="8.4">parse_natural_language_intent(history)</text>
  <text x="810" y="82" text-anchor="middle" fill="#475569" font-size="8.3">Single-Turn · Multi-Turn · Batch Proposals</text>

  <line x1="810" y1="88" x2="810" y2="103" stroke="#1e293b" stroke-width="1.15" marker-end="url(#arr)"/>

  <rect x="682" y="105" width="256" height="50" rx="1.5" fill="#fff1f2" stroke="#881337" stroke-width="1.2"/>
  <text x="810" y="120" text-anchor="middle" fill="#881337" font-size="9.5" font-weight="bold">C2/C3 Plan Guard (@output_validator)</text>
  <text x="690" y="135" fill="#334155" font-size="8.4">• Composition check rejects Ln/TM wildcards</text>
  <text x="690" y="148" fill="#334155" font-size="8.4">• build_plan() dry-run validates request &amp; proposals</text>

  <path d="M 938 130 L 954 130 L 954 65 L 940 65" fill="none" stroke="#881337" stroke-width="1.15" stroke-dasharray="3.5,2.5" marker-end="url(#arr-crimson)"/>
  <text x="959" y="92" fill="#881337" font-size="8.2" font-weight="bold">Invalid plan:</text>
  <text x="959" y="104" fill="#881337" font-family="Consolas, 'Courier New', monospace" font-size="8.1">ModelRetry</text>
  <text x="959" y="116" fill="#881337" font-size="8.0">(≤ 2 retries)</text>

  <line x1="680" y1="168" x2="1020" y2="168" stroke="#cbd5e1" stroke-width="0.9" stroke-dasharray="3,2"/>
  <text x="810" y="182" text-anchor="middle" fill="#475569" font-size="8.2">↑ Pass → Valid Request to L2  |  ↓ Summary-Only [C6]</text>

  <rect x="682" y="192" width="256" height="48" rx="1.5" fill="#f8fafc" stroke="#334155" stroke-width="1"/>
  <text x="810" y="207" text-anchor="middle" fill="#0f172a" font-size="10.0" font-weight="bold">Read-Only Analyst Agent (interpret_project)</text>
  <text x="810" y="220" text-anchor="middle" fill="#334155" font-size="8.4">6 read-only tools · No secrets or raw logs [C6]</text>
  <text x="810" y="233" text-anchor="middle" fill="#475569" font-size="8.3">Actions emit PendingActionRequest confirmation only</text>

  <line x1="810" y1="240" x2="810" y2="255" stroke="#1e293b" stroke-width="1.15" marker-end="url(#arr)"/>

  <rect x="682" y="257" width="256" height="54" rx="1.5" fill="#fff1f2" stroke="#881337" stroke-width="1.2"/>
  <text x="810" y="272" text-anchor="middle" fill="#881337" font-size="9.5" font-weight="bold">C1 Anti-Hallucination Guard (@output_validator)</text>
  <text x="690" y="287" fill="#334155" font-size="7.9">• Fact set ∪ units (Ha ↔ eV, kcal/mol, kJ/mol, %)</text>
  <text x="690" y="301" fill="#334155" font-size="8.3">• Rejects &amp; retries on any ungrounded number</text>

  <path d="M 938 284 L 954 284 L 954 216 L 940 216" fill="none" stroke="#881337" stroke-width="1.15" stroke-dasharray="3.5,2.5" marker-end="url(#arr-crimson)"/>
  <text x="959" y="244" fill="#881337" font-size="8.2" font-weight="bold">Ungrounded:</text>
  <text x="959" y="256" fill="#881337" font-family="Consolas, 'Courier New', monospace" font-size="8.1">ModelRetry</text>
  <text x="959" y="268" fill="#881337" font-size="8.0">(≤ 2 retries)</text>

  <line x1="810" y1="311" x2="810" y2="324" stroke="#1e293b" stroke-width="1.15" marker-end="url(#arr)"/>
  <rect x="682" y="326" width="256" height="22" rx="1" fill="#f1f5f9" stroke="#64748b" stroke-width="0.8"/>
  <text x="810" y="340.5" text-anchor="middle" fill="#0f172a" font-family="Consolas, 'Courier New', monospace" font-size="8.3">verified=True → Render | False → Blocked [C1]</text>

  <!-- Inter-Panel Connectors -->
  <line x1="646" y1="64" x2="680" y2="64" stroke="#1e40af" stroke-width="1.25" marker-end="url(#arr-blue)"/>
  <line x1="682" y1="130" x2="648" y2="130" stroke="#1e40af" stroke-width="1.25" marker-end="url(#arr-blue)"/>
  <path d="M 646 318 L 663 318 L 663 216 L 680 216" fill="none" stroke="#475569" stroke-width="1.15" stroke-dasharray="3,2" marker-end="url(#arr)"/>
  <line x1="333" y1="358" x2="333" y2="369" stroke="#0f2557" stroke-width="1.3" marker-end="url(#arr)"/>

  <!-- Panel (c) -->
  <rect x="10" y="370" width="1020" height="194" rx="1.5" fill="#ffffff" stroke="#334155" stroke-width="1"/>
  <rect x="10" y="370" width="1020" height="24" rx="1" fill="#f1f5f9"/>
  <line x1="10" y1="394" x2="1030" y2="394" stroke="#0f2557" stroke-width="1.2"/>
  <text x="18" y="386" fill="#0f2557" font-size="11.2" font-weight="bold">(c) S0–S7 Multi-Fidelity Funnel Pipeline, Registry[T] Plugins &amp; Constitutional Gates</text>

{chr(10).join(stage_svg_parts)}

  <polygon points="109,482 356,488 532,493 707,496 707,510 532,513 356,518 109,524" fill="#f1f5f9" stroke="#64748b" stroke-width="0.9"/>
  <rect x="22" y="482" width="76" height="42" rx="1" fill="#f8fafc" stroke="#cbd5e1" stroke-width="0.8"/>
  <text x="60" y="500" text-anchor="middle" fill="#334155" font-size="8.2" font-weight="bold">Search→Conv.</text>
  <text x="60" y="514" text-anchor="middle" fill="#475569" font-size="7.9">Multi-Fidelity</text>
  <text x="162" y="506" text-anchor="middle" fill="#0f172a" font-size="8.2" font-weight="bold">10²–10³ Initial Isomers</text>
  <text x="292" y="506" text-anchor="middle" fill="#334155" font-size="8.2">Top-K Ranked</text>
  <text x="430" y="506" text-anchor="middle" fill="#0f2557" font-size="8.2">Spin Stop → M_gs</text>
  <text x="615" y="506" text-anchor="middle" fill="#0f2557" font-size="8.2" font-weight="bold">Full Properties &amp; Report</text>
  <line x1="115" y1="538" x2="703" y2="538" stroke="#475569" stroke-width="1" marker-end="url(#arr)"/>
  <text x="408" y="553" text-anchor="middle" fill="#334155" font-size="8.6">Configuration Space Compression (N_iso ↓↓)  ·  Hamiltonian &amp; Electronic Fidelity Escalation (↑↑)</text>

  <rect x="724" y="405" width="294" height="86" rx="1.5" fill="#ffffff" stroke="#334155" stroke-width="1"/>
  <rect x="724" y="405" width="294" height="19" rx="1" fill="#0f2557"/>
  <text x="871" y="418" text-anchor="middle" fill="#ffffff" font-size="9.3" font-weight="bold">Registry[T] Six Extensible Plugin Registries</text>
  <text x="732" y="437" fill="#0f172a" font-size="8.2"><tspan font-weight="bold">QCPROGRAMS</tspan> : Gaussian 16 (extensible ORCA / CP2K)</text>
  <text x="732" y="451" fill="#0f172a" font-size="8.2"><tspan font-weight="bold">GENERATORS</tspan> : Import / ABCluster / Molclus / ASE-GA</text>
  <text x="732" y="465" fill="#0f172a" font-size="8.2"><tspan font-weight="bold">RENDERERS</tspan>  : Matplotlib / Origin 2024b / VMD</text>
  <text x="732" y="479" fill="#0f172a" font-size="8.2"><tspan font-weight="bold">RUNNERS·LLM</tspan>: DirectRunner / DeepSeek / Profile</text>

  <rect x="724" y="499" width="294" height="55" rx="1.5" fill="#fff1f2" stroke="#881337" stroke-width="1"/>
  <text x="871" y="514" text-anchor="middle" fill="#881337" font-size="9.0" font-weight="bold">Automated Constitutional Gates (CI / Runtime)</text>
  <text x="732" y="530" fill="#334155" font-size="8.2">• AST 0-Element Check [C2]    • Theory Parity [C4]</text>
  <text x="732" y="544" fill="#334155" font-size="8.2">• Keyring Zero-Echo [C6]      • Plan/Num Guards [C1–C3]</text>
</svg>
"""
    _assert_no_cjk(svg, "fig1_architecture.svg")
    svg_path.write_text(svg, encoding="utf-8")

    html_doc = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/>"
        "<style>@page{size:10.4in 5.72in;margin:0;}body{margin:0;padding:0;background:#fff;}"
        "svg{display:block;width:10.4in;height:5.72in;}</style>"
        f"</head><body>{svg}</body></html>"
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1040, "height": 572}, device_scale_factor=3)
        page.set_content(html_doc, wait_until="load")
        page.pdf(
            path=str(pdf_path),
            width="10.4in",
            height="5.72in",
            margin={"top": "0in", "bottom": "0in", "left": "0in", "right": "0in"},
            print_background=True,
        )
        page.screenshot(path=str(png_path))
        browser.close()

    with Image.open(png_path) as im:
        im.save(png_path, dpi=(300, 300))
    return [svg_path, pdf_path, png_path]


def build_fig2_vmd_gallery() -> list[Path]:
    """Assemble pure-English Fig. 2 (2x3 VMD TachyonInternal 3D gallery) at 600 dpi."""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    specs = [
        ("na6", r"(a) $\mathrm{Na_6}$ (s-block, $\mathit{M}$ = 1)"),
        ("al13_anion", r"(b) $\mathrm{Al_{13}^-}$ (40$\mathrm{e^-}$ superatom, $\mathit{M}$ = 1)"),
        ("fe4", r"(c) $\mathrm{Fe_4}$ (3d high-spin, $\mathit{M}$ = 13)"),
        ("w_au12", r"(d) $\mathrm{W@Au_{12}}$ (18$\mathrm{e^-}$ endohedral, $\mathit{M}$ = 1)"),
        ("cu3ag3", r"(e) $\mathrm{Cu_3Ag_3}$ (bimetallic, $\mathit{M}$ = 1)"),
        ("al12cu", r"(f) $\mathrm{Al_{12}Cu}$ ($\mathit{M}$ = 2, spin $\pm$0.0035 a.u.)"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(7.0, 4.9))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.98, bottom=0.06, wspace=0.05, hspace=0.14)

    for ax, (tag, caption) in zip(axes.flat, specs, strict=True):
        tile_path = VMD_TILES_DIR / f"{tag}.png"
        if not tile_path.exists():
            raise FileNotFoundError(f"Missing VMD tile: {tile_path}")
        with Image.open(tile_path) as raw:
            arr = np.asarray(raw.convert("RGB"))
        ax.imshow(arr)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor("#cbd5e1")
            spine.set_linewidth(0.8)
        ax.set_xlabel(caption, fontsize=8.5, fontweight="bold", color="#0f2557", labelpad=4)

    out_png = FIG_DIR / "fig2_golden_3d_vmd.png"
    out_pdf = FIG_DIR / "fig2_golden_3d_vmd.pdf"
    fig.savefig(out_png, dpi=600, facecolor="white", bbox_inches="tight", pad_inches=0.05)
    fig.savefig(out_pdf, facecolor="white", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return [out_png, out_pdf]


def build_fig3_golden_gaps() -> list[Path]:
    """Generate Fig. 3: Cross-periodic-table HOMO-LUMO gaps of 6 converged golden clusters."""
    specs = [
        ("w_au12", r"$\mathrm{W@Au_{12}}$", False),
        ("al13_anion", r"$\mathrm{Al_{13}^-}$", False),
        ("cu3ag3", r"$\mathrm{Cu_3Ag_3}$", False),
        ("na6", r"$\mathrm{Na_6}$", False),
        ("al12cu", r"$\mathrm{Al_{12}Cu}$", True),
        ("fe4", r"$\mathrm{Fe_4}$", True),
    ]
    labels, gaps, is_open = [], [], []
    for jid, lbl, op_flag in specs:
        res = parse_gaussian_log(GOLDEN_DIR / jid / "job.log", job_id=jid)
        g_ha = homo_lumo_gap_hartree(res.mo_energies_hartree, res.homo_indices)
        labels.append(lbl)
        gaps.append(round((g_ha or 0.0) * HA_TO_EV, 3))
        is_open.append(op_flag)

    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    x = np.arange(len(labels))
    closed_y = [v if not o else np.nan for v, o in zip(gaps, is_open, strict=True)]
    open_y = [v if o else np.nan for v, o in zip(gaps, is_open, strict=True)]

    ax.bar(
        x,
        closed_y,
        width=0.62,
        color="#1e40af",
        edgecolor="#0f172a",
        linewidth=0.8,
        label="Closed-shell ($M = 1$)",
        zorder=3,
    )
    ax.bar(
        x,
        open_y,
        width=0.62,
        color="#b91c1c",
        edgecolor="#0f172a",
        linewidth=0.8,
        label=r"Open-shell ($M \geq 2$)",
        zorder=3,
    )
    for xi, val in zip(x, gaps, strict=True):
        ax.text(
            xi, val + 0.08, f"{val:.3f}", ha="center", va="bottom", fontsize=8.5, color="#0f172a"
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.2)
    ax.set_ylim(0.0, 3.95)
    ax.set_yticks(np.arange(0.0, 4.0, 0.5))
    ax.tick_params(axis="y", labelsize=8.8)
    ax.set_xlabel("Reference Benchmark Cluster", fontsize=9.8, labelpad=5)
    ax.set_ylabel("HOMO–LUMO Gap $E_{\\mathrm{g}}$ (eV)", fontsize=9.8, labelpad=5)
    ax.grid(axis="y", linestyle=":", linewidth=0.6, color="#cbd5e1", zorder=0)
    ax.legend(loc="upper right", frameon=True, edgecolor="#cbd5e1", facecolor="white", fontsize=8.5)
    fig.tight_layout()
    return _save_mpl_fig(fig, "fig3_golden_gaps", dpi=600)


def build_fig4_al12cu_electronic() -> list[Path]:
    """Generate Fig. 4: Spin-polarized MO levels and Multiwfn TDOS/PDOS of Al12Cu."""
    r_al = parse_gaussian_log(GOLDEN_DIR / "al12cu" / "job.log", job_id="Al12Cu")
    pdos = parse_pdos(
        (MWFN_DIR / "out_10_exp.txt").read_text(encoding="utf-8"),
        MWFN_DIR / "DOS_curve.txt",
        ["Al", "Cu", "s", "p", "d"],
    )

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.35))
    fig.subplots_adjust(wspace=0.28)

    centers = [0.34, 0.78]
    for ch_idx, cx in enumerate(centers):
        h_idx = r_al.homo_indices[ch_idx]
        evs = [e * HA_TO_EV for e in r_al.mo_energies_hartree[ch_idx]]
        for idx in range(max(0, h_idx - 8), min(len(evs), h_idx + 8)):
            ev = evs[idx]
            if idx <= h_idx:
                ax1.plot(
                    [cx - 0.14, cx + 0.14],
                    [ev, ev],
                    color="#1e3a8a",
                    linewidth=1.5,
                    solid_capstyle="butt",
                    label="Occupied MO" if (ch_idx == 0 and idx == h_idx) else None,
                )
            else:
                ax1.plot(
                    [cx - 0.14, cx + 0.14],
                    [ev, ev],
                    color="#ea580c",
                    linewidth=1.2,
                    linestyle="--",
                    solid_capstyle="butt",
                    label="Virtual MO" if (ch_idx == 0 and idx == h_idx + 1) else None,
                )

    ax1.set_xlim(0.06, 1.06)
    ax1.set_ylim(-7.8, -1.45)
    ax1.set_xticks(centers)
    ax1.set_xticklabels([r"$\alpha$ channel", r"$\beta$ channel"], fontsize=9.2)
    ax1.tick_params(axis="x", length=0)
    ax1.tick_params(axis="y", labelsize=8.5)
    ax1.set_xlabel("Spin Channel", fontsize=9.5, labelpad=5)
    ax1.set_ylabel("Orbital Energy (eV)", fontsize=9.5, labelpad=4)

    # Non-overlapping frontier energy labels placed inside clean whitespace
    ax1.text(
        0.56,
        -1.78,
        r"Overall $E_{\mathrm{g}}$ = 0.277 eV",
        ha="center",
        va="top",
        fontsize=8.8,
        fontweight="bold",
        color="#0f2557",
    )
    ax1.annotate(
        "LUMO −4.66",
        xy=(0.48, -4.655),
        xytext=(0.34, -4.05),
        ha="center",
        va="bottom",
        fontsize=7.6,
        color="#c2410c",
        arrowprops={"arrowstyle": "->", "lw": 0.65, "color": "#c2410c"},
    )
    ax1.annotate(
        "HOMO −5.05",
        xy=(0.195, -5.046),
        xytext=(0.34, -6.26),
        ha="center",
        va="top",
        fontsize=7.5,
        color="#1e3a8a",
        arrowprops={
            "arrowstyle": "->",
            "lw": 0.65,
            "color": "#1e3a8a",
            "connectionstyle": "arc3,rad=-0.26",
        },
    )
    ax1.annotate(
        "LUMO −4.71",
        xy=(0.925, -4.710),
        xytext=(0.78, -4.05),
        ha="center",
        va="bottom",
        fontsize=7.6,
        color="#c2410c",
        arrowprops={"arrowstyle": "->", "lw": 0.65, "color": "#c2410c"},
    )
    ax1.annotate(
        "HOMO −4.99",
        xy=(0.925, -4.987),
        xytext=(0.78, -6.26),
        ha="center",
        va="top",
        fontsize=7.5,
        color="#1e3a8a",
        arrowprops={
            "arrowstyle": "->",
            "lw": 0.65,
            "color": "#1e3a8a",
            "connectionstyle": "arc3,rad=0.26",
        },
    )
    ax1.legend(
        loc="lower right", frameon=True, edgecolor="#cbd5e1", facecolor="white", fontsize=7.6
    )
    ax1.text(
        -0.17,
        1.04,
        "(a)",
        transform=ax1.transAxes,
        fontsize=10.5,
        fontweight="bold",
        color="#0f2557",
    )

    e_arr = np.asarray(pdos.energies_ev)
    mask = (e_arr >= -15.5) & (e_arr <= 3.8)
    es = e_arr[mask]
    series = [
        ("TDOS", np.asarray(pdos.tdos_alpha)[mask], "#0f172a", 1.5, "-"),
        ("Al", np.asarray(pdos.pdos_series["Al"])[mask], "#2563eb", 1.15, "-"),
        ("Cu", np.asarray(pdos.pdos_series["Cu"])[mask], "#b91c1c", 1.15, "-"),
        ("p", np.asarray(pdos.pdos_series["p"])[mask], "#16a34a", 1.15, "-"),
        ("d", np.asarray(pdos.pdos_series["d"])[mask], "#9333ea", 1.15, "-"),
    ]
    ax2.axhline(0.0, color="#94a3b8", linewidth=0.65, zorder=1)
    for lbl, vals, col, lw, ls in series:
        ax2.plot(es, vals, color=col, linewidth=lw, linestyle=ls, label=lbl, zorder=2)
    ax2.axvline(
        -5.046, color="#475569", linewidth=1.0, linestyle="--", label="HOMO (−5.05 eV)", zorder=3
    )
    ax2.set_xlim(-15.5, 3.8)
    ax2.set_ylim(-0.04, 0.92)
    ax2.tick_params(labelsize=8.5)
    ax2.set_xlabel("Energy (eV)", fontsize=9.5, labelpad=5)
    ax2.set_ylabel("DOS (states/eV)", fontsize=9.5, labelpad=4)
    ax2.legend(
        loc="upper left", frameon=True, edgecolor="#cbd5e1", facecolor="white", fontsize=7.5, ncol=1
    )
    ax2.text(
        -0.17,
        1.04,
        "(b)",
        transform=ax2.transAxes,
        fontsize=10.5,
        fontweight="bold",
        color="#0f2557",
    )

    fig.tight_layout()
    return _save_mpl_fig(fig, "fig4_al12cu_electronic", dpi=600)


def build_fig5_al12cu_spin_orb() -> list[Path]:
    """Generate Fig. 5: Al12Cu atomic Hirshfeld spin population and frontier MO s/p/d share."""
    r_al = parse_gaussian_log(GOLDEN_DIR / "al12cu" / "job.log", job_id="Al12Cu")
    assert r_al.final_geometry is not None
    _ch, spins = parse_charge_spin(
        (MWFN_DIR / "out_7.txt").read_text(encoding="utf-8")
        + "\n"
        + (MWFN_DIR / "out_15_spin.txt").read_text(encoding="utf-8")
    )
    comps = parse_orb_comp((MWFN_DIR / "out_8_frontier.txt").read_text(encoding="utf-8"))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.4))
    fig.subplots_adjust(wspace=0.26)

    sites = [f"{i + 1}{sym}" for i, sym in enumerate(r_al.final_geometry.symbols)]
    sp_vals = spins["hirshfeld"]
    xs = np.arange(len(sites))
    cu_vals = [sp_vals[0]] + [np.nan] * (len(sp_vals) - 1)
    pos_al = [np.nan] + [v if v >= 0 else np.nan for v in sp_vals[1:]]
    neg_al = [np.nan] + [v if v < 0 else np.nan for v in sp_vals[1:]]

    ax1.bar(
        xs,
        cu_vals,
        width=0.68,
        color="#b91c1c",
        edgecolor="#0f172a",
        linewidth=0.7,
        label="Cu dopant",
        zorder=3,
    )
    ax1.bar(
        xs,
        pos_al,
        width=0.68,
        color="#1e40af",
        edgecolor="#0f172a",
        linewidth=0.7,
        label=r"Al ($+$)",
        zorder=3,
    )
    ax1.bar(
        xs,
        neg_al,
        width=0.68,
        color="#0f766e",
        edgecolor="#0f172a",
        linewidth=0.7,
        label=r"Al ($-$)",
        zorder=3,
    )
    ax1.axhline(0.0, color="#0f172a", linewidth=0.9, zorder=2)
    ax1.set_xticks(xs)
    ax1.set_xticklabels(sites, rotation=45, ha="right", fontsize=7.8)
    ax1.set_ylim(-0.35, 0.39)
    ax1.tick_params(axis="y", labelsize=8.5)
    ax1.set_xlabel(r"Atomic Site ($\mathrm{Al_{12}Cu}$)", fontsize=9.5, labelpad=4)
    ax1.set_ylabel(r"Hirshfeld Spin Population ($e$)", fontsize=9.5, labelpad=4)
    ax1.text(
        0.5,
        0.93,
        r"$f_D(\mathrm{Cu}) = 3.91\%$  |  $\sum s_i = +1.000\,e$",
        transform=ax1.transAxes,
        ha="center",
        va="top",
        fontsize=8.0,
        color="#0f2557",
        fontweight="bold",
    )
    ax1.legend(loc="lower left", frameon=True, edgecolor="#cbd5e1", facecolor="white", fontsize=7.6)
    ax1.text(
        -0.18,
        1.04,
        "(a)",
        transform=ax1.transAxes,
        fontsize=10.5,
        fontweight="bold",
        color="#0f2557",
    )

    orb_labels = [f"MO {c.mo_index}\n({'α' if c.spin == 'alpha' else 'β'})" for c in comps]
    s_v = np.asarray([round(c.contributions.get("shell_s", 0.0), 2) for c in comps])
    p_v = np.asarray([round(c.contributions.get("shell_p", 0.0), 2) for c in comps])
    d_v = np.asarray([round(c.contributions.get("shell_d", 0.0), 2) for c in comps])
    x2 = np.arange(len(orb_labels))
    ax2.bar(
        x2,
        s_v,
        width=0.58,
        color="#1d4ed8",
        edgecolor="#0f172a",
        linewidth=0.7,
        label="s",
        zorder=3,
    )
    ax2.bar(
        x2,
        p_v,
        bottom=s_v,
        width=0.58,
        color="#f97316",
        edgecolor="#0f172a",
        linewidth=0.7,
        label="p",
        zorder=3,
    )
    ax2.bar(
        x2,
        d_v,
        bottom=s_v + p_v,
        width=0.58,
        color="#0f766e",
        edgecolor="#0f172a",
        linewidth=0.7,
        label="d",
        zorder=3,
    )
    ax2.set_xticks(x2)
    ax2.set_xticklabels(orb_labels, fontsize=8.4)
    ax2.set_ylim(0, 118)
    ax2.set_yticks(np.arange(0, 101, 20))
    ax2.tick_params(axis="y", labelsize=8.5)
    ax2.set_xlabel("Frontier Molecular Orbital", fontsize=9.5, labelpad=4)
    ax2.set_ylabel("Angular-Momentum Share (%)", fontsize=9.5, labelpad=4)
    ax2.legend(
        loc="upper center",
        ncol=3,
        frameon=True,
        edgecolor="#cbd5e1",
        facecolor="white",
        fontsize=8.2,
    )
    ax2.text(
        -0.17,
        1.04,
        "(b)",
        transform=ax2.transAxes,
        fontsize=10.5,
        fontweight="bold",
        color="#0f2557",
    )

    fig.tight_layout()
    return _save_mpl_fig(fig, "fig5_al12cu_spin_orb", dpi=600)


def build_fig6_ln_au5_rigidity() -> list[Path]:
    """Generate Fig. 6: Ln@Au5 (Gd-Lu) electronic rigidity plateau & 4f spin decoupling."""
    data = json.loads(LN_SUMMARY_PATH.read_text(encoding="utf-8"))
    rows = data["ground_states"]

    elems = [str(r["element"]) for r in rows]
    trivalent = {"Tb", "Dy", "Ho", "Er", "Tm", "Lu"}
    gaps = [float(r["gap_ev"]) for r in rows]
    gap_tri = [v if el in trivalent else np.nan for el, v in zip(elems, gaps, strict=True)]
    gap_anom = [v if el not in trivalent else np.nan for el, v in zip(elems, gaps, strict=True)]
    mu_tot = [float(r["mu_b"]) for r in rows]
    spin_ln = [float(r["spin_ln_effective"]) for r in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.35))
    fig.subplots_adjust(wspace=0.25)

    x = np.arange(len(elems))
    ax1.axhspan(2.524, 2.812, color="#dbeafe", alpha=0.55, zorder=1)
    ax1.bar(
        x,
        gap_tri,
        width=0.64,
        color="#1e40af",
        edgecolor="#0f172a",
        linewidth=0.75,
        label=r"Trivalent $\mathrm{8e^-}$ (2.52–2.81 eV)",
        zorder=3,
    )
    ax1.bar(
        x,
        gap_anom,
        width=0.64,
        color="#b91c1c",
        edgecolor="#0f172a",
        linewidth=0.75,
        label=r"Gd ($\mathrm{4f^7 5d^1}$) / $\mathrm{Yb^{2+}}$ ($\mathrm{7e^-}$)",
        zorder=3,
    )
    for xi, val in zip(x, gaps, strict=True):
        ax1.text(
            xi, val + 0.07, f"{val:.2f}", ha="center", va="bottom", fontsize=7.8, color="#0f172a"
        )

    ax1.set_xticks(x)
    ax1.set_xticklabels(elems, fontsize=8.8)
    ax1.set_ylim(0.0, 3.92)
    ax1.set_yticks(np.arange(0.0, 3.6, 0.5))
    ax1.tick_params(axis="y", labelsize=8.5)
    ax1.set_xlabel(r"Lanthanide Dopant in $\mathrm{Ln@Au_5}$", fontsize=9.5, labelpad=4)
    ax1.set_ylabel(r"HOMO–LUMO Gap $E_{\mathrm{g}}$ (eV)", fontsize=9.5, labelpad=4)
    ax1.legend(
        loc="upper right", frameon=True, edgecolor="#cbd5e1", facecolor="white", fontsize=7.5
    )
    ax1.text(
        -0.17,
        1.04,
        "(a)",
        transform=ax1.transAxes,
        fontsize=10.5,
        fontweight="bold",
        color="#0f2557",
    )

    ax2.plot(
        x,
        mu_tot,
        color="#0f2557",
        linewidth=1.5,
        marker="s",
        markersize=5.5,
        label=r"Total moment ($\mu_{\mathrm{B}}$)",
        zorder=3,
    )
    ax2.plot(
        x,
        spin_ln,
        color="#b91c1c",
        linewidth=1.25,
        marker="o",
        markersize=5.2,
        label=r"Localized spin(Ln) ($e$)",
        zorder=4,
    )
    ax2.annotate(
        r"$\mathrm{Yb^{2+}\ (4f^{14})}$: spin(Yb) = +0.18 $e$",
        xy=(6, 0.179),
        xytext=(1.1, 0.72),
        fontsize=7.8,
        color="#991b1b",
        fontweight="bold",
        arrowprops={"arrowstyle": "->", "lw": 0.9, "color": "#b91c1c"},
    )
    ax2.set_xticks(x)
    ax2.set_xticklabels(elems, fontsize=8.8)
    ax2.set_ylim(-0.55, 8.9)
    ax2.set_yticks(np.arange(0, 9, 1))
    ax2.tick_params(axis="y", labelsize=8.5)
    ax2.set_xlabel(r"Lanthanide Dopant in $\mathrm{Ln@Au_5}$", fontsize=9.5, labelpad=4)
    ax2.set_ylabel(r"Spin / Magnetic Moment ($\mu_{\mathrm{B}}$ or $e$)", fontsize=9.5, labelpad=4)
    ax2.legend(
        loc="upper right", frameon=True, edgecolor="#cbd5e1", facecolor="white", fontsize=7.7
    )
    ax2.text(
        -0.16,
        1.04,
        "(b)",
        transform=ax2.transAxes,
        fontsize=10.5,
        fontweight="bold",
        color="#0f2557",
    )

    fig.tight_layout()
    return _save_mpl_fig(fig, "fig6_ln_au5_rigidity", dpi=600)


def _al12cu_mo_plot_b64() -> str:
    r_al = parse_gaussian_log(GOLDEN_DIR / "al12cu" / "job.log", job_id="Al12Cu")
    fig, ax = plt.subplots(figsize=(4.4, 2.55))
    for ch_idx, cx in enumerate((0.35, 0.75)):
        h_idx = r_al.homo_indices[ch_idx]
        evs = [e * HA_TO_EV for e in r_al.mo_energies_hartree[ch_idx]]
        for idx in range(max(0, h_idx - 6), min(len(evs), h_idx + 6)):
            ev = evs[idx]
            if idx <= h_idx:
                ax.plot([cx - 0.13, cx + 0.13], [ev, ev], color="#1e3a8a", linewidth=1.4)
            else:
                ax.plot(
                    [cx - 0.13, cx + 0.13], [ev, ev], color="#ea580c", linewidth=1.1, linestyle="--"
                )
    ax.set_xlim(0.08, 1.02)
    ax.set_ylim(-6.75, -1.7)
    ax.set_xticks([0.35, 0.75])
    ax.set_xticklabels([r"$\alpha$", r"$\beta$"], fontsize=8.5)
    ax.tick_params(axis="y", labelsize=8.0)
    ax.set_title(
        r"$\mathrm{Al_{12}Cu}$ MO Energy Levels ($M = 2$, $q = 0$, $E_{\mathrm{g}} = 0.277$ eV)",
        fontsize=8.2,
        fontweight="bold",
        color="#0f2557",
    )
    ax.set_ylabel("Energy (eV)", fontsize=8.5)
    ax.text(0.35, -4.18, "LUMO −4.66", ha="center", va="bottom", fontsize=7.0, color="#c2410c")
    ax.annotate(
        "HOMO −5.05",
        xy=(0.215, -5.046),
        xytext=(0.35, -6.12),
        ha="center",
        va="top",
        fontsize=6.8,
        color="#1e3a8a",
        arrowprops={
            "arrowstyle": "->",
            "lw": 0.6,
            "color": "#1e3a8a",
            "connectionstyle": "arc3,rad=-0.26",
        },
    )
    ax.text(0.75, -4.18, "LUMO −4.71", ha="center", va="bottom", fontsize=7.0, color="#c2410c")
    ax.annotate(
        "HOMO −4.99",
        xy=(0.885, -4.987),
        xytext=(0.75, -6.12),
        ha="center",
        va="top",
        fontsize=6.8,
        color="#1e3a8a",
        arrowprops={
            "arrowstyle": "->",
            "lw": 0.6,
            "color": "#1e3a8a",
            "connectionstyle": "arc3,rad=0.26",
        },
    )
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=220, facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_fig7_web_workbench() -> list[Path]:
    """Render pure-English Fig. 7 Web Research Workbench (2-panel HiDPI Chromium capture)."""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    png_path = FIG_DIR / "fig7_web_workbench.png"
    pdf_path = FIG_DIR / "fig7_web_workbench.pdf"

    icon_path = ASSETS_DIR / "qcai_icon.png"
    icon_b64 = (
        base64.b64encode(icon_path.read_bytes()).decode("ascii") if icon_path.exists() else ""
    )
    mo_b64 = _al12cu_mo_plot_b64()

    def _sidebar_html(active_idx: int) -> str:
        nav = [
            "1. New Research",
            "2. Plan Review",
            "3. Job Dashboard",
            "4. Results & Report",
            "5. Single-File Tools",
            "6. Settings",
        ]
        items = "".join(
            f'<div class="nav-item {"nav-active" if idx == active_idx else ""}">{lbl}</div>'
            for idx, lbl in enumerate(nav, start=1)
        )
        logo = f'<img src="data:image/png;base64,{icon_b64}" class="sb-logo"/>' if icon_b64 else ""
        return f"""
        <div class="sidebar">
          <div class="nav-list">{items}</div>
          <div class="brand-row">
            {logo}
            <div><div class="brand-name">QuantumChem AI</div><div class="brand-sub">Cluster Research v0.1.0</div></div>
          </div>
          <div class="status-card">
            <div class="pills"><span class="pill pill-ok">AI Ready</span><span class="pill pill-info">Cluster Ready</span></div>
            <div>Model: <code>deepseek-v4.1-flash</code></div>
            <div>Local projects: <b>1</b></div>
          </div>
        </div>"""

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<style>
  @page {{ size: 14.0in 5.45in; margin: 0; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 14px;
    background: #ffffff;
    font-family: Arial, Helvetica, sans-serif;
    color: #0f172a;
    width: 1400px;
  }}
  .grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 18px;
  }}
  .panel-wrap {{
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .window {{
    display: grid;
    grid-template-columns: 158px 1fr;
    border: 1.5px solid #94a3b8;
    border-radius: 6px;
    overflow: hidden;
    background: #f8fafc;
    height: 468px;
  }}
  .sidebar {{
    background: #f1f5f9;
    border-right: 1px solid #e2e8f0;
    padding: 12px 10px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }}
  .nav-list {{ display: flex; flex-direction: column; gap: 3px; }}
  .nav-item {{
    font-size: 9.5px;
    padding: 5px 7px;
    border-radius: 6px;
    color: #334155;
  }}
  .nav-active {{
    background: #e2e8f0;
    font-weight: 700;
    color: #0f172a;
  }}
  .brand-row {{ display: flex; align-items: center; gap: 7px; margin-top: 4px; }}
  .sb-logo {{ width: 28px; height: 28px; border-radius: 6px; }}
  .brand-name {{ font-size: 10px; font-weight: 700; color: #0f172a; }}
  .brand-sub {{ font-size: 8.2px; color: #64748b; }}
  .status-card {{
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 7px;
    font-size: 8.5px;
    line-height: 1.45;
    color: #334155;
  }}
  .status-card code {{ font-family: Consolas, monospace; font-size: 8px; background: #f1f5f9; padding: 1px 3px; border-radius: 3px; }}
  .pills {{ margin-bottom: 4px; display: flex; gap: 4px; flex-wrap: wrap; }}
  .pill {{ padding: 1.5px 6px; border-radius: 999px; font-size: 7.8px; font-weight: 700; }}
  .pill-ok {{ background: #dcfce7; color: #166534; }}
  .pill-info {{ background: #dbeafe; color: #1e40af; }}
  .main {{ padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }}
  .hero {{
    background: #0f2557;
    color: #ffffff;
    padding: 10px 14px;
    border-radius: 6px;
  }}
  .hero h3 {{ margin: 0 0 3px 0; font-size: 14px; }}
  .hero p {{ margin: 0; font-size: 8.8px; color: #dbeafe; line-height: 1.35; }}
  .stepper {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }}
  .step {{
    padding: 4px 6px;
    border-radius: 7px;
    border: 1px solid #e2e8f0;
    background: #ffffff;
    color: #64748b;
    font-size: 8.5px;
    text-align: center;
  }}
  .step.active {{ border-color: #1e40af; background: #eff6ff; color: #1e3a8a; font-weight: 700; }}
  .step.done {{ border-color: #bbf7d0; background: #f0fdf4; color: #166534; }}
  .tabs {{ display: flex; gap: 16px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; font-size: 9px; }}
  .tab-on {{ color: #dc2626; font-weight: 700; border-bottom: 2px solid #dc2626; padding-bottom: 3px; }}
  .tab-off {{ color: #64748b; }}
  .card {{
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .card-title {{ font-size: 11.5px; font-weight: 700; color: #0f172a; }}
  .card-sub {{ font-size: 8.5px; color: #475569; line-height: 1.4; }}
  .ex-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }}
  .ex-btn {{
    border: 1px solid #cbd5e1;
    background: #f8fafc;
    border-radius: 6px;
    padding: 5px 4px;
    font-size: 8.2px;
    text-align: center;
    color: #1e293b;
  }}
  .prompt-label {{ font-size: 8.8px; font-weight: 700; color: #334155; }}
  .textarea {{
    border: 1px solid #cbd5e1;
    background: #f8fafc;
    border-radius: 7px;
    padding: 8px 10px;
    font-size: 8.8px;
    color: #475569;
    min-height: 52px;
    line-height: 1.4;
  }}
  .btn-row {{ display: grid; grid-template-columns: 185px 1fr; gap: 10px; align-items: center; }}
  .btn-primary {{
    background: #1e40af;
    color: #ffffff;
    border-radius: 7px;
    padding: 7px 10px;
    font-size: 9px;
    font-weight: 700;
    text-align: center;
  }}
  .hint {{ font-size: 8px; color: #64748b; line-height: 1.35; }}
  .select-box {{
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    padding: 5px 9px;
    font-size: 9px;
    color: #0f172a;
    display: flex;
    justify-content: space-between;
  }}
  .kpi-row {{ display: grid; grid-template-columns: 0.9fr 1.25fr 1.1fr 0.95fr 0.75fr; gap: 6px; }}
  .kpi {{
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 6px 8px;
  }}
  .kpi-lbl {{ font-size: 7.8px; color: #64748b; }}
  .kpi-val {{ font-size: 11px; font-weight: 700; color: #0f172a; margin-top: 2px; white-space: nowrap; }}
  .act-bar {{
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 6px 8px;
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 8px;
    align-items: center;
  }}
  .btn-sec {{
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    padding: 5px 8px;
    font-size: 8.6px;
    text-align: center;
    background: #ffffff;
    font-weight: 600;
  }}
  .plot-area {{
    display: grid;
    grid-template-columns: 155px 1fr;
    gap: 10px;
    align-items: start;
  }}
  .plot-img {{ width: 100%; max-height: 145px; object-fit: contain; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; }}
  .fig-cap {{
    font-size: 11.5px;
    font-weight: 700;
    color: #0f2557;
    padding-left: 2px;
  }}
</style>
</head>
<body>
<div class="grid">
  <div class="panel-wrap">
    <div class="window">
      {_sidebar_html(1)}
      <div class="main">
        <div class="hero">
          <h3>1. New Cluster Study</h3>
          <p>Describe a target cluster system in natural language or configure calculation parameters manually via the periodic-table interface.</p>
        </div>
        <div class="stepper">
          <div class="step active">1. New Study</div>
          <div class="step">2. Plan Review</div>
          <div class="step">3. Job Dashboard</div>
          <div class="step">4. Results &amp; Report</div>
        </div>
        <div class="tabs">
          <div class="tab-on">Natural-Language Input</div>
          <div class="tab-off">Periodic-Table &amp; Structure Input</div>
        </div>
        <div class="card">
          <div class="card-title">Natural-Language-to-Plan Translation (LLM + Rule Engine)</div>
          <div class="card-sub">Specify target elements, stoichiometry, charge, and scientific objectives. Broad element families trigger focused clarification prompts alongside candidate ProposedPlan options.</div>
          <div class="ex-grid">
            <div class="ex-btn">Al<sub>6–13</sub>Ni Doping</div>
            <div class="ex-btn">W@Au<sub>12</sub> Superatom</div>
            <div class="ex-btn">Fe<sub>4</sub> Spin Ladder</div>
            <div class="ex-btn">Ln@Au<sub>5</sub> Rigidity</div>
          </div>
          <div class="prompt-label">Specify cluster stoichiometry and calculation goal</div>
          <div class="textarea">Example: Evaluate the stability and magnetism of Al<sub>6–13</sub>Ni clusters at standard accuracy (12 h budget); or: Examine electronic structural rigidity in heavy lanthanide Ln@Au<sub>5</sub> superatoms.</div>
          <div class="btn-row">
            <div class="btn-primary">Generate Calculation Plan</div>
            <div class="hint">The LLM extracts structured intent only; DFT functionals, BSE GenECP blocks, spin multiplicities, and equations remain governed by deterministic rules.</div>
          </div>
        </div>
      </div>
    </div>
    <div class="fig-cap">(a) Study Setup Interface (Natural-Language &amp; Periodic-Table Input)</div>
  </div>

  <div class="panel-wrap">
    <div class="window">
      {_sidebar_html(4)}
      <div class="main">
        <div class="hero">
          <h3>4. Results &amp; Report Export</h3>
          <p>Inspect ground-state observables, 2D MO/PDOS spectra, 3D geometries, Origin/VMD renders, grounded AI summaries, and A4 PDF reports.</p>
        </div>
        <div class="stepper">
          <div class="step done">&#10003; New Study</div>
          <div class="step done">&#10003; Plan Review</div>
          <div class="step done">&#10003; Job Dashboard</div>
          <div class="step active">4. Results &amp; Report</div>
        </div>
        <div class="select-box"><span>Project: <b>Al<sub>12</sub>Cu Cluster Study (al12cu)</b></span><span>&#9662;</span></div>
        <div class="kpi-row">
          <div class="kpi"><div class="kpi-lbl">Ground State (q=0)</div><div class="kpi-val">Al<sub>12</sub>Cu</div></div>
          <div class="kpi"><div class="kpi-lbl">SCF Energy</div><div class="kpi-val">-4546.9815 Ha</div></div>
          <div class="kpi"><div class="kpi-lbl">Spin &amp; Moment</div><div class="kpi-val">M=2 / 1.0 &mu;B</div></div>
          <div class="kpi"><div class="kpi-lbl">HOMO-LUMO Gap</div><div class="kpi-val">0.277 eV</div></div>
          <div class="kpi"><div class="kpi-lbl">Jobs / Alerts</div><div class="kpi-val">1 / 0</div></div>
        </div>
        <div class="act-bar">
          <div class="btn-sec">Export Data (CSV)</div>
          <div class="btn-primary">Generate PDF / HTML Report</div>
          <div class="hint" style="text-align:center;">Playwright A4 PDF / HTML</div>
        </div>
        <div class="tabs">
          <div class="tab-off">Summary Table</div>
          <div class="tab-on">2D Plots &amp; Origin</div>
          <div class="tab-off">3D &amp; VMD</div>
          <div class="tab-off">AI Interpretation</div>
        </div>
        <div class="plot-area">
          <div style="display:flex;flex-direction:column;gap:6px;">
            <div class="select-box"><span>MO Energy Levels (levels)</span><span>&#9662;</span></div>
            <div class="btn-sec">Render via Origin 2024b</div>
          </div>
          <img class="plot-img" src="data:image/png;base64,{mo_b64}" alt="MO Levels"/>
        </div>
      </div>
    </div>
    <div class="fig-cap">(b) Results Interface (Ground-State Observables, 2D/3D Plots &amp; Export)</div>
  </div>
</div>
</body>
</html>"""

    _assert_no_cjk(html_doc, "fig7_web_workbench.html")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 545}, device_scale_factor=2)
        page.set_content(html_doc, wait_until="load")
        page.pdf(
            path=str(pdf_path),
            width="14.0in",
            height="5.45in",
            margin={"top": "0in", "bottom": "0in", "left": "0in", "right": "0in"},
            print_background=True,
        )
        page.screenshot(path=str(png_path))
        browser.close()

    with Image.open(png_path) as im:
        im.save(png_path, dpi=(300, 300))
    return [png_path, pdf_path]


def build_toc_graphic() -> list[Path]:
    """Generate ACS JCIM-compliant TOC graphic (<= 3.25 in x 1.75 in, no outer border)."""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(LN_SUMMARY_PATH.read_text(encoding="utf-8"))
    rows = data["ground_states"]
    elems = [str(r["element"]) for r in rows]
    gaps = [float(r["gap_ev"]) for r in rows]
    trivalent = {"Tb", "Dy", "Ho", "Er", "Tm", "Lu"}
    bar_cols = ["#1e40af" if el in trivalent else "#b91c1c" for el in elems]

    fig = plt.figure(figsize=(3.25, 1.75), dpi=600)
    ax_bg = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax_bg.set_xlim(0.0, 3.25)
    ax_bg.set_ylim(0.0, 1.75)
    ax_bg.axis("off")

    def _box(
        x: float, y: float, w: float, h: float, hdr_col: str, hdr: str, lines: list[str]
    ) -> None:
        patch = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.015,rounding_size=0.03",
            facecolor="#ffffff",
            edgecolor="#334155",
            linewidth=0.75,
        )
        ax_bg.add_patch(patch)
        ax_bg.text(
            x + w / 2,
            y + h - 0.075,
            hdr,
            ha="center",
            va="top",
            fontsize=6.7,
            fontweight="bold",
            color=hdr_col,
        )
        for idx, line in enumerate(lines):
            ax_bg.text(
                x + w / 2,
                y + h - 0.20 - idx * 0.12,
                line,
                ha="center",
                va="top",
                fontsize=5.9,
                color="#1e293b",
            )

    _box(
        0.05,
        1.27,
        1.27,
        0.41,
        "#0f2557",
        "1. Natural Language",
        [r"$\mathrm{Ln@Au_5}$ prompt · 50+50 eval"],
    )
    _box(
        0.05,
        0.67,
        1.27,
        0.46,
        "#9f1239",
        "2. Constitution (C1–C8)",
        ["AST 0-Branch YAML Rules", "Numerical Grounding Guard"],
    )
    _box(
        0.05,
        0.07,
        1.27,
        0.46,
        "#166534",
        "3. S0–S7 HPC Funnel",
        ["230 Jobs · 1,399.78 core·h", "100% Conv. (7 4f Repairs)"],
    )

    arrow_kw = {"arrowstyle": "-|>", "lw": 0.85, "color": "#334155", "mutation_scale": 7.5}
    ax_bg.annotate("", xy=(0.685, 1.15), xytext=(0.685, 1.25), arrowprops=arrow_kw)
    ax_bg.annotate("", xy=(0.685, 0.55), xytext=(0.685, 0.65), arrowprops=arrow_kw)
    ax_bg.plot([1.34, 1.43, 1.43], [0.30, 0.30, 0.88], color="#334155", lw=0.85)
    ax_bg.annotate("", xy=(1.53, 0.88), xytext=(1.425, 0.88), arrowprops=arrow_kw)

    # Embedded right-side Ln@Au5 discovery mini-plot
    ax_in = fig.add_axes([0.535, 0.16, 0.44, 0.67])
    xs = np.arange(len(elems))
    ax_in.axhspan(2.524, 2.812, color="#dbeafe", alpha=0.65, zorder=1)
    ax_in.bar(xs, gaps, width=0.66, color=bar_cols, edgecolor="#0f172a", linewidth=0.45, zorder=3)
    ax_in.set_xticks(xs)
    ax_in.set_xticklabels(elems, fontsize=6.0)
    ax_in.set_ylim(0.0, 3.48)
    ax_in.set_yticks([0, 1, 2, 3])
    ax_in.tick_params(axis="both", top=False, right=False, labelsize=6.0, length=2.2, pad=1.5)
    ax_in.set_ylabel(r"$E_{\mathrm{g}}$ (eV)", fontsize=6.4, labelpad=1.5)
    ax_in.set_title(
        r"4. $\mathrm{Ln@Au_5}$ Electronic Rigidity",
        fontsize=6.8,
        fontweight="bold",
        color="#0f2557",
        pad=3.5,
    )
    ax_in.text(
        3.2,
        3.02,
        r"$\mathrm{8e^-}$ Plateau (2.52–2.81 eV)",
        ha="center",
        va="bottom",
        fontsize=5.8,
        fontweight="bold",
        color="#1e40af",
    )
    ax_in.text(
        0.0,
        1.78,
        r"$\mathrm{Gd}$",
        ha="center",
        va="bottom",
        fontsize=5.8,
        fontweight="bold",
        color="#991b1b",
    )
    ax_in.text(
        6.0,
        1.60,
        r"$\mathrm{Yb^{2+}}$",
        ha="center",
        va="bottom",
        fontsize=5.8,
        fontweight="bold",
        color="#991b1b",
    )
    for sp in ("top", "right"):
        ax_in.spines[sp].set_visible(False)

    paths: list[Path] = []
    for ext in ("png", "pdf", "svg"):
        out = FIG_DIR / f"TOC_graphic.{ext}"
        fig.savefig(out, dpi=600, facecolor="white")
        paths.append(out)
    plt.close(fig)

    with Image.open(FIG_DIR / "TOC_graphic.png") as im:
        im.save(FIG_DIR / "TOC_graphic.png", dpi=(600, 600))
        w_in = im.width / 600.0
        h_in = im.height / 600.0
        if w_in > 3.25 + 1e-4 or h_in > 1.75 + 1e-4:
            raise AssertionError(f"TOC dimensions exceed ACS limit: {w_in:.3f} x {h_in:.3f} in")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build all pure-English JCIM figures.")
    parser.add_argument(
        "--only",
        choices=["all", "fig1", "fig2", "fig3", "fig4", "fig5", "fig6", "fig7", "toc"],
        default="all",
    )
    args = parser.parse_args(argv)
    if args.only in ("all", "fig1"):
        print("FIG1:", build_fig1_architecture())
    if args.only in ("all", "fig2"):
        print("FIG2:", build_fig2_vmd_gallery())
    if args.only in ("all", "fig3"):
        print("FIG3:", build_fig3_golden_gaps())
    if args.only in ("all", "fig4"):
        print("FIG4:", build_fig4_al12cu_electronic())
    if args.only in ("all", "fig5"):
        print("FIG5:", build_fig5_al12cu_spin_orb())
    if args.only in ("all", "fig6"):
        print("FIG6:", build_fig6_ln_au5_rigidity())
    if args.only in ("all", "fig7"):
        print("FIG7:", build_fig7_web_workbench())
    if args.only in ("all", "toc"):
        print("TOC:", build_toc_graphic())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

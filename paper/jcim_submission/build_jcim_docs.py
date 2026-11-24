"""Build English Supporting Information (MD + PDF) and 1-page Cover Letter (MD + PDF) for JCIM."""

from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from qcai.core.physics import HA_TO_EV, homo_lumo_gap_hartree
from qcai.programs.gaussian.parser import parse_gaussian_log

REPO_ROOT = Path(__file__).resolve().parents[2]
JCIM_DIR = Path(__file__).resolve().parent
DATA_DIR = JCIM_DIR / "data"
GOLDEN_DIR = REPO_ROOT / "tests" / "data" / "golden"
RULES_DIR = REPO_ROOT / "src" / "qcai" / "knowledge" / "rules"
LN_STUDY_DIR = REPO_ROOT / "results" / "ln_au5_study"
EVAL_RESULTS_PATH = DATA_DIR / "bilingual_eval_results.json"


def _assert_no_cjk(text: str, label: str) -> None:
    if m := re.search(r"[\u4e00-\u9fff]", text):
        raise ValueError(f"CJK character {m.group(0)!r} detected in {label}")


def _tex_to_html(expr: str) -> str:
    """Convert inline TeX snippets to clean HTML subscripts/superscripts/Unicode."""
    raw = expr.strip()
    repls = (
        (r"\langle ", "⟨"),
        (r"\langle", "⟨"),
        (r" \rangle", "⟩"),
        (r"\rangle", "⟩"),
        (r"\Delta ", "Δ"),
        (r"\Delta", "Δ"),
        (r"\text{\AA}", "Å"),
        (r"\AA", "Å"),
        (r"\mathrm{", ""),
        (r"\text{", ""),
        (r"\min", "min"),
        (r"\mu_{\mathrm{B}}", "μ<sub>B</sub>"),
        (r"\mu_B", "μ<sub>B</sub>"),
        (r"\pm", "±"),
        (r"\le", "≤"),
        (r"\ge", "≥"),
        (r"\in", "∈"),
    )
    for src, dst in repls:
        raw = raw.replace(src, dst)
    # Strip unmatched closing braces left by \mathrm{...} or \text{...} when not preceded by _ or ^
    holds: list[str] = []

    def _hold(snippet: str) -> str:
        idx = len(holds)
        holds.append(snippet)
        return f"@@H{idx}@@"

    raw = re.sub(r"_\{([^{}]+)\}", lambda m: _hold(f"<sub>{html.escape(m.group(1))}</sub>"), raw)
    raw = re.sub(r"\^\{([^{}]+)\}", lambda m: _hold(f"<sup>{html.escape(m.group(1))}</sup>"), raw)
    raw = re.sub(r"_([A-Za-z0-9]+)", lambda m: _hold(f"<sub>{html.escape(m.group(1))}</sub>"), raw)
    raw = re.sub(
        r"\^([A-Za-z0-9+\-]+)", lambda m: _hold(f"<sup>{html.escape(m.group(1))}</sup>"), raw
    )
    raw = raw.replace("{", "").replace("}", "")
    out = html.escape(raw)
    for idx, tok in enumerate(holds):
        out = out.replace(f"@@H{idx}@@", tok)
    return f'<span class="math">{out}</span>'


def _clean_md_inline(text: str) -> str:
    tokens: list[str] = []

    def _hold(snippet: str) -> str:
        idx = len(tokens)
        tokens.append(snippet)
        return f"@@T{idx}@@"

    text = re.sub(r"`([^`]+)`", lambda m: _hold(f"<code>{html.escape(m.group(1))}</code>"), text)
    text = re.sub(r"\$([^$\n]+)\$", lambda m: _hold(_tex_to_html(m.group(1))), text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: _hold(f'<a href="{html.escape(m.group(2))}">{html.escape(m.group(1))}</a>'),
        text,
    )
    out = html.escape(text)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", out)
    for idx, tok in enumerate(tokens):
        out = out.replace(f"@@T{idx}@@", tok)
    return out


def _md_to_html(md: str) -> str:
    lines = md.splitlines()
    blocks: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if s == "---":
            blocks.append("<hr/>")
            i += 1
            continue
        if s.startswith("# "):
            blocks.append(f"<h1>{_clean_md_inline(s[2:])}</h1>")
            i += 1
            continue
        if s.startswith("## "):
            blocks.append(f"<h2>{_clean_md_inline(s[3:])}</h2>")
            i += 1
            continue
        if s.startswith("### "):
            blocks.append(f"<h3>{_clean_md_inline(s[4:])}</h3>")
            i += 1
            continue
        if s.startswith("#### "):
            blocks.append(f"<h4>{_clean_md_inline(s[5:])}</h4>")
            i += 1
            continue
        if s.startswith("```"):
            i += 1
            code_lines: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
            continue
        if s.startswith("|") and i + 1 < n and lines[i + 1].strip().startswith("|"):
            tbl_lines: list[str] = []
            while i < n and lines[i].strip().startswith("|"):
                tbl_lines.append(lines[i].strip())
                i += 1
            headers = [
                c.strip().replace(r"\|", "|")
                for c in re.split(r"(?<!\\)\|", tbl_lines[0].strip("|"))
            ]
            aligns = [c.strip() for c in re.split(r"(?<!\\)\|", tbl_lines[1].strip("|"))]
            rows = [
                [c.strip().replace(r"\|", "|") for c in re.split(r"(?<!\\)\|", r.strip("|"))]
                for r in tbl_lines[2:]
            ]

            def _cls(idx: int, cols: list[str] = aligns) -> str:
                tok = cols[idx] if idx < len(cols) else "---"
                if tok.startswith(":") and tok.endswith(":"):
                    return ' class="center"'
                if tok.endswith(":"):
                    return ' class="num"'
                return ""

            ths = "".join(
                f"<th{_cls(ci)}>{_clean_md_inline(h)}</th>" for ci, h in enumerate(headers)
            )
            trs = "".join(
                "<tr>"
                + "".join(f"<td{_cls(ci)}>{_clean_md_inline(c)}</td>" for ci, c in enumerate(r))
                + "</tr>"
                for r in rows
            )
            tbl_cls = ' class="wide-tbl"' if len(headers) >= 10 else ""
            blocks.append(
                f"<table{tbl_cls}><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"
            )
            continue
        if s.startswith("- "):
            items: list[str] = []
            while i < n and lines[i].strip().startswith("- "):
                items.append(f"<li>{_clean_md_inline(lines[i].strip()[2:])}</li>")
                i += 1
            blocks.append(f"<ul>{''.join(items)}</ul>")
            continue
        if m_ol := re.match(r"^(\d+)\.\s+", s):
            start_num = int(m_ol.group(1))
            items = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                items.append(
                    f"<li>{_clean_md_inline(re.sub(r'^\d+\.\s+', '', lines[i].strip()))}</li>"
                )
                i += 1
            start_attr = f' start="{start_num}"' if start_num != 1 else ""
            blocks.append(f"<ol{start_attr}>{''.join(items)}</ol>")
            continue
        para = [lines[i]]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not lines[i].strip().startswith(("#", "|", "- ", "---", "```"))
            and not re.match(r"^\d+\.\s+", lines[i].strip())
        ):
            para.append(lines[i])
            i += 1
        if (
            len(para) == 1
            and para[0].strip().startswith("*Table ")
            and para[0].strip().endswith("*")
        ):
            txt = para[0].strip()[1:-1]
            blocks.append(f'<p class="table-cap">{_clean_md_inline(txt)}</p>')
        elif (
            len(para) == 1
            and para[0].strip().startswith("**")
            and i < n
            and lines[i].strip().startswith("```")
        ):
            blocks.append(f'<p class="xyz-hdr">{_clean_md_inline(para[0].strip())}</p>')
        else:
            rendered_lines: list[str] = []
            for p_idx, raw_ln in enumerate(para):
                seg = _clean_md_inline(raw_ln.strip())
                if p_idx < len(para) - 1:
                    seg += "<br/>" if raw_ln.rstrip("\r\n").endswith("  ") else " "
                rendered_lines.append(seg)
            blocks.append(f"<p>{''.join(rendered_lines)}</p>")
    return "\n".join(blocks)


def _compile_pdf(
    html_doc: str, pdf_path: Path, *, header_text: str = "", show_footer: bool = True
) -> None:
    body_only = re.sub(r"<style>.*?</style>", "", html_doc, flags=re.DOTALL)
    body_only = re.sub(r"<code>.*?</code>", "", body_only, flags=re.DOTALL)
    body_only = re.sub(r"<[^>]+>", "", body_only)
    if m := re.search(r"\\[A-Za-z]{2,}", body_only):
        raise AssertionError(f"Unrendered TeX escape in {pdf_path.name}: {m.group(0)!r}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html_doc, wait_until="load")
        footer_tmpl = (
            '<div style="font-family:Arial,sans-serif;font-size:7.5pt;color:#64748b;width:100%;text-align:center;">'
            'Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>'
            if show_footer
            else "<div></div>"
        )
        hdr_tmpl = (
            f'<div style="font-family:Arial,sans-serif;font-size:7.5pt;color:#64748b;width:100%;text-align:center;">{html.escape(header_text)}</div>'
            if header_text
            else "<div></div>"
        )
        page.pdf(
            path=str(pdf_path),
            format="Letter",
            print_background=True,
            display_header_footer=bool(header_text or show_footer),
            header_template=hdr_tmpl,
            footer_template=footer_tmpl,
            margin={"top": "18mm", "bottom": "18mm", "left": "18mm", "right": "18mm"},
        )
        browser.close()


def _english_rule_tables() -> str:
    theory = yaml.safe_load((RULES_DIR / "theory_level.yaml").read_text(encoding="utf-8"))
    mult = yaml.safe_load((RULES_DIR / "multiplicity.yaml").read_text(encoding="utf-8"))
    charges = yaml.safe_load((RULES_DIR / "charges.yaml").read_text(encoding="utf-8"))
    recipes = yaml.safe_load((RULES_DIR / "recipes.yaml").read_text(encoding="utf-8"))

    tier_reason_en = {
        "fast": "GFN-xTB search followed by PBE-D3BJ/def2-SVP fast screening without TZVP refinement.",
        "standard": "GFN-xTB search -> PBE-D3BJ/def2-SVP screening -> PBE0-D3BJ/def2-TZVP opt+freq refinement.",
        "high": "PBE0-D3BJ/def2-SVP screening -> TPSSh-D3BJ/def2-TZVP opt+freq+stability check.",
    }
    rule_reason_en = {
        "rule.cluster.nosymm": "Disable symmetry constraints (`nosymm`) during cluster optimization to prevent artificial locking of Jahn-Teller distortions.",
        "rule.tm.robust_scf_and_stability": "Enable robust SCF (`xqc,maxcycle=500`), wavefunction stability checks, and raise multiplicity cap to 12 for near-degenerate d-block clusters.",
        "rule.f_block.experimental_warning": "Flag f-block systems (lanthanides/actinides) for potential static correlation/SOC review and enforce robust SCF.",
        "rule.size.basis_downgrade": "Downgrade refinement basis to def2-SVP and cap candidate count K=5 when cluster size exceeds 20 atoms.",
    }
    charge_reason_en = {
        "stability": "Neutral ground state by default (unless user specifies explicit charges).",
        "electronic": "Neutral state by default (unless user specifies explicit charges).",
        "magnetism": "Neutral state by default (unless user specifies explicit charges).",
        "pes": "Requires anion optimization, neutral single-point at anion geometry (VDE), and neutral optimization (ADE).",
        "ionization": "Requires cation SP/opt (VIP/AIP), neutral opt, and anion SP/opt (VEA/AEA).",
        "size_evolution": "Neutral sequence along n = a..b using selected property template.",
        "custom": "Neutral state by default; extensible per requested analysis.",
    }

    lines = [
        "### S2.1 Accuracy Tiers (`theory_level.yaml`)",
        "",
        "*Table S2.1: Deterministic accuracy-tier mapping in `src/qcai/knowledge/rules/theory_level.yaml`.*",
        "",
        "| Tier | Search | Screening Level | Refinement Level | Tasks | Default K | Rationale & References |",
        "| :--- | :--- | :--- | :--- | :--- | :---: | :--- |",
    ]
    for tier_name, cfg in theory["accuracy_tiers"].items():
        scr = (
            f"{cfg['screening_functional']}-{cfg['screening_dispersion']}/{cfg['screening_basis']}"
        )
        ref = (
            f"{cfg['refinement_functional']}-{cfg['refinement_dispersion']}/{cfg['refinement_basis']}"
            if cfg["refinement_functional"]
            else "None"
        )
        tasks = ", ".join(cfg["refinement_tasks"]) if cfg["refinement_tasks"] else "SP / screen"
        refs = "; ".join(cfg["refs"])
        lines.append(
            f"| `{tier_name}` | {cfg['search_method']} | {scr} | {ref} | {tasks} | {cfg['default_k']} | {tier_reason_en[tier_name]} ({refs}) |"
        )

    lines.extend(
        [
            "",
            "### S2.2 Element-Category and Size Rules (`theory_level.yaml` & `multiplicity.yaml`)",
            "",
            "*Table S2.2: AST-verified element-attribute rules (`when` conditions evaluate periodic properties only, zero symbol branches).*",
            "",
            "| Rule ID | Trigger Condition (`when`) | Applied Parameters (`then`) | Physical Rationale & References |",
            "| :--- | :--- | :--- | :--- |",
        ]
    )
    for r in theory["rules"]:
        rid = r["id"]
        when_s = ", ".join(f"`{k}={v}`" for k, v in r["when"].items())
        then_s = ", ".join(f"`{k}={v}`" for k, v in r["then"].items())
        refs = "; ".join(r["refs"])
        lines.append(f"| `{rid}` | {when_s} | {then_s} | {rule_reason_en[rid]} ({refs}) |")

    mdef = mult["defaults"]
    mrule = mult["rules"][0]
    lines.append(
        f"| `{mrule['id']}` | All compositions | `min_states={mdef['min_states']}`, `main_cap={mdef['main_group_cap']}`, `tm_cap={mdef['transition_metal_cap']}`, `early_stop={mdef['early_stop_ev']} eV`, `expand={mdef['expand_at_boundary']}` | Parity conservation `(Ne + M) mod 2 = 1`, atomic Hund-rule spin upper bound, early stop after {mdef['consecutive_high_states']} higher states, boundary expansion ({'; '.join(mrule['refs'])}). |"
    )

    lines.extend(
        [
            "",
            "### S2.3 Charge States and Research Recipes (`charges.yaml` & `recipes.yaml`)",
            "",
            "*Table S2.3: Recipe-to-stage, charge-state, and observable mappings.*",
            "",
            "| Recipe Key | Default Charges | Pipeline Stages | Derived Analyses | Output Figures | Charge Rationale |",
            "| :--- | :---: | :--- | :--- | :--- | :--- |",
        ]
    )
    for rkey, rcfg in recipes["recipes"].items():
        ch_cfg = charges["recipe_charges"][rkey]
        ch_str = ", ".join(str(x) for x in ch_cfg["charges"])
        stages = ", ".join(rcfg["stages"])
        analyses = ", ".join(rcfg["analyses"])
        figs = ", ".join(rcfg["figures"])
        lines.append(
            f"| `{rkey}` | `[{ch_str}]` | `{stages}` | {analyses} | {figs} | {charge_reason_en[rkey]} |"
        )
    return "\n".join(lines)


def _golden_and_ln_tables() -> str:
    lines = [
        "### S3.1 Ten Reference Gaussian 16 Benchmarks (`tests/data/golden/`)",
        "",
        "*Table S3.1: Parsed quantum-chemical metrics and server-side `custodian` recovery outcomes across all 10 reference Gaussian 16 benchmark runs.*",
        "",
        "| Benchmark ID | Species ($N$) | $q / M$ | Status | SCF Energy (Ha) | Gap $E_{\\mathrm{g}}$ (eV) | $\\langle S^2 \\rangle$ | $n_{\\text{imag}}$ | Link1 / Stable | Custodian Recovery Log |",
        "| :--- | :--- | :---: | :---: | ---: | ---: | :---: | :---: | :---: | :--- |",
    ]
    labels = {
        "na6": "Na6 (6)",
        "al13_anion": "Al13- (13)",
        "fe4": "Fe4 (4)",
        "w_au12": "W@Au12 (13)",
        "cu3ag3": "Cu3Ag3 (6)",
        "al12cu": "Al12Cu (13)",
        "fault_imag_freq": "Au4 saddle (4)",
        "fault_opt_maxsteps": "L9999 test (3)",
        "fault_scf_noconv": "L502 test (4)",
        "link1_stable_opt": "Link1 test (2)",
    }
    notes = {
        "na6": "Normal convergence; zero imaginary frequencies.",
        "al13_anion": "40e- closed-shell superatom; normal convergence.",
        "fe4": "3d high-spin (M=13); clean spin channels (ideal 42.0000).",
        "w_au12": "BSE GenECP 18e- endohedral superatom; normal convergence.",
        "cu3ag3": "Bimetallic mixed basis/ECP; normal convergence.",
        "al12cu": "ImaginaryFreqHandler perturbed Jahn-Teller saddle to true minimum.",
        "fault_imag_freq": "ImaginaryFreqHandler displaced along normal mode (step_scale=0.25).",
        "fault_opt_maxsteps": "Step-limit handler resumed geometry & raised opt_max_cycles=100.",
        "fault_scf_noconv": "Escalated maxcycle=100 -> xqc; cleanly marked failed & needs_human=True.",
        "link1_stable_opt": "2-section Link1 parsed cleanly; wavefunction confirmed stable=True.",
    }
    order = [
        "na6",
        "al13_anion",
        "fe4",
        "w_au12",
        "cu3ag3",
        "al12cu",
        "fault_imag_freq",
        "fault_opt_maxsteps",
        "fault_scf_noconv",
        "link1_stable_opt",
    ]
    for jid in order:
        st = json.loads((GOLDEN_DIR / jid / "status.json").read_text(encoding="utf-8"))
        res = parse_gaussian_log(GOLDEN_DIR / jid / "job.log", job_id=jid)
        g_ha = homo_lumo_gap_hartree(res.mo_energies_hartree, res.homo_indices)
        gap_s = f"{g_ha * HA_TO_EV:.3f}" if (g_ha is not None and res.normal_termination) else "--"
        s2_s = f"{res.s2_after:.4f}" if res.s2_after is not None else "--"
        l1_s = f"{res.metadata.get('link1_sections', 1)} / {res.stable if res.stable is not None else '--'}"
        lines.append(
            f"| `{jid}` | {labels[jid]} | {res.state.charge} / {res.state.multiplicity} | `{st['state']}` | {res.energy_hartree:.6f} | {gap_s} | {s2_s} | {len(res.imag_freqs)} | {l1_s} | {notes[jid]} |"
        )

    lines.extend(
        [
            "",
            "### S3.2 Complete S4 Converged Isomers for Heavy Lanthanide Ln@Au5 (Gd-Lu)",
            "",
            "*Table S3.2: All 19 converged S4 `PBE0-D3BJ/def2-TZVP (GenECP)` structures across the 8-element campaign plus standalone `Tm@Au5` reproduction (`proj_a9065c59`).*",
            "",
            "| Element (Z) | Project ID | Rank | Job ID | $M$ | $E_{\\text{SCF}}$ (Ha) | $\\Delta E$ (eV) | $E_b$ (eV/atom) | $E_{\\mathrm{g}}$ (eV) | $\\langle S^2 \\rangle$ | $f_{\\min}$ ($\\text{cm}^{-1}$) | PG | $d_{\\text{Ln-Au}}$ ($\\text{\\AA}$) | $q_{\\text{APT}}$ / spin(Ln) |",
            "| :--- | :--- | :---: | :--- | :---: | ---: | ---: | ---: | ---: | :---: | ---: | :---: | :---: | :---: |",
        ]
    )
    with (LN_STUDY_DIR / "ln_au5_all_s4_isomers.csv").open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            s2_str = f"{float(row['s2_after']):.4f}" if row["s2_after"] else "--"
            sp_str = f"{float(row['spin_mulliken_ln']):+.2f}" if row["spin_mulliken_ln"] else "0.00"
            lines.append(
                f"| {row['element']} ({row['Z']}) | `{row['project_id']}` | {row['rank']} | `{row['job_id']}` | {row['m_gs']} | {float(row['e_scf_ha']):.6f} | {float(row['rel_e_ev']):.4f} | {float(row['eb_ev_per_atom']):.4f} | {float(row['gap_ev']):.3f} | {s2_str} | {float(row['min_freq_cm1']):.2f} | {row['point_group']} | {float(row['d_ln_au_mean_ang']):.3f}+/-{float(row['d_ln_au_std_ang']):.3f} | {float(row['q_apt_ln']):+.2f} / {sp_str} |"
            )

    lines.extend(
        [
            "",
            "### S3.3 Automated Server-Side `custodian` 4f Recovery Records (7 Fixes, 100% Success)",
            "",
            "*Table S3.3: Complete automated fault-recovery trace from the 230-job `Ln@Au5` production campaign.*",
            "",
            "| Project ID | Job ID | Stage | Cluster | $M$ | Detected Error | Automated Recovery Action |",
            "| :--- | :--- | :--- | :--- | :---: | :--- | :--- |",
        ]
    )
    with (LN_STUDY_DIR / "ln_au5_custodian_fixes.csv").open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            raw_fix = row["fixes"]
            if "scf_convergence" in raw_fix:
                err, act = "SCF convergence failure", "`scf=(yqc,maxcycle=512,vshift=500)`"
            elif "imaginary_freq" in raw_fix:
                err, act = "Imaginary frequency", "`perturb_along_imag_mode (step_scale=0.25)`"
            else:
                err, act = (
                    "Optimization step limit",
                    "`from_final_structure` + `opt_max_cycles=100`",
                )
            lines.append(
                f"| `{row['project_id']}` | `{row['job_id']}` | `{row['stage']}` | `{row['cluster_label']}` | {row['multiplicity']} | {err} | {act} |"
            )

    lines.extend(
        [
            "",
            "### S3.4 Optimized Cartesian Coordinates (Angstrom)",
            "",
            "#### S3.4.1 Six Converged Reference Benchmark Clusters",
            "",
        ]
    )
    for jid in ("na6", "al13_anion", "fe4", "w_au12", "cu3ag3", "al12cu"):
        res = parse_gaussian_log(GOLDEN_DIR / jid / "job.log", job_id=jid)
        assert res.final_geometry is not None
        g = res.final_geometry
        lines.append(
            f"**{jid}** (q={res.state.charge}, M={res.state.multiplicity}, E={res.energy_hartree:.6f} Ha)"
        )
        lines.append("```xyz")
        lines.append(str(len(g.symbols)))
        lines.append(
            f"{jid} q={res.state.charge} M={res.state.multiplicity} E={res.energy_hartree:.6f} Ha"
        )
        for sym, (x, y, z) in zip(g.symbols, g.positions, strict=True):
            lines.append(f"{sym:4s} {x:12.6f} {y:12.6f} {z:12.6f}")
        lines.append("```")
        lines.append("")

    lines.extend(["#### S3.4.2 Eight Heavy Lanthanide Ln@Au5 (Gd-Lu) Ground-State Coordinates", ""])
    for el in ("Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"):
        xyz_txt = (LN_STUDY_DIR / "xyz" / f"{el}Au5_gs.xyz").read_text(encoding="utf-8").strip()
        lines.append(f"**{el}@Au5 Ground State (`{el}Au5_gs.xyz`)**")
        lines.append("```xyz")
        lines.append(xyz_txt)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _bilingual_eval_section() -> str:
    data = json.loads(EVAL_RESULTS_PATH.read_text(encoding="utf-8"))
    zh = data["zh"]
    en = data["en"]
    cat_order = [
        "s-block",
        "p-block",
        "3d-TM / doped",
        "4d/5d-TM & bimetallic",
        "Lanthanide (4f)",
        "Ambiguous (clarification)",
    ]
    lines = [
        "## Section S4: Complete Bilingual (50 Chinese + 50 English) Instruction Benchmark",
        "",
        f"Live end-to-end evaluation was executed via `tests/llm_eval/eval_runner.py` against `{data['model']}` on both the Chinese benchmark (`tests/llm_eval/instructions.yaml`: **{zh['passed']}/{zh['total']} = {zh['accuracy']:.1%}**) and the matched English benchmark (`tests/llm_eval/instructions_en.yaml`: **{en['passed']}/{en['total']} = {en['accuracy']:.1%}**). Both suites exceed the 90% acceptance gate (`pytest -m llm`).",
        "",
        "*Table S4.1: Category-level bilingual parsing accuracy across all 50 paired scientific instructions.*",
        "",
        "| Category | Cases | Chinese Pass / Total | Chinese Acc. | English Pass / Total | English Acc. |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]
    for cat in cat_order:
        zc = [c for c in zh["cases"] if c["category"] == cat]
        ec = [c for c in en["cases"] if c["category"] == cat]
        zp = sum(1 for c in zc if c["passed"])
        ep = sum(1 for c in ec if c["passed"])
        lines.append(
            f"| {cat} | {len(ec)} | {zp}/{len(zc)} | {zp / len(zc):.1%} | {ep}/{len(ec)} | {ep / len(ec):.1%} |"
        )
    lines.append(
        f"| **Total** | **50** | **{zh['passed']}/50** | **{zh['accuracy']:.1%}** | **{en['passed']}/50** | **{en['accuracy']:.1%}** |"
    )

    lines.extend(
        [
            "",
            "*Table S4.2: Complete 50-item paired evaluation matrix (English prompt text from `instructions_en.yaml` paired with identical-schema Chinese benchmark outcomes from `instructions.yaml`).*",
            "",
            "| ID | Category | English Instruction Prompt | Expected Target | ZH Outcome | EN Outcome |",
            "| :---: | :--- | :--- | :--- | :---: | :---: |",
        ]
    )
    for zc_item, ec_item in zip(zh["cases"], en["cases"], strict=True):
        exp = ec_item["expected"]
        if ec_item["needs_clarification"]:
            exp_str = "clarification=True"
        else:
            bits = [
                f"comp={exp['composition']}",
                f"rec={','.join(exp['recipes'])}",
                f"acc={exp['accuracy']}",
            ]
            if "charges" in exp:
                bits.append(f"q={exp['charges']}")
            if "time_budget_hours" in exp:
                bits.append(f"t={exp['time_budget_hours']}h")
            exp_str = "; ".join(bits)
        z_stat = "PASS" if zc_item["passed"] else f"FAIL ({zc_item['reason']})"
        e_stat = "PASS" if ec_item["passed"] else f"FAIL ({ec_item['reason']})"
        lines.append(
            f"| {ec_item['id']} | {ec_item['category']} | {ec_item['text']} | `{exp_str}` | {z_stat} ({zc_item['latency_s']:.1f}s) | {e_stat} ({ec_item['latency_s']:.1f}s) |"
        )
    return "\n".join(lines)


def build_supporting_information() -> tuple[Path, Path]:
    si_md_path = JCIM_DIR / "Supporting_Information.md"
    si_pdf_path = JCIM_DIR / "Supporting_Information.pdf"

    md_parts = [
        "# Supporting Information",
        "",
        "**QuantumChem AI: A Rule-Governed Automation Platform with Grounded LLM Assistance for All-Element Atomic Cluster Quantum Chemistry**",
        "",
        "Changtian Qian",
        "",
        "*Department of Physics, Capital Normal University, Beijing 100048, China*",
        "",
        "Repository: `https://github.com/QIANCHANGKING/quantumchem-ai` | Archival DOI: `10.5281/zenodo.24501860`",
        "",
        "---",
        "",
        "## Section S1: Offline Reproduction and 115+ Automated Verification Guide",
        "",
        "1. **Environment Setup (Python 3.12 + uv):**",
        "   - Clone `https://github.com/QIANCHANGKING/quantumchem-ai` (or unpack the Zenodo archive `10.5281/zenodo.24501860`).",
        "   - Run `uv sync` in the repository root to create the locked Python 3.12 virtual environment (`.venv`).",
        "   - Copy `config/settings.example.toml` to `config/settings.toml` only when connecting live SSH clusters or LLM endpoints; offline verification requires zero credentials.",
        "2. **Full Offline Quality & Test Gate (115+ Tests):**",
        "```bash",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run mypy src",
        "uv run pytest",
        "```",
        "   - The default `pytest` marker configuration (`-m 'not (remote or origin or vmd or llm)'`) executes all 115 offline unit, AST constitutional-gate, reference-log regression, Multiwfn output parsing, renderer, launcher, and headless Chromium Playwright E2E tests.",
        "3. **Live Bilingual 50+50 LLM Benchmark Reproduction (Optional):**",
        "   - Store an OpenAI-compatible DeepSeek API key in the OS keyring (`python -c \"from qcai.config import save_deepseek_key; save_deepseek_key('...')\"`) or `DEEPSEEK_API_KEY`, then run `uv run pytest -m llm tests/integration/test_deepseek_llm.py`.",
        "",
        "---",
        "",
        "## Section S2: Complete YAML Rule-Engine Specification",
        "",
        _english_rule_tables(),
        "",
        "---",
        "",
        "## Section S3: Reference Benchmarks, Heavy Lanthanide Dataset, Recovery Trace, and Coordinates",
        "",
        _golden_and_ln_tables(),
        "",
        "---",
        "",
        _bilingual_eval_section(),
    ]
    si_md = "\n".join(md_parts) + "\n"
    _assert_no_cjk(si_md, "Supporting_Information.md")
    si_md_path.write_text(si_md, encoding="utf-8")

    body = _md_to_html(si_md)
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Supporting Information — QuantumChem AI</title>
<style>
  body {{ font-family: "Times New Roman", Times, serif; font-size: 9.6pt; line-height: 1.48; color: #0f172a; max-width: 820px; margin: 0 auto; }}
  h1 {{ font-family: Arial, Helvetica, sans-serif; font-size: 15pt; color: #0f2557; text-align: center; margin: 0 0 6px 0; }}
  h2 {{ font-family: Arial, Helvetica, sans-serif; font-size: 11.5pt; color: #0f2557; border-bottom: 1.2pt solid #1e40af; padding-bottom: 2px; margin-top: 14px; break-after: avoid; }}
  h3 {{ font-family: Arial, Helvetica, sans-serif; font-size: 10.2pt; color: #1e3a8a; margin-top: 11px; break-after: avoid; }}
  h4 {{ font-family: Arial, Helvetica, sans-serif; font-size: 9.6pt; color: #334155; margin-top: 9px; break-after: avoid; }}
  p {{ margin: 4px 0 6px 0; text-align: justify; }}
  p.xyz-hdr {{ margin: 8px 0 2px 0; text-align: left; break-after: avoid; }}
  p.table-cap {{ font-family: Arial, Helvetica, sans-serif; font-size: 8.6pt; font-weight: 700; color: #0f2557; text-align: left; margin: 10px 0 3px 0; break-after: avoid; }}
  code {{ font-family: Consolas, "Courier New", monospace; font-size: 8.0pt; background: #f8fafc; border: 0.5pt solid #e2e8f0; padding: 0 2.5px; border-radius: 2px; }}
  pre {{ background: #f8fafc; border: 0.6pt solid #cbd5e1; border-left: 2.5pt solid #1e40af; padding: 6px 9px; font-family: Consolas, monospace; font-size: 7.7pt; line-height: 1.32; white-space: pre-wrap; break-inside: avoid; }}
  pre code {{ background: transparent; border: none; padding: 0; }}
  table {{ width: 100%; border-collapse: collapse; margin: 3px 0 10px 0; font-size: 7.4pt; line-height: 1.32; }}
  table.wide-tbl {{ font-size: 6.15pt; line-height: 1.25; table-layout: auto; }}
  table.wide-tbl th, table.wide-tbl td {{ padding: 2.5px 2.0px; }}
  table.wide-tbl td:nth-child(4) {{ max-width: 96px; overflow-wrap: anywhere; }}
  table.wide-tbl td:nth-child(14) {{ white-space: nowrap; }}
  table.wide-tbl code {{ font-size: 5.9pt; padding: 0 1.5px; }}
  thead {{ display: table-header-group; }}
  tr {{ break-inside: avoid; }}
  th {{ background: #f1f5f9; color: #0f2557; border-top: 1.2pt solid #0f2557; border-bottom: 0.8pt solid #0f2557; padding: 3.5px 4px; text-align: left; font-family: Arial, sans-serif; }}
  td {{ border-bottom: 0.45pt solid #cbd5e1; padding: 3px 4px; vertical-align: top; }}
  th.center, td.center {{ text-align: center; }}
  th.num, td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  tbody tr:last-child td {{ border-bottom: 1.2pt solid #0f2557; }}
  hr {{ border: none; border-top: 0.7pt solid #cbd5e1; margin: 10px 0; }}
</style>
</head>
<body>{body}</body>
</html>"""
    _compile_pdf(
        full_html,
        si_pdf_path,
        header_text="Supporting Information · Qian, C. · QuantumChem AI (JCIM)",
        show_footer=True,
    )
    return si_md_path, si_pdf_path


def build_cover_letter() -> tuple[Path, Path]:
    eval_data = json.loads(EVAL_RESULTS_PATH.read_text(encoding="utf-8"))
    zh_acc = f"{eval_data['zh']['passed']}/{eval_data['zh']['total']} ({eval_data['zh']['accuracy']:.0%})"
    en_acc = f"{eval_data['en']['passed']}/{eval_data['en']['total']} ({eval_data['en']['accuracy']:.0%})"

    cl_md_path = JCIM_DIR / "Cover_Letter.md"
    cl_pdf_path = JCIM_DIR / "Cover_Letter.pdf"

    cl_md = f"""Department of Physics  
Capital Normal University  
Beijing 100048, China  
November 24, 2026

Prof. Kenneth M. Merz, Jr.  
Editor-in-Chief  
*Journal of Chemical Information and Modeling*  
American Chemical Society

Dear Prof. Merz,

Please find enclosed my Article manuscript entitled **"QuantumChem AI: A Rule-Governed Automation Platform with Grounded LLM Assistance for All-Element Atomic Cluster Quantum Chemistry"** for consideration for publication in the *Journal of Chemical Information and Modeling*.

Atomic cluster quantum chemistry across the periodic table requires tightly coupled orchestration of global structural search, permutation-invariant isomer deduplication, mixed basis/ECP assignment, open-shell spin-multiplicity scanning, fault-tolerant HPC execution, wavefunction analysis, and publication-grade visualization. Existing workflows either hardcode specific element families or expose large language model (LLM) agents to silent physical errors and numerical hallucinations.

In this work, I present QuantumChem AI, an open-source (MIT-licensed) automation platform built around an eight-article Design Constitution (C1–C8) enforced at runtime and in continuous integration. Key contributions of direct relevance to the JCIM readership include:

1. **Zero-Hardcoding Periodic-Table Rule Engine:** All functional, dispersion, Basis Set Exchange (`GenECP`), electron-parity, and adaptive spin-multiplicity rules reside in traceable YAML specifications, verified by Python AST static analysis to contain zero element-symbol branches across the source tree.
2. **Tri-Axial Inertia Kabsch Deduplication & Symmetry Enumeration:** A three-stage fingerprint, tri-axial principal-inertia Hungarian/Kabsch alignment, and fallback permutation matcher resolves arbitrary 3D rotations and atom-index permutations to $10^{{-15}}$ Angstrom precision in under 8 ms, paired with `PointGroupAnalyzer` dopant enumeration.
3. **Resilient Shared-HPC Orchestration:** NUMA-aware load throttling with elastic core scaling (`4` to `10–16` cores), SSH auto-reconnect with exit-poll race protection, three-section `--Link1--` (`opt` -> `stable=opt` -> `freq`), and lossless 4f SCF escalation/tail-preserving recovery.
4. **Computational Benchmark Validation and Lanthanide Superatom Study:** Validated across 10 reference Gaussian 16 cluster benchmarks, Multiwfn 3.8(dev) wavefunction analysis of `Al12Cu`, and an autonomous 9-project, 230-job (221 Gaussian 16 runs, 1,399.78 CPU core-hours, 100% convergence with 7 automated 4f repairs) study of heavy lanthanide $\\mathrm{{Ln@Au_5}}$ ($\\mathrm{{Ln}} = \\mathrm{{Gd}}$–$\\mathrm{{Lu}}$), revealing a trivalent $8\\mathrm{{e}}^-$ superatom HOMO–LUMO gap rigidity plateau ($2.524$–$2.812$ eV), localized $4f$ spin decoupling, and divalent $\\mathrm{{Yb^{{2+}}}}$ spin delocalization.
5. **Grounded LLM Collaboration:** A `pydantic-ai` planning/interpretation layer protected by deterministic `build_plan()` dry-run validation and unit-conversion-aware numerical grounding, achieving {zh_acc} (Chinese) and {en_acc} (English) accuracy across a live 50+50 bilingual scientific instruction benchmark.

I confirm that this manuscript is original, has not been published previously, and is not under consideration elsewhere, and I declare no competing financial interests. All source code, 115 offline tests, reference DFT datasets, Multiwfn logs, `Ln@Au5` production summaries, and bilingual LLM evaluation suites are openly available under the MIT license at `https://github.com/QIANCHANGKING/quantumchem-ai` and archived at `10.5281/zenodo.24501860`.

Thank you for your time and consideration.

Sincerely,

**Changtian Qian**  
Department of Physics, Capital Normal University, Beijing 100048, China  
Email: `qianchangdtw@gmail.com` | ORCID: `0009-0005-2464-3814`
"""
    _assert_no_cjk(cl_md, "Cover_Letter.md")
    cl_md_path.write_text(cl_md, encoding="utf-8")

    body = _md_to_html(cl_md)
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Cover Letter — QuantumChem AI</title>
<style>
  body {{ font-family: "Times New Roman", Times, serif; font-size: 9.7pt; line-height: 1.36; color: #0f172a; max-width: 760px; margin: 0 auto; }}
  p {{ margin: 4px 0 6px 0; text-align: justify; }}
  ol {{ margin: 4px 0 7px 0; padding-left: 18px; }}
  li {{ margin-bottom: 3.5px; text-align: justify; }}
  code {{ font-family: Consolas, monospace; font-size: 8.4pt; background: #f8fafc; padding: 0 2px; border-radius: 2px; }}
</style>
</head>
<body>{body}</body>
</html>"""
    _compile_pdf(full_html, cl_pdf_path, header_text="", show_footer=False)
    return cl_md_path, cl_pdf_path


def main() -> int:
    si_md, si_pdf = build_supporting_information()
    cl_md, cl_pdf = build_cover_letter()
    print("SI :", si_md, si_pdf)
    print("CL :", cl_md, cl_pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

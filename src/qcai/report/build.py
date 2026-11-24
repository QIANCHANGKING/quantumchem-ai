"""HTML and Playwright A4 PDF report builder (Section 6.8)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright
from pymatgen.core.periodic_table import Element

from qcai.analysis.summary import ProjectSummary
from qcai.core.models import CalcResult
from qcai.knowledge import load_rule_yaml
from qcai.renderers import RENDERERS, build_figure_spec
from qcai.renderers.spec import (
    build_isomer_ranking_spec,
    build_size_evolution_spec,
    build_spin_ladder_spec,
    build_vde_ade_spec,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@dataclass(frozen=True)
class EmbeddedFigure:
    """Figure entry embedded into report HTML (inline SVG preferred, PNG fallback)."""

    caption: str
    inline_svg: str | None = None
    img_uri: str | None = None


def _select_bibliography(used_keys: list[str]) -> list[str]:
    bib = load_rule_yaml("bibliography.yaml")["entries"]
    refs: list[str] = []
    seen: set[str] = set()
    for key in used_keys:
        if key in bib and key not in seen:
            seen.add(key)
            refs.append(str(bib[key]["citation"]))
    return refs


def build_methods_paragraphs(
    *,
    search_desc_zh: str = "ABCluster 人工蜂群算法结合 GFN2-xTB（备选 ASE 遗传算法 + tblite）",
    search_desc_en: str = "ABCluster artificial bee colony global search combined with GFN2-xTB (with ASE-GA + tblite fallback)",
    screening_level: str = "PBE-D3BJ/def2-SVP",
    refinement_level: str = "PBE0-D3BJ/def2-TZVP",
    candidate_k: int = 8,
    has_ecp: bool = False,
    has_stability: bool = False,
    used_multiwfn: bool = False,
    used_vmd: bool = False,
) -> tuple[str, str]:
    """Render accurate ZH and EN Computational Methods paragraphs from actual workflow."""
    cfg = load_rule_yaml("methods_text.yaml")
    ecp_zh = "，对 Z > 36 元素自动采用 def2 系列内置有效核势 (ECP)" if has_ecp else ""
    ecp_en = (
        ", employing built-in def2 effective core potentials (ECPs) for elements with Z > 36"
        if has_ecp
        else ""
    )
    stab_zh = "，并对过渡金属体系执行波函数稳定性检查 (stable=opt)" if has_stability else ""
    stab_en = (
        ", alongside wavefunction stability verification (stable=opt) for transition-metal systems"
        if has_stability
        else ""
    )
    post_zh = (
        "波函数电荷/自旋布居、PDOS 与轨道成分分析通过 Multiwfn 3.8(dev) 完成"
        if used_multiwfn
        else "轨道能级与自旋布居由 Gaussian 输出经 cclib 解析得到"
    )
    if used_vmd:
        post_zh += "，三维结构与等值面图像采用 VMD (TachyonInternal) 渲染"
    post_zh += "。"
    post_en = (
        "Population, PDOS, and frontier orbital composition analyses were carried out with Multiwfn 3.8(dev)"
        if used_multiwfn
        else "Orbital energies and spin populations were extracted from Gaussian logs using cclib"
    )
    if used_vmd:
        post_en += (
            ", and 3D molecular structures/isosurfaces were rendered via VMD (TachyonInternal)"
        )
    post_en += ". "

    ctx = {
        "search_desc": search_desc_zh,
        "candidate_k": candidate_k,
        "program": "Gaussian 16",
        "screening_level": screening_level,
        "refinement_level": refinement_level,
        "ecp_clause_zh": ecp_zh,
        "stability_clause_zh": stab_zh,
        "postprocess_clause_zh": post_zh,
    }
    zh = str(cfg["zh_template"]).format(**ctx).strip()

    ctx_en = {
        "search_desc": search_desc_en,
        "candidate_k": candidate_k,
        "program": "Gaussian 16",
        "screening_level": screening_level,
        "refinement_level": refinement_level,
        "ecp_clause_en": ecp_en,
        "stability_clause_en": stab_en,
        "postprocess_clause_en": post_en,
    }
    en = str(cfg["en_template"]).format(**ctx_en).strip()
    return zh, en


def _embed_rendered_files(paths: list[Path], caption: str) -> EmbeddedFigure:
    svg_file = next((p for p in paths if p.suffix.lower() == ".svg" and p.exists()), None)
    if svg_file is not None:
        return EmbeddedFigure(caption=caption, inline_svg=svg_file.read_text(encoding="utf-8"))
    png_file = next((p for p in paths if p.suffix.lower() == ".png" and p.exists()), None)
    if png_file is not None:
        return EmbeddedFigure(caption=caption, img_uri=png_file.resolve().as_uri())
    return EmbeddedFigure(caption=caption)


def build_report(
    project_summary: ProjectSummary,
    results: list[CalcResult],
    out_dir: Path,
    *,
    title: str | None = None,
    renderer_name: str = "mpl",
    extra_images: list[tuple[Path, str]] | None = None,
    ai_interpretation: str | None = None,
    used_multiwfn: bool = False,
    used_vmd: bool = False,
    render_pdf: bool = True,
) -> tuple[Path, Path | None]:
    """Generate figures, HTML report, and A4 PDF report for a project."""
    out_dir = Path(out_dir)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    renderer = RENDERERS.get(renderer_name)

    figures: list[EmbeddedFigure] = []
    # 1. Per-cluster summary and ground-state electronic/spin plots
    res_by_id = {r.job_id: r for r in results}
    for cs in project_summary.clusters.values():
        gs = res_by_id.get(cs.ground_state_job_id)
        if gs is not None and gs.mo_energies_hartree and gs.homo_indices:
            spec_lv = build_figure_spec(gs, "levels")
            figures.append(_embed_rendered_files(renderer.render(spec_lv, fig_dir), spec_lv.title))
            spec_dos = build_figure_spec(gs, "dos")
            figures.append(
                _embed_rendered_files(renderer.render(spec_dos, fig_dir), spec_dos.title)
            )
        if gs is not None and gs.spins:
            spec_sp = build_figure_spec(gs, "spin")
            figures.append(_embed_rendered_files(renderer.render(spec_sp, fig_dir), spec_sp.title))
        if gs is not None and (gs.s2_before is not None or gs.s2_after is not None):
            spec_s2 = build_figure_spec(gs, "s2")
            figures.append(_embed_rendered_files(renderer.render(spec_s2, fig_dir), spec_s2.title))
        if len(cs.spin_ladder) >= 2:
            spec_sl = build_spin_ladder_spec(cs)
            figures.append(_embed_rendered_files(renderer.render(spec_sl, fig_dir), spec_sl.title))
        if len(cs.isomers) >= 2:
            spec_iso = build_isomer_ranking_spec(cs)
            figures.append(
                _embed_rendered_files(renderer.render(spec_iso, fig_dir), spec_iso.title)
            )
        if cs.vde_ev is not None or cs.ade_ev is not None:
            spec_va = build_vde_ade_spec(cs)
            figures.append(_embed_rendered_files(renderer.render(spec_va, fig_dir), spec_va.title))

    if len(project_summary.size_evolution) >= 2:
        spec_se = build_size_evolution_spec(project_summary)
        figures.append(_embed_rendered_files(renderer.render(spec_se, fig_dir), spec_se.title))

    if extra_images:
        for img_path, cap in extra_images:
            if img_path.exists():
                figures.append(_embed_rendered_files([img_path], cap))

    has_ecp = any(
        any(Element(sym).Z > 36 for sym in cs.stoichiometry)
        for cs in project_summary.clusters.values()
    )
    has_stability = any(r.stable is not None for r in results)
    methods_zh, methods_en = build_methods_paragraphs(
        has_ecp=has_ecp,
        has_stability=has_stability,
        used_multiwfn=used_multiwfn,
        used_vmd=used_vmd,
    )

    bib_keys = [
        "gaussian16",
        "pbe",
        "pbe0",
        "d3bj",
        "def2",
        "abcluster",
        "xtb",
        "cclib",
        "custodian",
    ]
    if used_multiwfn:
        bib_keys.append("multiwfn")
    if used_vmd:
        bib_keys.append("vmd")
    references = _select_bibliography(bib_keys)

    fixes = [{"job_id": r.job_id, "detail": "; ".join(r.fixes)} for r in results if r.fixes]

    summary_parts = [
        f"本项目共分析 {len(project_summary.clusters)} 个团簇组成与 {len(results)} 个计算作业。"
    ]
    for cs in project_summary.clusters.values():
        gap_txt = f"{cs.homo_lumo_gap_ev:.3f} eV" if cs.homo_lumo_gap_ev is not None else "N/A"
        summary_parts.append(
            f"{cs.cluster_label} (q={cs.charge}) 的基态多重度为 M={cs.ground_state_multiplicity}，"
            f"总能量 {cs.ground_state_energy_hartree:.6f} Ha，HOMO–LUMO 能隙 {gap_txt}。"
        )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["zip_lists"] = lambda a, b: list(zip(a, b, strict=False))
    template = env.get_template("report.html.j2")

    html_text = template.render(
        title=title or f"QuantumChem AI 计算分析报告：{project_summary.project_id}",
        project_id=project_summary.project_id,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        summary_text=" ".join(summary_parts),
        ai_interpretation=ai_interpretation,
        methods_zh=methods_zh,
        methods_en=methods_en,
        cluster_list=list(project_summary.clusters.values()),
        figures=figures,
        fixes=fixes,
        issues=project_summary.all_issues,
        results=results,
        references=references,
    )
    html_path = out_dir / "report.html"
    html_path.write_text(html_text, encoding="utf-8")

    pdf_path: Path | None = None
    if render_pdf:
        pdf_path = out_dir / "report.pdf"
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template=(
                    '<div style="font-size:8px;color:#64748b;width:100%;'
                    'text-align:right;padding-right:16mm;">QuantumChem AI Research Report</div>'
                ),
                footer_template=(
                    '<div style="font-size:8px;color:#64748b;width:100%;text-align:center;">'
                    '第 <span class="pageNumber"></span> / <span class="totalPages"></span> 页</div>'
                ),
            )
            browser.close()

    return html_path, pdf_path

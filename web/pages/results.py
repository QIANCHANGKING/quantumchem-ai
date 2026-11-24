"""Page 4: Results Workbench, Charts, 3D Preview, Publication Render, AI, and PDF Export."""

from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from qcai.analysis import summarize_cluster, summarize_project
from qcai.core.models import CalcResult
from qcai.core.physics import HA_TO_EV, homo_lumo_gap_hartree, total_magnetic_moment_mu_b
from qcai.renderers import RENDERERS, build_figure_spec
from qcai.renderers.vmd import VmdRenderer
from qcai.renderers.web3d import build_py3dmol_html
from qcai.report import build_report
from web.state import (
    get_deepseek_key,
    get_projects_root,
    get_store,
    has_deepseek_key,
    load_app_settings,
)
from web.theme import render_page_hero

AI_PRESET_QUESTIONS = [
    ("全面学术总结", "请总结本项目的基态结构、电子性质、自旋特征及异常警告。"),
    (
        "稳定性与幻数分析",
        "请重点分析各异构体的相对能量排序、能隙特征及是否呈现闭壳层幻数稳定趋势。",
    ),
    ("自旋与异常核查", "请核查是否存在自旋污染、虚频或波函数不稳定标记，并给出具体数值依据。"),
]


def render_results_page() -> None:
    render_page_hero(
        "4. 结果查看与出版级导出",
        "统一查看物性汇总表、2D 光谱/能级图、交互式 3D 结构、Origin/VMD 出版渲染、防幻觉 AI 解读与 A4 PDF 报告。",
        active_step=4,
    )
    store = get_store()
    projects = store.list_projects()
    if not projects:
        st.info(
            "暂无项目记录，请先在「1. 新建研究」中创建并运行项目，或使用「5. 单文件工具」离线解析日志。"
        )
        return

    proj_ids = [p.project_id for p in projects]
    proj_labels = {p.project_id: f"{p.title} ({p.project_id})" for p in projects}
    default_pid = st.session_state.get("active_project_id", proj_ids[-1])
    idx = proj_ids.index(default_pid) if default_pid in proj_ids else len(proj_ids) - 1
    pid = st.selectbox(
        "选择项目",
        options=proj_ids,
        index=idx,
        format_func=lambda x: proj_labels.get(x, x),
        key="res_proj_sb",
    )

    results: list[CalcResult] = []
    for job in store.list_jobs(project_id=pid):
        if job.result_path and Path(job.result_path).exists():
            results.append(
                CalcResult.model_validate_json(Path(job.result_path).read_text(encoding="utf-8"))
            )

    if not results:
        st.warning("该项目尚无已解析的计算结果。")
        return

    grouped: dict[str, list[CalcResult]] = {}
    for r in results:
        if r.final_geometry is not None:
            cnt = Counter(r.final_geometry.symbols)
            formula = "".join(f"{el}{n if n > 1 else ''}" for el, n in sorted(cnt.items()))
        else:
            formula = r.job_id
        grouped.setdefault(f"{formula} (q={r.state.charge})", []).append(r)

    clusters = {
        k: summarize_cluster(k, grp)
        for k, grp in grouped.items()
        if any(r.normal_termination and r.energy_hartree is not None for r in grp)
    }
    proj_summary = summarize_project(pid, clusters)

    # Top KPI Strip
    gs: CalcResult = results[0]
    if clusters:
        cs = next(iter(clusters.values()))
        gs = next((r for r in results if r.job_id == cs.ground_state_job_id), results[0])
        gap_ha = homo_lumo_gap_hartree(gs.mo_energies_hartree, gs.homo_indices)
        k1, k2, k3, k4, k5 = st.columns([0.9, 1.35, 1.15, 1.0, 0.9])
        short_formula = cs.cluster_label.split(" ", 1)[0]
        k1.metric(f"基态体系 (q={cs.charge})", short_formula)
        k2.metric(
            "基态能量",
            f"{gs.energy_hartree:.4f} Ha" if gs.energy_hartree is not None else "N/A",
        )
        k3.metric(
            "自旋与磁矩",
            f"M={gs.state.multiplicity} / {total_magnetic_moment_mu_b(gs.state.multiplicity):.1f} μB",
        )
        k4.metric("HOMO–LUMO 隙", f"{gap_ha * HA_TO_EV:.3f} eV" if gap_ha is not None else "N/A")
        k5.metric("作业 / 警示", f"{len(results)} / {len(proj_summary.all_issues)}")

    table_rows = [
        {
            "job_id": r.job_id,
            "normal": r.normal_termination,
            "error": r.error_code or "",
            "charge": r.state.charge,
            "mult": r.state.multiplicity,
            "energy_Ha": r.energy_hartree,
            "zpe_Ha": r.zpe_hartree,
            "s2_after": r.s2_after,
            "imag_freqs": len(r.imag_freqs),
        }
        for r in results
    ]
    df = pd.DataFrame(table_rows)

    # Always-visible Quick Export & Report Action Bar
    last_interp = st.session_state.get("last_ai_interp")
    with st.container(border=True):
        ac1, ac2, ac3 = st.columns(3)
        ac1.download_button(
            "导出数据表 (CSV)",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"{pid}_results.csv",
            mime="text/csv",
            use_container_width=True,
        )
        if ac2.button(
            "生成 PDF / HTML 报告",
            type="primary",
            use_container_width=True,
            key="btn_build_pdf",
        ):
            rep_dir = get_projects_root() / pid / "report"
            ai_txt = last_interp["text"] if (last_interp and last_interp.get("verified")) else None
            with st.spinner("正在构建 A4 出版级 HTML / PDF 报告..."):
                html_p, pdf_p = build_report(
                    proj_summary,
                    results,
                    rep_dir,
                    renderer_name="mpl",
                    ai_interpretation=ai_txt,
                    render_pdf=True,
                )
            st.session_state["last_pdf_path"] = str(pdf_p) if pdf_p else ""
            st.success(f"报告已生成：{html_p.name}" + (f" / {pdf_p.name}" if pdf_p else ""))

        last_pdf = st.session_state.get("last_pdf_path")
        if last_pdf and Path(last_pdf).exists():
            ac3.download_button(
                "下载 PDF 报告",
                data=Path(last_pdf).read_bytes(),
                file_name=f"{pid}_report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            ac3.caption("点击左侧按钮生成后可一键下载 PDF 报告")

    tab_tbl, tab_2d, tab_3d, tab_ai = st.tabs(
        [
            "📋 计算结果明细表",
            "📈 2D 图表与 Origin 出图",
            "🧬 3D 结构与 VMD 渲染",
            "🤖 DeepSeek AI 结果解读",
        ]
    )

    with tab_tbl:
        st.dataframe(df, use_container_width=True, hide_index=True)
        if proj_summary.all_issues:
            st.warning("项目物理异常与注意事项：")
            for issue in proj_summary.all_issues:
                st.write(f"- {issue}")

    with tab_2d:
        pc1, pc2 = st.columns([1.2, 2.5])
        with pc1:
            plot_kind = st.selectbox(
                "选择 2D 图类型",
                options=["levels", "dos", "spin", "s2"],
                format_func=lambda k: {
                    "levels": "分子轨道能级图 (levels)",
                    "dos": "态密度 TDOS / PDOS (dos)",
                    "spin": "原子自旋布居 (spin)",
                    "s2": "自旋期望值 <S²> (s2)",
                }[k],
                key="res_plot_kind",
            )
            if st.button("Origin 2024b 出版级 2D 出图", use_container_width=True):
                try:
                    out_dir = get_projects_root() / pid / "origin_pub"
                    spec = build_figure_spec(gs, plot_kind)  # type: ignore[arg-type]
                    with st.spinner("正在调用后台 Origin 2024b 渲染 PNG / SVG / OPJU..."):
                        files = RENDERERS.get("origin").render(spec, out_dir)
                    st.success(f"Origin 已输出：{', '.join(p.name for p in files)}")
                except Exception as exc:
                    st.error(f"Origin 出图失败：{exc}")
        with pc2:
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    spec = build_figure_spec(gs, plot_kind)  # type: ignore[arg-type]
                    mpl_files = RENDERERS.get("mpl").render(spec, Path(tmp))
                    png_p = next((p for p in mpl_files if p.suffix == ".png"), None)
                    svg_p = next((p for p in mpl_files if p.suffix == ".svg"), None)
                    if png_p is not None:
                        st.image(str(png_p), caption=spec.title, use_container_width=True)
                        dl1, dl2 = st.columns(2)
                        dl1.download_button(
                            "下载 PNG",
                            data=png_p.read_bytes(),
                            file_name=png_p.name,
                            mime="image/png",
                            use_container_width=True,
                        )
                        if svg_p is not None:
                            dl2.download_button(
                                "下载 SVG 矢量图",
                                data=svg_p.read_bytes(),
                                file_name=svg_p.name,
                                mime="image/svg+xml",
                                use_container_width=True,
                            )
            except Exception as exc:
                st.info(f"当前体系暂无 {plot_kind} 所需数据：{exc}")

    with tab_3d:
        iso_val = st.slider(
            "Cube 等值面阈值", min_value=0.005, max_value=0.10, value=0.03, step=0.005
        )
        if gs.final_geometry is not None:
            cube_text: str | None = None
            if gs.cubes:
                first_cube = next(iter(gs.cubes.values()))
                if first_cube.exists():
                    cube_text = first_cube.read_text(encoding="utf-8", errors="replace")
            components.html(
                build_py3dmol_html(gs.final_geometry, cube_text=cube_text, isovalue=iso_val),
                height=460,
            )
            if st.button("VMD 出版级 3D 渲染", use_container_width=True):
                try:
                    out_dir = get_projects_root() / pid / "vmd_pub"
                    with st.spinner("正在调用 VMD (TachyonInternal) 渲染..."):
                        vmd_files = VmdRenderer().render_cluster(
                            gs.final_geometry, out_dir, isovalue=iso_val
                        )
                    st.image(str(vmd_files[0]), caption="VMD TachyonInternal 渲染图")
                except Exception as exc:
                    st.error(f"VMD 渲染失败：{exc}")
        else:
            st.info("该基态作业未提取到三维坐标。")

    with tab_ai:
        st.caption(
            "严格执行公理 A1（数值确定性）：AI 回答中的每个物理量都会与确定性计算结果逐一核验，未锚定数值会被自动拦截并标红。"
        )
        pcols = st.columns(len(AI_PRESET_QUESTIONS))
        for col, (lbl, q_txt) in zip(pcols, AI_PRESET_QUESTIONS, strict=True):
            if col.button(f"快捷：{lbl}", use_container_width=True, key=f"ai_pre_{lbl}"):
                st.session_state["res_ai_q"] = q_txt

        ai_q = st.text_input(
            "提问或自定义解读要求",
            value=st.session_state.get(
                "res_ai_q", "请总结本项目的基态结构、电子性质、自旋特征及异常警告。"
            ),
            key="res_ai_q",
        )
        if st.button("✨ 生成 AI 解读", type="primary", key="btn_ai_interpret"):
            if not has_deepseek_key(load_app_settings()):
                st.warning("请先在「6. 设置」页面配置 DeepSeek API Key。")
            else:
                from qcai.ai import interpret_project

                with st.spinner("正在调用 DeepSeek 结合只读工具生成并核验数值..."):
                    interp = interpret_project(store, pid, ai_q, api_key=get_deepseek_key())
                st.session_state["last_ai_interp"] = interp.model_dump()
                last_interp = st.session_state["last_ai_interp"]

        if last_interp:
            if last_interp.get("verified"):
                st.success("✅ 已通过数值确定性校验（所有数值均锚定真实计算结果）")
                st.markdown(last_interp["text"])
            else:
                st.error(last_interp["text"])


render_results_page()

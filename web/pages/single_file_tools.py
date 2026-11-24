"""Page 5: Offline Single-File Tools (Parse/Plot Gaussian Log & Generate GJF)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st
from ase.io import read as ase_read

from qcai.core.models import CalcSpec, Cluster, ElectronicState
from qcai.core.physics import HA_TO_EV, homo_lumo_gap_hartree, total_electrons
from qcai.programs.gaussian.parser import parse_gaussian_log
from qcai.programs.gaussian.writer import write_gaussian_input
from qcai.renderers import RENDERERS, build_figure_spec
from web.theme import REPO_ROOT, render_page_hero

DEMO_SAMPLES = {
    "Al₁₂Cu 掺杂团簇 (黄金样本)": REPO_ROOT / "tests" / "data" / "golden" / "al12cu" / "job.log",
    "W@Au₁₂ 内嵌超原子 (黄金样本)": REPO_ROOT / "tests" / "data" / "golden" / "w_au12" / "job.log",
    "Fe₄ 高自旋团簇 (M=13)": REPO_ROOT / "tests" / "data" / "golden" / "fe4" / "job.log",
}


def render_single_file_tools_page() -> None:
    render_page_hero(
        "5. 单文件工具（离线可用，不依赖服务器）",
        "无需连接远程集群，直接拖入单个 Gaussian 日志即可解析物理量与出图，或由结构文件一键生成规范 .gjf 输入。",
    )

    tab_parse, tab_gen = st.tabs(["Gaussian 日志解析与出图", "结构文件生成 .gjf"])

    with tab_parse:
        with st.container(border=True):
            up_log = st.file_uploader(
                "上传 Gaussian 输出日志 (.log / .out)", type=["log", "out"], key="sf_log"
            )
            dc1, dc2, dc3 = st.columns([1.8, 1.2, 1.2])
            demo_choice = dc1.selectbox(
                "或快速加载内置真实算例体验",
                options=["不使用示例", *DEMO_SAMPLES.keys()],
                key="sf_demo_sb",
            )
            kind = dc2.selectbox(
                "选择绘图类型",
                options=["levels", "dos", "spin", "s2"],
                key="sf_plot_kind",
            )
            renderer_choice = dc3.radio(
                "渲染器", options=["mpl", "origin"], horizontal=True, key="sf_rend"
            )

        active_log_bytes: bytes | None = None
        active_log_name = ""
        if up_log is not None:
            active_log_bytes = up_log.getvalue()
            active_log_name = up_log.name
        elif demo_choice in DEMO_SAMPLES and DEMO_SAMPLES[demo_choice].exists():
            demo_path = DEMO_SAMPLES[demo_choice]
            active_log_bytes = demo_path.read_bytes()
            active_log_name = demo_path.parent.name + ".log"

        if active_log_bytes is not None:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_dir = Path(tmp)
                log_path = tmp_dir / active_log_name
                log_path.write_bytes(active_log_bytes)
                res = parse_gaussian_log(log_path)

                gap_ha = homo_lumo_gap_hartree(res.mo_energies_hartree, res.homo_indices)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("正常结束", "是" if res.normal_termination else f"否 ({res.error_code})")
                c2.metric(
                    "总能量 (Ha)",
                    f"{res.energy_hartree:.6f}" if res.energy_hartree is not None else "N/A",
                )
                c3.metric("电荷 / 多重度", f"{res.state.charge} / {res.state.multiplicity}")
                c4.metric(
                    "HOMO–LUMO (eV)", f"{gap_ha * HA_TO_EV:.3f}" if gap_ha is not None else "N/A"
                )

                try:
                    spec = build_figure_spec(res, kind)  # type: ignore[arg-type]
                    out_files = RENDERERS.get(renderer_choice).render(spec, tmp_dir / "plots")
                    png = next((p for p in out_files if p.suffix == ".png"), None)
                    svg = next((p for p in out_files if p.suffix == ".svg"), None)
                    if png is not None:
                        st.image(str(png), caption=spec.title, use_container_width=True)
                        dl1, dl2 = st.columns(2)
                        dl1.download_button(
                            "下载 PNG 图片",
                            data=png.read_bytes(),
                            file_name=png.name,
                            mime="image/png",
                            use_container_width=True,
                        )
                        if svg is not None:
                            dl2.download_button(
                                "下载 SVG 矢量图",
                                data=svg.read_bytes(),
                                file_name=svg.name,
                                mime="image/svg+xml",
                                use_container_width=True,
                            )
                except Exception as exc:
                    st.warning(f"无法绘制 {kind}：{exc}")

    with tab_gen:
        with st.container(border=True):
            up_struct = st.file_uploader(
                "上传结构文件 (.xyz / .gjf / .cif)", type=["xyz", "gjf", "cif"], key="sf_struct"
            )
            c1, c2, c3 = st.columns(3)
            func = c1.text_input("泛函", value="PBE0", key="sf_func")
            basis = c2.text_input("基组", value="def2-TZVP", key="sf_basis")
            charge = int(c3.number_input("总电荷", value=0, step=1, key="sf_charge"))
            tasks = st.multiselect(
                "任务类型",
                options=["sp", "opt", "freq", "stable"],
                default=["opt", "freq"],
                key="sf_tasks",
            )

        if up_struct is not None:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_dir = Path(tmp)
                in_p = tmp_dir / up_struct.name
                in_p.write_bytes(up_struct.getvalue())
                atoms = ase_read(str(in_p))
                if isinstance(atoms, list):
                    atoms = atoms[-1]
                cluster = Cluster.from_ase(atoms, label=in_p.stem)
                n_elec = total_electrons(cluster.symbols, charge)
                default_m = 1 if n_elec % 2 == 0 else 2
                mult = int(
                    st.number_input("多重度", min_value=1, value=default_m, step=2, key="sf_mult")
                )
                try:
                    out_gjf = tmp_dir / f"{in_p.stem}.gjf"
                    write_gaussian_input(
                        cluster,
                        ElectronicState(charge=charge, multiplicity=mult),
                        CalcSpec(functional=func, basis=basis, tasks=tasks or ["opt"]),  # type: ignore[arg-type]
                        out_gjf,
                    )
                    gjf_text = out_gjf.read_text(encoding="utf-8")
                    st.code(gjf_text, language="text")
                    st.download_button(
                        "下载 .gjf",
                        data=gjf_text,
                        file_name=out_gjf.name,
                        mime="text/plain",
                        use_container_width=True,
                    )
                except Exception as exc:
                    st.error(f"生成失败：{exc}")


render_single_file_tools_page()

"""Generate all publication-grade figures (SVG, VMD 3D, Origin 2024b 2D, and Web UI) for the paper."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

from qcai.core.physics import HA_TO_EV, homo_lumo_gap_hartree
from qcai.pipeline import JobRecord, JobStore, ProjectRecord
from qcai.planner import build_plan
from qcai.programs.gaussian.parser import parse_gaussian_log
from qcai.programs.multiwfn import parse_charge_spin, parse_orb_comp, parse_pdos
from qcai.renderers.web3d.viewer import align_cluster_principal_axes, minority_atom_indices

REPO_ROOT = Path(__file__).resolve().parents[1]
FIG_DIR = REPO_ROOT / "paper" / "figures"
TMP_DIR = REPO_ROOT / "projects" / "paper_tmp"
GOLDEN_DIR = REPO_ROOT / "tests" / "data" / "golden"
MWFN_DIR = REPO_ROOT / "tests" / "data" / "multiwfn" / "al12cu"
VMD_EXE = Path(os.environ.get("VMD_EXE", "vmd"))


def _load_font(size: int, *, bold: bool = False) -> Any:
    candidates = (
        [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\arialbd.ttf"]
        if bold
        else [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\arial.ttf"]
    )
    for c in candidates:
        if Path(c).exists():
            return ImageFont.truetype(c, size=size)
    return ImageFont.load_default()


def _trim_white(img: Image.Image, *, margin: int = 16, threshold: int = 248) -> Image.Image:
    rgb = img.convert("RGB")
    bg = Image.new("RGB", rgb.size, (255, 255, 255))
    diff = ImageChops.difference(rgb, bg)
    gray = diff.convert("L")
    mask = gray.point(lambda px: 255 if px > (255 - threshold) else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return rgb
    x0 = max(0, bbox[0] - margin)
    y0 = max(0, bbox[1] - margin)
    x1 = min(rgb.width, bbox[2] + margin)
    y1 = min(rgb.height, bbox[3] + margin)
    return rgb.crop((x0, y0, x1, y1))


def _fit_tile(img: Image.Image, width: int, height: int) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    copy = img.copy()
    copy.thumbnail((width - 24, height - 24), Image.Resampling.LANCZOS)
    ox = (width - copy.width) // 2
    oy = (height - copy.height) // 2
    canvas.paste(copy, (ox, oy))
    return canvas


def build_architecture_svg() -> Path:
    """Write publication-grade Fig. 1 vector SVG (academic multi-panel schematic)."""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / "fig1_architecture.svg"

    layers = [
        (
            "L1",
            "交互与桌面封装层",
            "[条款 C5, C6]",
            "Streamlit 6 页极简工作台",
            "Typer CLI · qcai-app.exe 无黑框",
            "OS Keyring · 免代理 · 脱敏发布 ZIP",
            42,
        ),
        (
            "L2",
            "全元素规则引擎与规划层",
            "[条款 C2, C3, C4]",
            "YAML 规则库 (AST 零元素分支)",
            "奇偶守恒 · 洪特规则 · BSE GenECP",
            "OLS 耗时校准 · 预算收缩 · 方案书",
            106,
        ),
        (
            "L3",
            "幂等漏斗流水线与构型去重层",
            "[条款 C7]",
            "SQLite 状态机 (暂停/恢复/对账)",
            "PointGroup 掺杂 · 三轴 Kabsch 去重",
            "S0–S7 编排 · needs_human 传播",
            170,
        ),
        (
            "L4",
            "远程集群调度与自愈执行层",
            "[条款 C7, C8]",
            "ShellIO / setsid 进程组 · 白名单",
            "NUMA 拓扑探测 · 满载礼让 (jobs=0)",
            "三段 Link1 · 无损 SCF/尾段自愈",
            234,
        ),
        (
            "L5",
            "物理分析与多引擎出版输出层",
            "[条款 C1, C4, C5, C8]",
            "cclib + Multiwfn 3.8(dev) 版本锁",
            "FigureSpec → Origin 2024b / MPL",
            "惯量对齐 VMD 光追 · A4 PDF 报告",
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
  <text x="60" y="{y + 15}" fill="#0f172a" font-size="10.6" font-weight="bold">{title}</text>
  <text x="638" y="{y + 14.5}" text-anchor="end" fill="#0f2557" font-size="9" font-weight="bold">{clause}</text>
  <rect x="60" y="{y + 20}" width="186" height="19" rx="1" fill="#f8fafc" stroke="#cbd5e1" stroke-width="0.75"/>
  <text x="153" y="{y + 33}" text-anchor="middle" fill="#334155" font-size="8.9">{c1}</text>
  <rect x="252" y="{y + 20}" width="190" height="19" rx="1" fill="#f8fafc" stroke="#cbd5e1" stroke-width="0.75"/>
  <text x="347" y="{y + 33}" text-anchor="middle" fill="#334155" font-size="8.9">{c2}</text>
  <rect x="448" y="{y + 20}" width="190" height="19" rx="1" fill="#f8fafc" stroke="#cbd5e1" stroke-width="0.75"/>
  <text x="543" y="{y + 33}" text-anchor="middle" fill="#334155" font-size="8.9">{c3}</text>"""
        )

    for y1, y2, label in contracts:
        ym = (y1 + y2) // 2 + 3
        layer_svg_parts.append(
            f"""  <line x1="156" y1="{y1}" x2="156" y2="{y2 - 2}" stroke="#1e293b" stroke-width="1.2" marker-end="url(#arr)"/>
  <rect x="166" y="{ym - 10}" width="356" height="13" rx="1" fill="#eff6ff" stroke="#bfdbfe" stroke-width="0.7"/>
  <text x="172" y="{ym}" fill="#1e3a8a" font-family="Consolas, 'Courier New', monospace" font-size="8.7">{label}</text>"""
        )

    stages = [
        ("S0 规划", "Rule Engine", "YAML + BSE", "预算收缩", "#e2e8f0", "#0f172a", "#64748b"),
        ("S1 搜索", "ABCluster /", "Molclus /", "xTB · GA", "#e2e8f0", "#0f172a", "#64748b"),
        ("S2 去重", "特征值指纹", "三轴 Kabsch", "对称掺杂", "#cbd5e1", "#0f172a", "#475569"),
        ("S3 粗筛", "PBE-D3BJ", "def2-SVP", "窗口初排", "#cbd5e1", "#0f172a", "#475569"),
        ("S4 精算", "PBE0 / TPSSh", "def2-TZVP", "Link1+早停", "#bfdbfe", "#0f2557", "#1e3a8a"),
        ("S5 参比", "孤立原子", "n±1 / VDE", "同水平[C4]", "#bfdbfe", "#0f2557", "#1e3a8a"),
        ("S6 波函", "formchk", "Multiwfn", "PDOS/轨道", "#93c5fd", "#0f2557", "#0f2557"),
        ("S7 报告", "10类图 + 3D", "A4 PDF", "缺陷显性[C8]", "#0f2557", "#ffffff", "#0f2557"),
    ]
    stage_svg_parts: list[str] = []
    for idx, (st_hdr, l1, l2, l3, hdr_fill, hdr_fg, brd) in enumerate(stages):
        sx = 22 + idx * 87
        stage_svg_parts.append(
            f"""  <rect x="{sx}" y="405" width="76" height="68" rx="1.5" fill="#ffffff" stroke="{brd}" stroke-width="1"/>
  <rect x="{sx}" y="405" width="76" height="19" rx="1" fill="{hdr_fill}"/>
  <text x="{sx + 38}" y="418" text-anchor="middle" fill="{hdr_fg}" font-size="9.5" font-weight="bold">{st_hdr}</text>
  <text x="{sx + 38}" y="436" text-anchor="middle" fill="#1e293b" font-size="8.4">{l1}</text>
  <text x="{sx + 38}" y="450" text-anchor="middle" fill="#1e293b" font-size="8.4">{l2}</text>
  <text x="{sx + 38}" y="464" text-anchor="middle" fill="#475569" font-size="8.2">{l3}</text>"""
        )
        if idx < len(stages) - 1:
            ax1 = sx + 76
            ax2 = sx + 85
            stage_svg_parts.append(
                f"""  <line x1="{ax1}" y1="439" x2="{ax2}" y2="439" stroke="#334155" stroke-width="1.15" marker-end="url(#arr)"/>"""
            )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1040 572" width="1040" height="572" font-family="'Microsoft YaHei', 'SimHei', 'Helvetica Neue', Arial, sans-serif">
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

  <!-- Panel (a): Five-Layer Architecture -->
  <rect x="10" y="8" width="646" height="350" rx="1.5" fill="#ffffff" stroke="#334155" stroke-width="1"/>
  <rect x="10" y="8" width="646" height="24" rx="1" fill="#f1f5f9"/>
  <line x1="10" y1="32" x2="656" y2="32" stroke="#0f2557" stroke-width="1.2"/>
  <text x="18" y="24" fill="#0f2557" font-size="11.5" font-weight="bold">(a) 五层确定性协同架构与层间数据契约 (Layered Stack &amp; Data Contracts)</text>
{chr(10).join(layer_svg_parts)}

  <!-- Panel (b): Constitutional AI Closed-Loop Control -->
  <rect x="670" y="8" width="360" height="350" rx="1.5" fill="#ffffff" stroke="#334155" stroke-width="1"/>
  <rect x="670" y="8" width="360" height="24" rx="1" fill="#f1f5f9"/>
  <line x1="670" y1="32" x2="1030" y2="32" stroke="#0f2557" stroke-width="1.2"/>
  <text x="678" y="24" fill="#0f2557" font-size="11.5" font-weight="bold">(b) 设计宪法驱动的 LLM 闭环校验流 (C1–C3, C6)</text>

  <!-- Loop 1: NL Intent & Deterministic Plan Guard -->
  <rect x="682" y="42" width="256" height="46" rx="1.5" fill="#f8fafc" stroke="#334155" stroke-width="1"/>
  <text x="810" y="57" text-anchor="middle" fill="#0f172a" font-size="10.2" font-weight="bold">意图规划 Agent (DeepSeek)</text>
  <text x="810" y="70" text-anchor="middle" fill="#1e3a8a" font-family="Consolas, 'Courier New', monospace" font-size="8.6">parse_natural_language_intent(history)</text>
  <text x="810" y="82" text-anchor="middle" fill="#475569" font-size="8.5">单轮直达 · 多轮上下文融合 · 批量 ProposedPlan</text>

  <line x1="810" y1="88" x2="810" y2="103" stroke="#1e293b" stroke-width="1.15" marker-end="url(#arr)"/>

  <rect x="682" y="105" width="256" height="50" rx="1.5" fill="#fff1f2" stroke="#881337" stroke-width="1.2"/>
  <text x="810" y="120" text-anchor="middle" fill="#881337" font-size="9.8" font-weight="bold">宪法 C2/C3 规划守卫 (@output_validator)</text>
  <text x="690" y="135" fill="#334155" font-size="8.6">• _validate_composition 拦截 Ln/TM 通配符</text>
  <text x="690" y="148" fill="#334155" font-size="8.6">• build_plan() 预演校验 request 与推荐方案</text>

  <!-- Feedback Loop 1 -->
  <path d="M 938 130 L 954 130 L 954 65 L 940 65" fill="none" stroke="#881337" stroke-width="1.15" stroke-dasharray="3.5,2.5" marker-end="url(#arr-crimson)"/>
  <text x="960" y="92" fill="#881337" font-size="8.4" font-weight="bold">校验未过:</text>
  <text x="960" y="104" fill="#881337" font-family="Consolas, 'Courier New', monospace" font-size="8.3">ModelRetry</text>
  <text x="960" y="116" fill="#881337" font-size="8.2">(≤ 2 次重试)</text>

  <line x1="680" y1="168" x2="1020" y2="168" stroke="#cbd5e1" stroke-width="0.9" stroke-dasharray="3,2"/>
  <text x="810" y="182" text-anchor="middle" fill="#475569" font-size="8.4">↑ Pass → 合法请求直入 L2  |  ↓ 仅读摘要 (宪法隔离)</text>

  <!-- Loop 2: Read-Only Interpretation & Anti-Hallucination Guard -->
  <rect x="682" y="192" width="256" height="48" rx="1.5" fill="#f8fafc" stroke="#334155" stroke-width="1"/>
  <text x="810" y="207" text-anchor="middle" fill="#0f172a" font-size="10.2" font-weight="bold">只读解读 Agent (interpret_project)</text>
  <text x="810" y="220" text-anchor="middle" fill="#334155" font-size="8.6">仅授权 6 只读工具 · 严禁外泄密钥/原始日志 [C6]</text>
  <text x="810" y="233" text-anchor="middle" fill="#475569" font-size="8.5">调度动作仅返回 PendingActionRequest 确认体</text>

  <line x1="810" y1="240" x2="810" y2="255" stroke="#1e293b" stroke-width="1.15" marker-end="url(#arr)"/>

  <rect x="682" y="257" width="256" height="54" rx="1.5" fill="#fff1f2" stroke="#881337" stroke-width="1.2"/>
  <text x="810" y="272" text-anchor="middle" fill="#881337" font-size="9.8" font-weight="bold">宪法 C1 防幻觉数值守卫 (@output_validator)</text>
  <text x="690" y="287" fill="#334155" font-size="8.6">• 事实基线 ∪ 单位换算扩集 (Ha↔eV/kcal/kJ/%)</text>
  <text x="690" y="301" fill="#334155" font-size="8.6">• 检出任何未锚定物理数值即拒绝输出</text>

  <!-- Feedback Loop 2 -->
  <path d="M 938 284 L 954 284 L 954 216 L 940 216" fill="none" stroke="#881337" stroke-width="1.15" stroke-dasharray="3.5,2.5" marker-end="url(#arr-crimson)"/>
  <text x="960" y="244" fill="#881337" font-size="8.4" font-weight="bold">数值越界:</text>
  <text x="960" y="256" fill="#881337" font-family="Consolas, 'Courier New', monospace" font-size="8.3">ModelRetry</text>
  <text x="960" y="268" fill="#881337" font-size="8.2">(≤ 2 次重试)</text>

  <line x1="810" y1="311" x2="810" y2="324" stroke="#1e293b" stroke-width="1.15" marker-end="url(#arr)"/>
  <rect x="682" y="326" width="256" height="22" rx="1" fill="#f1f5f9" stroke="#64748b" stroke-width="0.8"/>
  <text x="810" y="340.5" text-anchor="middle" fill="#0f172a" font-family="Consolas, 'Courier New', monospace" font-size="8.7">verified=True → UI 放行 | False → 标红拦截 [C1]</text>

  <!-- Orthogonal Inter-Panel Connectors (zero crossings) -->
  <line x1="646" y1="64" x2="680" y2="64" stroke="#1e40af" stroke-width="1.25" marker-end="url(#arr-blue)"/>
  <line x1="682" y1="130" x2="648" y2="130" stroke="#1e40af" stroke-width="1.25" marker-end="url(#arr-blue)"/>
  <path d="M 646 318 L 663 318 L 663 216 L 680 216" fill="none" stroke="#475569" stroke-width="1.15" stroke-dasharray="3,2" marker-end="url(#arr)"/>

  <!-- Connector (a) L3 pipeline to (c) Funnel -->
  <line x1="333" y1="358" x2="333" y2="369" stroke="#0f2557" stroke-width="1.3" marker-end="url(#arr)"/>

  <!-- Panel (c): S0-S7 Multi-Fidelity Funnel & Registry[T] -->
  <rect x="10" y="370" width="1020" height="194" rx="1.5" fill="#ffffff" stroke="#334155" stroke-width="1"/>
  <rect x="10" y="370" width="1020" height="24" rx="1" fill="#f1f5f9"/>
  <line x1="10" y1="394" x2="1030" y2="394" stroke="#0f2557" stroke-width="1.2"/>
  <text x="18" y="386" fill="#0f2557" font-size="11.5" font-weight="bold">(c) S0–S7 多精度漏斗压缩流水线与 Registry[T] 可扩展插件及宪法门禁</text>

{chr(10).join(stage_svg_parts)}

  <!-- Funnel Dimensionality Reduction Envelope under S0-S7 -->
  <polygon points="109,482 356,488 532,493 707,496 707,510 532,513 356,518 109,524" fill="#f1f5f9" stroke="#64748b" stroke-width="0.9"/>
  <rect x="22" y="482" width="76" height="42" rx="1" fill="#f8fafc" stroke="#cbd5e1" stroke-width="0.8"/>
  <text x="60" y="500" text-anchor="middle" fill="#334155" font-size="8.4" font-weight="bold">搜索→收敛</text>
  <text x="60" y="514" text-anchor="middle" fill="#475569" font-size="8">多尺度漏斗</text>
  <text x="148" y="506" text-anchor="middle" fill="#0f172a" font-size="8.4" font-weight="bold">10²–10³ 初始构型</text>
  <text x="275" y="506" text-anchor="middle" fill="#334155" font-size="8.4">前 K 候选排序</text>
  <text x="415" y="506" text-anchor="middle" fill="#0f2557" font-size="8.4">自旋早停锁定 M_gs</text>
  <text x="615" y="506" text-anchor="middle" fill="#0f2557" font-size="8.4" font-weight="bold">全物性图谱与报告</text>
  <line x1="115" y1="538" x2="703" y2="538" stroke="#475569" stroke-width="1" marker-end="url(#arr)"/>
  <text x="408" y="553" text-anchor="middle" fill="#334155" font-size="8.8">构型空间逐级降维 (N_iso ↓↓)  ·  哈密顿量精度与电子结构完备度递增 (Fidelity ↑↑)</text>

  <!-- Right block in Panel (c): Registry[T] & Constitutional Gates -->
  <rect x="724" y="405" width="294" height="86" rx="1.5" fill="#ffffff" stroke="#334155" stroke-width="1"/>
  <rect x="724" y="405" width="294" height="19" rx="1" fill="#0f2557"/>
  <text x="871" y="418" text-anchor="middle" fill="#ffffff" font-size="9.5" font-weight="bold">Registry[T] 六大泛型插件注册表</text>
  <text x="732" y="437" fill="#0f172a" font-size="8.4"><tspan font-weight="bold">QCPROGRAMS</tspan> : Gaussian 16 (扩展 ORCA / CP2K)</text>
  <text x="732" y="451" fill="#0f172a" font-size="8.4"><tspan font-weight="bold">GENERATORS</tspan> : Import / ABCluster / Molclus / ASE-GA</text>
  <text x="732" y="465" fill="#0f172a" font-size="8.4"><tspan font-weight="bold">RENDERERS</tspan>  : Matplotlib / Origin 2024b / VMD</text>
  <text x="732" y="479" fill="#0f172a" font-size="8.4"><tspan font-weight="bold">RUNNERS·LLM</tspan>: DirectRunner / DeepSeek / Profile</text>

  <rect x="724" y="499" width="294" height="55" rx="1.5" fill="#fff1f2" stroke="#881337" stroke-width="1"/>
  <text x="871" y="514" text-anchor="middle" fill="#881337" font-size="9.2" font-weight="bold">设计宪法自动化门禁 (CI / Runtime Enforcement)</text>
  <text x="732" y="530" fill="#334155" font-size="8.4">• AST 扫描零元素硬编码 [C2]    • 理论水平一致校验 [C4]</text>
  <text x="732" y="544" fill="#334155" font-size="8.4">• Keyring 凭据零回显 [C6]      • 规划/数值双重守卫 [C1–C3]</text>
</svg>
"""
    out.write_text(svg, encoding="utf-8")
    return out


def _render_vmd_single(
    *,
    tag: str,
    xyz_path: Path | None,
    cube_path: Path | None,
    bond_cutoff: float,
    dopant_indices: list[int],
    rot_xy: tuple[float, float] = (20.0, 28.0),
    isovalue: float = 0.0035,
) -> Path:
    vmd_tmp = TMP_DIR / "vmd_tiles"
    vmd_tmp.mkdir(parents=True, exist_ok=True)
    tga = vmd_tmp / f"{tag}.tga"
    png = vmd_tmp / f"{tag}.png"
    tcl = vmd_tmp / f"{tag}.tcl"
    for p in (tga, png):
        if p.exists():
            p.unlink()

    load_cmd = (
        f"mol new {{{cube_path.resolve().as_posix()}}} type cube waitfor all"
        if cube_path is not None
        else f"mol new {{{xyz_path.resolve().as_posix()}}} type xyz waitfor all"  # type: ignore[union-attr]
    )
    lines = [
        load_cmd,
        "display resize 1000 820",
        "display projection Orthographic",
        "display depthcue off",
        "display shadows on",
        "display ambientocclusion on",
        "display aoambient 0.85",
        "display aodirect 0.35",
        "color Display Background white",
        "axes location Off",
        "mol delrep 0 top",
        # Sleek metallic bonds across cluster cutoff
        f"mol representation DynamicBonds {bond_cutoff:.2f} 0.18 28",
        "mol color ColorID 2",
        "mol material AOShiny",
        "mol addrep top",
    ]
    if dopant_indices:
        idx_str = " ".join(str(i) for i in dopant_indices)
        lines.extend(
            [
                "mol representation CPK 0.82 0.0 34 34",
                "mol color ColorID 15",
                f"mol selection {{not index {idx_str}}}",
                "mol material AOShiny",
                "mol addrep top",
                "mol representation CPK 0.96 0.0 34 34",
                "mol color ColorID 3",
                f"mol selection {{index {idx_str}}}",
                "mol material AOShiny",
                "mol addrep top",
            ]
        )
    else:
        lines.extend(
            [
                "mol representation CPK 0.85 0.0 34 34",
                "mol color ColorID 23",
                "mol selection {all}",
                "mol material AOShiny",
                "mol addrep top",
            ]
        )

    if cube_path is not None:
        lines.extend(
            [
                f"mol representation Isosurface {isovalue:.4f} 0 0 0 1 1",
                "mol color ColorID 1",
                "mol material Transparent",
                "mol addrep top",
                f"mol representation Isosurface {-isovalue:.4f} 0 0 0 1 1",
                "mol color ColorID 0",
                "mol material Transparent",
                "mol addrep top",
            ]
        )

    lines.extend(
        [
            f"rotate x by {rot_xy[0]:.1f}",
            f"rotate y by {rot_xy[1]:.1f}",
            "scale by 1.22",
            f"render TachyonInternal {{{tga.resolve().as_posix()}}}",
            "quit",
        ]
    )
    tcl.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(
        [str(VMD_EXE), "-dispdev", "text", "-e", str(tcl)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if not tga.exists() or tga.stat().st_size == 0:
        raise RuntimeError(f"VMD failed to render {tga}")
    with Image.open(tga) as im:
        _trim_white(im, margin=20).save(png)
    return png


def _nn_bond_cutoff(positions: list[tuple[float, float, float]]) -> float:
    pts = np.asarray(positions, dtype=float)
    dists = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1)
    np.fill_diagonal(dists, np.inf)
    nn = float(np.median(np.min(dists, axis=1)))
    return max(2.6, min(4.2, nn * 1.28))


def build_vmd_gallery() -> Path:
    """Render 6 converged golden clusters via VMD TachyonInternal into a 2x3 gallery."""
    if not VMD_EXE.exists():
        raise RuntimeError(f"VMD executable missing: {VMD_EXE}")
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    vmd_tmp = (TMP_DIR / "vmd_tiles").resolve()
    vmd_tmp.mkdir(parents=True, exist_ok=True)

    specs = [
        ("na6", "(a) Na6 (s-block, M = 1)", (22.0, 25.0), False),
        ("al13_anion", "(b) Al13- (40e- superatom, M = 1)", (20.0, 35.0), False),
        ("fe4", "(c) Fe4 (3d high-spin, M = 13)", (24.0, 28.0), False),
        ("w_au12", "(d) W@Au12 (18e- endohedral, M = 1)", (18.0, 32.0), False),
        ("cu3ag3", "(e) Cu3Ag3 (bimetallic, M = 1)", (25.0, 15.0), False),
        ("al12cu", "(f) Al12Cu (M = 2, spin density ±0.0035 a.u.)", (22.0, 32.0), True),
    ]

    cube_path = (TMP_DIR / "spindensity.cub").resolve()
    tiles: list[tuple[str, Path]] = []
    for job_id, caption, rot_xy, use_cube in specs:
        res = parse_gaussian_log(GOLDEN_DIR / job_id / "job.log", job_id=job_id)
        geom = res.final_geometry
        assert geom is not None
        aligned = align_cluster_principal_axes(geom)
        cutoff = _nn_bond_cutoff(aligned.positions)
        dop_idx = (
            minority_atom_indices(geom.symbols)
            if use_cube
            else minority_atom_indices(aligned.symbols)
        )
        if len(set(geom.symbols)) > 1 and (not dop_idx or len(dop_idx) == len(geom.symbols)):
            # Bimetallic equal stoichiometry (e.g., 3 Cu + 3 Ag): highlight first element only
            src_syms = geom.symbols if use_cube else aligned.symbols
            dop_idx = [i for i, sym in enumerate(src_syms) if sym == src_syms[0]]

        xyz_file: Path | None = None
        if not (use_cube and cube_path.exists()):
            xyz_file = vmd_tmp / f"{job_id}.xyz"
            rows = [str(len(aligned.symbols)), aligned.label]
            for sym, (x, y, z) in zip(aligned.symbols, aligned.positions, strict=True):
                rows.append(f"{sym:4s} {x:12.6f} {y:12.6f} {z:12.6f}")
            xyz_file.write_text("\n".join(rows) + "\n", encoding="utf-8")

        png = _render_vmd_single(
            tag=job_id,
            xyz_path=xyz_file,
            cube_path=cube_path if (use_cube and cube_path.exists()) else None,
            bond_cutoff=cutoff,
            dopant_indices=dop_idx,
            rot_xy=rot_xy,
            isovalue=0.0035,
        )
        tiles.append((caption, png))

    # Assemble 2x3 gallery (2400 x 1620)
    cols, rows_n = 3, 2
    tile_w, tile_h = 780, 740
    header_h = 64
    gap = 20
    canvas = Image.new(
        "RGB",
        (cols * tile_w + (cols + 1) * gap, rows_n * tile_h + (rows_n + 1) * gap),
        (255, 255, 255),
    )
    draw = ImageDraw.Draw(canvas)
    f_cap = _load_font(28, bold=True)

    for idx, (caption, png_path) in enumerate(tiles):
        r, c = divmod(idx, cols)
        x0 = gap + c * (tile_w + gap)
        y0 = gap + r * (tile_h + gap)
        draw.rectangle([x0, y0, x0 + tile_w, y0 + tile_h], outline=(203, 213, 225), width=2)
        with Image.open(png_path) as raw_tile:
            fitted = _fit_tile(raw_tile, tile_w - 8, tile_h - header_h - 8)
        canvas.paste(fitted, (x0 + 4, y0 + 4))
        draw.text((x0 + 18, y0 + tile_h - header_h + 14), caption, fill=(15, 37, 87), font=f_cap)

    out = FIG_DIR / "fig2_golden_3d_vmd.png"
    canvas.save(out, dpi=(300, 300))
    return out


def _apply_origin_axis_style(gl: Any, *, x_title: str, y_title: str) -> None:
    gl.axis("x").title = x_title
    gl.axis("y").title = y_title
    gl.lt_exec(
        "layer.x.ticks=1; layer.y.ticks=1;"
        "layer.x2.showAxes=3; layer.y2.showAxes=3; layer.x2.ticks=1; layer.y2.ticks=1;"
        "xb.fsize=22; yl.fsize=22;"
        "layer.x.label.pt=20; layer.y.label.pt=20;"
        "layer.x.thickness=2; layer.y.thickness=2; layer.x2.thickness=2; layer.y2.thickness=2;"
    )


def _compose_side_by_side(
    left_png: Path,
    right_png: Path,
    out_png: Path,
    *,
    left_label: str = "(a)",
    right_label: str = "(b)",
) -> Path:
    with Image.open(left_png) as l_im, Image.open(right_png) as r_im:
        lw = _trim_white(l_im, margin=18)
        rw = _trim_white(r_im, margin=18)
    target_h = 1120
    lw_resized = lw.resize(
        (int(lw.width * target_h / lw.height), target_h), Image.Resampling.LANCZOS
    )
    rw_resized = rw.resize(
        (int(rw.width * target_h / rw.height), target_h), Image.Resampling.LANCZOS
    )
    gap = 36
    pad = 20
    canvas = Image.new(
        "RGB",
        (lw_resized.width + rw_resized.width + gap + 2 * pad, target_h + 2 * pad),
        (255, 255, 255),
    )
    canvas.paste(lw_resized, (pad, pad))
    canvas.paste(rw_resized, (pad + lw_resized.width + gap, pad))
    draw = ImageDraw.Draw(canvas)
    f_badge = _load_font(42, bold=True)
    draw.text((pad + 12, pad + 4), left_label, fill=(15, 37, 87), font=f_badge)
    draw.text(
        (pad + lw_resized.width + gap + 12, pad + 4), right_label, fill=(15, 37, 87), font=f_badge
    )
    canvas.save(out_png, dpi=(300, 300))
    return out_png


def build_origin_figures() -> list[Path]:
    """Drive Origin 2024b serially to export fig3, fig4, and fig5."""
    import originpro as op

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    opju_dir = (TMP_DIR / "origin_opju").resolve()
    raw_dir = (TMP_DIR / "origin_raw").resolve()
    opju_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    r_al = parse_gaussian_log(GOLDEN_DIR / "al12cu" / "job.log", job_id="Al12Cu")
    charges, spins = parse_charge_spin(
        (MWFN_DIR / "out_7.txt").read_text(encoding="utf-8")
        + "\n"
        + (MWFN_DIR / "out_15_spin.txt").read_text(encoding="utf-8")
    )
    r_al.charges = charges
    r_al.spins = spins
    pdos = parse_pdos(
        (MWFN_DIR / "out_10_exp.txt").read_text(encoding="utf-8"),
        MWFN_DIR / "DOS_curve.txt",
        ["Al", "Cu", "s", "p", "d"],
    )
    comps = parse_orb_comp((MWFN_DIR / "out_8_frontier.txt").read_text(encoding="utf-8"))

    # Collect 6 golden gaps for fig5
    gap_items: list[tuple[str, float, bool]] = []
    for jid, lbl, is_open in [
        ("w_au12", "W@Au12", False),
        ("al13_anion", "Al13-", False),
        ("cu3ag3", "Cu3Ag3", False),
        ("na6", "Na6", False),
        ("al12cu", "Al12Cu", True),
        ("fe4", "Fe4", True),
    ]:
        rr = parse_gaussian_log(GOLDEN_DIR / jid / "job.log", job_id=jid)
        g_ha = homo_lumo_gap_hartree(rr.mo_energies_hartree, rr.homo_indices)
        gap_items.append((lbl, round((g_ha or 0.0) * HA_TO_EV, 3), is_open))

    raw_paths: dict[str, Path] = {}
    op.set_show(False)
    try:
        # 1. Panel 3a: Al12Cu Spin-Polarized MO Levels
        op.new()
        wks_lvl = op.new_sheet("w", "LevelsData")
        col = 0
        occ_pairs: list[tuple[int, int]] = []
        virt_pairs: list[tuple[int, int]] = []
        centers = [0.35, 0.78]
        for ch_idx in range(2):
            cx = centers[ch_idx]
            h_idx = r_al.homo_indices[ch_idx]
            evs = [e * HA_TO_EV for e in r_al.mo_energies_hartree[ch_idx]]
            ox, oy, vx, vy = [], [], [], []
            for idx in range(max(0, h_idx - 8), min(len(evs), h_idx + 8)):
                e = evs[idx]
                x0, x1 = cx - 0.14, cx + 0.14
                if idx <= h_idx:
                    ox.extend([x0, x1, float("nan")])
                    oy.extend([e, e, float("nan")])
                else:
                    vx.extend([x0, x1, float("nan")])
                    vy.extend([e, e, float("nan")])
            wks_lvl.from_list(col, ox, f"X_occ_{ch_idx}")
            wks_lvl.from_list(col + 1, oy, "Occupied MO" if ch_idx == 0 else "")
            occ_pairs.append((col, col + 1))
            col += 2
            wks_lvl.from_list(col, vx, f"X_virt_{ch_idx}")
            wks_lvl.from_list(col + 1, vy, "Virtual MO" if ch_idx == 0 else "")
            virt_pairs.append((col, col + 1))
            col += 2

        g_lvl = op.new_graph(template="LINE")
        gl_lvl = g_lvl[0]
        for xc, yc in occ_pairs:
            p = gl_lvl.add_plot(wks_lvl, yc, xc)
            p.color = "#1e3a8a"
            p.set_int("width", 3)
        for xc, yc in virt_pairs:
            p = gl_lvl.add_plot(wks_lvl, yc, xc)
            p.color = "#ea580c"
            p.set_int("width", 2)
            p.set_int("style", 2)
        gl_lvl.set_xlim(0.08, 1.05)
        gl_lvl.set_ylim(-7.8, -1.7)
        _apply_origin_axis_style(
            gl_lvl,
            x_title="Spin Channel (left: alpha, right: beta)",
            y_title="Orbital Energy (eV)",
        )
        gl_lvl.lt_exec(
            "layer.x.inc=1; layer.x.from=0.08; layer.x.to=1.05; layer.x.showLabels=0;legend.show=0;"
        )
        l_a = gl_lvl.add_label("alpha channel", 0.35, -7.44)
        l_a.set_int("fsize", 16)
        l_b = gl_lvl.add_label("beta channel", 0.78, -7.44)
        l_b.set_int("fsize", 16)
        l_la = gl_lvl.add_label("LUMO -4.66", 0.35, -4.32)
        l_la.set_int("fsize", 13)
        l_ha = gl_lvl.add_label("HOMO -5.05", 0.35, -4.82)
        l_ha.set_int("fsize", 13)
        l_lb = gl_lvl.add_label("LUMO -4.71", 0.78, -4.32)
        l_lb.set_int("fsize", 13)
        l_hb = gl_lvl.add_label("HOMO -4.99", 0.78, -4.81)
        l_hb.set_int("fsize", 13)
        l_eg = gl_lvl.add_label("Overall Eg = 0.277 eV", 0.56, -1.96)
        l_eg.set_int("fsize", 16)

        raw_paths["levels"] = raw_dir / "fig3a_levels.png"
        g_lvl.save_fig(str(raw_paths["levels"]), type="png", width=1800)
        op.save(str(opju_dir / "fig3a_levels.opju"))

        # 2. Panel 3b: Al12Cu Multiwfn PDOS (zoomed [-15.5, 3.8] eV)
        op.new()
        wks_dos = op.new_sheet("w", "PDOSData")
        mask = [(-15.5 <= e <= 3.8) for e in pdos.energies_ev]
        e_sub = [e for e, m in zip(pdos.energies_ev, mask, strict=True) if m]
        tdos_sub = [v for v, m in zip(pdos.tdos_alpha, mask, strict=True) if m]
        al_sub = [v for v, m in zip(pdos.pdos_series["Al"], mask, strict=True) if m]
        cu_sub = [v for v, m in zip(pdos.pdos_series["Cu"], mask, strict=True) if m]
        p_sub = [v for v, m in zip(pdos.pdos_series["p"], mask, strict=True) if m]
        d_sub = [v for v, m in zip(pdos.pdos_series["d"], mask, strict=True) if m]

        wks_dos.from_list(0, e_sub, "Energy (eV)")
        wks_dos.from_list(1, tdos_sub, "TDOS")
        wks_dos.from_list(2, al_sub, "Al")
        wks_dos.from_list(3, cu_sub, "Cu")
        wks_dos.from_list(4, p_sub, "p")
        wks_dos.from_list(5, d_sub, "d")
        wks_dos.from_list(6, [-5.046, -5.046], "HOMO_X")
        wks_dos.from_list(7, [0.0, 0.88], "HOMO")

        g_dos = op.new_graph(template="LINE")
        gl_dos = g_dos[0]
        styles = [
            (1, "#0f172a", 3, 0),
            (2, "#2563eb", 2, 0),
            (3, "#dc2626", 2, 0),
            (4, "#16a34a", 2, 0),
            (5, "#9333ea", 2, 0),
            (7, "#475569", 2, 1),
        ]
        for yc, col_hex, lw, lstyle in styles:
            xcol = 6 if yc == 7 else 0
            p = gl_dos.add_plot(wks_dos, yc, xcol)
            p.color = col_hex
            p.set_int("width", lw)
            if lstyle:
                p.set_int("style", lstyle)

        gl_dos.set_xlim(-15.5, 3.8)
        gl_dos.set_ylim(-0.04, 0.92)
        _apply_origin_axis_style(gl_dos, x_title="Energy (eV)", y_title="DOS (states/eV)")
        gl_dos.lt_exec("layer.y.inc=0.2;")
        gl_dos.lt_exec("legend.fsize=15; legend.x=-12.6; legend.y=0.66;")
        raw_paths["pdos"] = raw_dir / "fig3b_pdos.png"
        g_dos.save_fig(str(raw_paths["pdos"]), type="png", width=1800)
        op.save(str(opju_dir / "fig3b_pdos.opju"))

        # 3. Panel 4a: Al12Cu Atomic Hirshfeld Spin Population
        op.new()
        wks_sp = op.new_sheet("w", "SpinData")
        labels_sp = [f"{i + 1}{sym}" for i, sym in enumerate(r_al.final_geometry.symbols)]  # type: ignore[union-attr]
        sp_vals = r_al.spins["hirshfeld"]
        cu_col = [sp_vals[0]] + [float("nan")] * (len(sp_vals) - 1)
        pos_al = [float("nan")] + [v if v >= 0 else float("nan") for v in sp_vals[1:]]
        neg_al = [float("nan")] + [v if v < 0 else float("nan") for v in sp_vals[1:]]

        wks_sp.from_list(0, labels_sp, "Atom")
        wks_sp.from_list(1, cu_col, "Cu dopant")
        wks_sp.from_list(2, pos_al, "Al (+)")
        wks_sp.from_list(3, neg_al, "Al (-)")

        g_sp = op.new_graph(template="COLUMN")
        gl_sp = g_sp[0]
        p_cu = gl_sp.add_plot(wks_sp, 1, 0, type=203)
        p_pos = gl_sp.add_plot(wks_sp, 2, 0, type=203)
        p_neg = gl_sp.add_plot(wks_sp, 3, 0, type=203)
        p_cu.color = "#dc2626"
        p_pos.color = "#1d4ed8"
        p_neg.color = "#0f766e"
        gl_sp.set_xlim(0.3, 13.7)
        gl_sp.set_ylim(-0.35, 0.37)
        _apply_origin_axis_style(
            gl_sp, x_title="Atomic Site (Al12Cu)", y_title="Hirshfeld Spin Population (e)"
        )
        gl_sp.lt_exec("layer.y.inc=0.1; layer.x.label.pt=15;")
        gl_sp.lt_exec("legend.fsize=15; legend.x=3.8; legend.y=-0.18;")
        note_fd = gl_sp.add_label("fD(Cu) = 3.91% | Net Spin = +1.000 e", 5.6, 0.315)
        note_fd.set_int("fsize", 15)

        raw_paths["spin"] = raw_dir / "fig4a_spin.png"
        g_sp.save_fig(str(raw_paths["spin"]), type="png", width=2000)
        op.save(str(opju_dir / "fig4a_spin.opju"))

        # 4. Panel 4b: Al12Cu Frontier MO Angular-Momentum Composition (cumulative stacked)
        op.new()
        wks_oc = op.new_sheet("w", "OrbComp")
        orb_names = [f"MO {c.mo_index} ({c.spin[0]})" for c in comps]
        s_v = [round(c.contributions.get("shell_s", 0.0), 2) for c in comps]
        p_v = [round(c.contributions.get("shell_p", 0.0), 2) for c in comps]
        d_v = [round(c.contributions.get("shell_d", 0.0), 2) for c in comps]
        wks_oc.from_list(0, orb_names, "Orbital")
        wks_oc.from_list(
            1, [round(a + b + c, 2) for a, b, c in zip(s_v, p_v, d_v, strict=True)], "d"
        )
        wks_oc.from_list(2, [round(a + b, 2) for a, b in zip(s_v, p_v, strict=True)], "p")
        wks_oc.from_list(3, s_v, "s")

        g_oc = op.new_graph(template="COLUMN")
        gl_oc = g_oc[0]
        oc_d = gl_oc.add_plot(wks_oc, 1, 0, type=203)
        oc_p = gl_oc.add_plot(wks_oc, 2, 0, type=203)
        oc_s = gl_oc.add_plot(wks_oc, 3, 0, type=203)
        oc_d.color = "#0f766e"
        oc_p.color = "#f97316"
        oc_s.color = "#1d4ed8"
        gl_oc.set_xlim(0.4, 4.6)
        gl_oc.set_ylim(0, 118)
        _apply_origin_axis_style(
            gl_oc, x_title="Frontier Molecular Orbital", y_title="Angular-Momentum Share (%)"
        )
        gl_oc.label("legend").text = r"\l(3) s   \l(2) p   \l(1) d"
        gl_oc.lt_exec("layer.y.inc=20;")
        gl_oc.lt_exec("legend.fsize=17; legend.x=2.5; legend.y=109;")
        raw_paths["orb_comp"] = raw_dir / "fig4b_orb_comp.png"
        g_oc.save_fig(str(raw_paths["orb_comp"]), type="png", width=2000)
        op.save(str(opju_dir / "fig4b_orb_comp.opju"))

        # 5. Fig 5: Cross-Periodic-Table HOMO-LUMO Gaps of Converged Golden Clusters
        op.new()
        wks_g = op.new_sheet("w", "GoldenGaps")
        g_labels = [it[0] for it in gap_items]
        closed_vals = [it[1] if not it[2] else float("nan") for it in gap_items]
        open_vals = [it[1] if it[2] else float("nan") for it in gap_items]
        wks_g.from_list(0, g_labels, "Cluster")
        wks_g.from_list(1, closed_vals, "Closed-shell (M=1)")
        wks_g.from_list(2, open_vals, "Open-shell (M>=2)")

        g_gap = op.new_graph(template="COLUMN")
        gl_gap = g_gap[0]
        pg_c = gl_gap.add_plot(wks_g, 1, 0, type=203)
        pg_o = gl_gap.add_plot(wks_g, 2, 0, type=203)
        pg_c.color = "#1d4ed8"
        pg_o.color = "#dc2626"
        gl_gap.set_xlim(0.4, 6.6)
        gl_gap.set_ylim(0, 3.85)
        _apply_origin_axis_style(
            gl_gap, x_title="Converged Golden Cluster", y_title="HOMO-LUMO Gap Eg (eV)"
        )
        gl_gap.lt_exec("layer.y.inc=0.5;")
        gl_gap.lt_exec("legend.fsize=17; legend.x=4.95; legend.y=3.15;")
        for idx, (_nm, val, _iso) in enumerate(gap_items, start=1):
            t = gl_gap.add_label(f"{val:.3f}", idx - 0.16, val + 0.18)
            t.set_int("fsize", 15)

        out_fig5 = FIG_DIR / "fig5_origin_golden_gaps.png"
        g_gap.save_fig(str(out_fig5.resolve()), type="png", width=2200)
        op.save(str(opju_dir / "fig5_golden_gaps.opju"))
    finally:
        op.exit()

    # Compose fig3 & fig4 side-by-side Origin composites
    out_fig3 = _compose_side_by_side(
        raw_paths["levels"],
        raw_paths["pdos"],
        FIG_DIR / "fig3_origin_al12cu_electronic.png",
        left_label="(a)",
        right_label="(b)",
    )
    out_fig4 = _compose_side_by_side(
        raw_paths["spin"],
        raw_paths["orb_comp"],
        FIG_DIR / "fig4_origin_al12cu_spin_orb.png",
        left_label="(a)",
        right_label="(b)",
    )
    with Image.open(FIG_DIR / "fig5_origin_golden_gaps.png") as g5:
        _trim_white(g5, margin=24).save(FIG_DIR / "fig5_origin_golden_gaps.png", dpi=(300, 300))

    return [out_fig3, out_fig4, FIG_DIR / "fig5_origin_golden_gaps.png"]


def build_ln_au5_origin_figure() -> Path:
    """Drive Origin 2024b to plot Ln@Au5 (Gd-Lu) electronic rigidity & 4f spin decoupling."""
    import originpro as op

    summary_path = REPO_ROOT / "paper" / "data" / "ln_au5_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(
            f"Missing {summary_path}; run `uv run python scripts/export_ln_au5_study.py` first."
        )
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = data["ground_states"]

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    opju_dir = (TMP_DIR / "origin_opju").resolve()
    raw_dir = (TMP_DIR / "origin_raw").resolve()
    opju_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    elems = [str(r["element"]) for r in rows]
    trivalent_set = {"Tb", "Dy", "Ho", "Er", "Tm", "Lu"}
    gap_tri = [float(r["gap_ev"]) if r["element"] in trivalent_set else float("nan") for r in rows]
    gap_anom = [
        float(r["gap_ev"]) if r["element"] not in trivalent_set else float("nan") for r in rows
    ]
    mu_tot = [float(r["mu_b"]) for r in rows]
    spin_ln = [float(r["spin_ln_effective"]) for r in rows]

    raw_gap = raw_dir / "fig6a_ln_gap.png"
    raw_spin = raw_dir / "fig6b_ln_spin.png"

    op.set_show(False)
    try:
        # Panel (a): HOMO-LUMO gap Eg (eV) highlighting trivalent 8e- rigidity vs Gd/Yb anomalies
        op.new()
        wks_gap = op.new_sheet("w", "LnGap")
        wks_gap.from_list(0, elems, "Lanthanide")
        wks_gap.from_list(1, gap_tri, "Trivalent 8e- (2.52-2.81 eV)")
        wks_gap.from_list(2, gap_anom, "Gd (4f7 5d1) / Yb2+ (7e-)")

        g_gap = op.new_graph(template="COLUMN")
        gl_gap = g_gap[0]
        p_tri = gl_gap.add_plot(wks_gap, 1, 0, type=203)
        p_anom = gl_gap.add_plot(wks_gap, 2, 0, type=203)
        p_tri.color = "#1d4ed8"
        p_anom.color = "#dc2626"
        gl_gap.set_xlim(0.3, 8.7)
        gl_gap.set_ylim(0, 3.88)
        _apply_origin_axis_style(
            gl_gap,
            x_title="Lanthanide Dopant in Ln@Au5",
            y_title="HOMO-LUMO Gap Eg (eV)",
        )
        gl_gap.lt_exec("layer.y.inc=0.5; legend.fsize=15; legend.x=4.55; legend.y=3.48;")
        for idx, r in enumerate(rows, start=1):
            val = float(r["gap_ev"])
            lbl = gl_gap.add_label(f"{val:.2f}", idx - 0.19, val + 0.21)
            lbl.set_int("fsize", 15)
        g_gap.save_fig(str(raw_gap), type="png", width=2000)
        op.save(str(opju_dir / "fig6a_ln_au5_gap.opju"))

        # Panel (b): Total Magnetic Moment vs Localized 4f Spin on Ln
        op.new()
        wks_sp = op.new_sheet("w", "LnSpin")
        wks_sp.from_list(0, elems, "Lanthanide")
        wks_sp.from_list(1, mu_tot, "Total moment (mu_B)")
        wks_sp.from_list(2, spin_ln, "Localized spin(Ln) (e)")

        g_sp = op.new_graph(template="LINE")
        gl_sp = g_sp[0]
        ps_tot = gl_sp.add_plot(wks_sp, 1, 0, type=202)
        ps_ln = gl_sp.add_plot(wks_sp, 2, 0, type=202)
        ps_tot.color = "#0f2557"
        ps_tot.set_int("width", 3)
        ps_tot.symbol_kind = 1
        ps_tot.symbol_size = 9
        ps_ln.color = "#dc2626"
        ps_ln.set_int("width", 2)
        ps_ln.symbol_kind = 2
        ps_ln.symbol_size = 9
        gl_sp.set_xlim(0.3, 8.7)
        gl_sp.set_ylim(-0.6, 9.4)
        _apply_origin_axis_style(
            gl_sp,
            x_title="Lanthanide Dopant in Ln@Au5",
            y_title="Spin / Magnetic Moment (mu_B or e)",
        )
        gl_sp.lt_exec("layer.y.inc=1; legend.fsize=15; legend.x=5.3; legend.y=7.9;")
        yb_note = gl_sp.add_label("Yb2+ (4f14): spin(Yb) = +0.18 e", 2.0, 0.75)
        yb_note.set_int("fsize", 14)
        g_sp.save_fig(str(raw_spin), type="png", width=2000)
        op.save(str(opju_dir / "fig6b_ln_au5_spin.opju"))
    finally:
        op.exit()

    return _compose_side_by_side(
        raw_gap,
        raw_spin,
        FIG_DIR / "fig_ln_au5_origin_rigidity.png",
        left_label="(a)",
        right_label="(b)",
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_http(url: str, timeout: float = 35.0) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=2) as resp:
                if int(resp.status) == 200:
                    return
        except Exception:
            time.sleep(0.35)
    raise TimeoutError(f"Timed out waiting for Streamlit at {url}")


def build_web_workbench_figure() -> Path:
    """Capture 2x HiDPI Chromium screenshots of redesigned Web UI Pages 1 & 4."""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    ui_tmp = (TMP_DIR / "ui_screenshots").resolve()
    ui_tmp.mkdir(parents=True, exist_ok=True)
    db_path = ui_tmp / "demo_ui.sqlite"
    if db_path.exists():
        db_path.unlink()

    store = JobStore(db_path)
    from qcai.core.models import ResearchRequest

    req = ResearchRequest(
        composition={"Al": 12, "Cu": 1},
        recipes=["stability", "electronic", "magnetism"],
        accuracy="standard",
    )
    plan = build_plan(req)
    pid = "proj_al12cu"
    store.upsert_project(
        ProjectRecord(
            project_id=pid,
            title="Al12Cu_Cluster_Study",
            request_json=req.model_dump_json(),
            plan_json=plan.model_dump_json(),
            status="done",
        )
    )
    res_al = parse_gaussian_log(GOLDEN_DIR / "al12cu" / "job.log", job_id="al12cu_gs")
    res_file = ui_tmp / "al12cu_gs.json"
    res_file.write_text(res_al.model_dump_json(indent=2), encoding="utf-8")
    store.upsert_job(
        JobRecord(
            job_id="al12cu_gs",
            project_id=pid,
            stage="S4_refine",
            cluster_label="Al12Cu",
            charge=0,
            multiplicity=2,
            level="PBE0/def2-TZVP",
            status="done",
            result_path=str(res_file),
        )
    )

    port = _free_port()
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["QCAI_DB_PATH"] = str(db_path)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(REPO_ROOT / "web" / "app.py"),
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    p1_img = ui_tmp / "page1.png"
    p4_img = ui_tmp / "page4.png"
    try:
        _wait_for_http(url, timeout=40.0)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 840}, device_scale_factor=2)
            page.goto(url, wait_until="networkidle")
            page.get_by_text("1. 新建团簇研究").wait_for(timeout=15000)
            page.get_by_role("tab", name="🤖 AI 一句话全自动规划（推荐）").wait_for(timeout=15000)
            page.get_by_role("button", name="🚀 自动规划并生成方案书").wait_for(timeout=15000)
            page.get_by_text("AI 仅负责将研究语义转化为结构化参数").wait_for(timeout=15000)
            time.sleep(1.5)
            page.screenshot(path=str(p1_img), full_page=False)

            page.get_by_role("link", name="4. 结果与报告").click()
            page.get_by_text("4. 结果查看与出版级导出").wait_for(timeout=15000)
            page.get_by_text("基态体系").wait_for(timeout=15000)
            page.get_by_role("tab", name="📈 2D 图表与 Origin 出图").click()
            page.get_by_role("button", name="Origin 2024b 出版级 2D 出图").wait_for(timeout=15000)
            time.sleep(2.0)
            page.screenshot(path=str(p4_img), full_page=False)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    with Image.open(p1_img) as im1, Image.open(p4_img) as im4:
        w1, h1 = im1.size
        target_w = 1320
        th1 = int(h1 * target_w / w1)
        r1 = im1.resize((target_w, th1), Image.Resampling.LANCZOS)
        r4 = im4.resize((target_w, th1), Image.Resampling.LANCZOS)

    gap = 28
    pad = 24
    cap_h = 56
    canvas = Image.new(
        "RGB", (2 * target_w + gap + 2 * pad, th1 + cap_h + 2 * pad), (255, 255, 255)
    )
    canvas.paste(r1, (pad, pad))
    canvas.paste(r4, (pad + target_w + gap, pad))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([pad, pad, pad + target_w, pad + th1], outline=(148, 163, 184), width=2)
    draw.rectangle(
        [pad + target_w + gap, pad, pad + 2 * target_w + gap, pad + th1],
        outline=(148, 163, 184),
        width=2,
    )
    f_cap = _load_font(28, bold=True)
    draw.text(
        (pad, pad + th1 + 12),
        "(a) 新建团簇研究（AI 一句话全自动规划 + 双页签切换）",
        fill=(15, 37, 87),
        font=f_cap,
    )
    draw.text(
        (pad + target_w + gap, pad + th1 + 12),
        "(b) 结果工作台（基态指标卡片 + 2D/3D/AI 多页签交互）",
        fill=(15, 37, 87),
        font=f_cap,
    )
    out = FIG_DIR / "fig6_web_workbench.png"
    canvas.save(out, dpi=(300, 300))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build all figures for QuantumChem AI paper.")
    parser.add_argument(
        "--stage",
        choices=["all", "arch", "vmd", "origin", "ln_au5", "ui"],
        default="all",
    )
    args = parser.parse_args(argv)
    if args.stage in ("all", "arch"):
        print("ARCH:", build_architecture_svg())
    if args.stage in ("all", "vmd"):
        print("VMD:", build_vmd_gallery())
    if args.stage in ("all", "origin"):
        print("ORIGIN:", build_origin_figures())
    if args.stage in ("all", "origin", "ln_au5"):
        print("LN_AU5:", build_ln_au5_origin_figure())
    if args.stage in ("all", "ui"):
        print("UI:", build_web_workbench_figure())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

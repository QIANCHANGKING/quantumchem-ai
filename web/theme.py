"""Unified scientific UI theme, sidebar status widget, and workflow stepper."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from qcai import __version__
from qcai.launcher import get_runtime_status, stop_web_assistant
from web.state import get_db_path, get_store, has_deepseek_key, load_app_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = REPO_ROOT / "assets"

WORKFLOW_STEPS: tuple[tuple[str, str], ...] = (
    ("1", "新建研究"),
    ("2", "方案确认"),
    ("3", "运行看板"),
    ("4", "结果与报告"),
)


def inject_global_theme() -> None:
    """Inject cohesive scientific workbench styling into the Streamlit app."""
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #f8fafc;
        }
        .block-container {
            padding-top: 1.1rem;
            padding-bottom: 2.2rem;
            max-width: 1320px;
        }
        .qcai-hero {
            background: linear-gradient(135deg, #0f2557 0%, #1e40af 60%, #0284c7 100%);
            color: #ffffff;
            padding: 1.05rem 1.45rem;
            border-radius: 14px;
            margin-bottom: 0.85rem;
            box-shadow: 0 8px 24px rgba(15, 37, 87, 0.14);
        }
        .qcai-hero h2 {
            color: #ffffff !important;
            margin: 0 0 0.25rem 0 !important;
            font-size: 1.5rem !important;
            font-weight: 700 !important;
            letter-spacing: -0.01em;
        }
        .qcai-hero p {
            color: #dbeafe;
            margin: 0;
            font-size: 0.92rem;
        }
        .qcai-stepper {
            display: flex;
            gap: 0.5rem;
            align-items: center;
            margin: 0 0 0.85rem 0;
            flex-wrap: wrap;
        }
        .qcai-step {
            flex: 1 1 140px;
            padding: 0.45rem 0.85rem;
            border-radius: 10px;
            border: 1px solid #e2e8f0;
            background: #ffffff;
            color: #64748b;
            font-size: 0.86rem;
            font-weight: 500;
            text-align: center;
        }
        .qcai-step.active {
            border-color: #1e40af;
            background: #eff6ff;
            color: #1e3a8a;
            font-weight: 700;
            box-shadow: 0 2px 8px rgba(30, 64, 175, 0.12);
        }
        .qcai-step.done {
            border-color: #bbf7d0;
            background: #f0fdf4;
            color: #166534;
        }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 0.7rem 0.9rem;
            box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
        }
        div[data-testid="stMetricLabel"] {
            font-size: 0.80rem !important;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1.25rem !important;
            line-height: 1.3 !important;
            white-space: nowrap !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 12px !important;
            background: #ffffff;
            box-shadow: 0 1px 6px rgba(15, 23, 42, 0.04);
        }
        div.stButton > button {
            border-radius: 10px;
            font-weight: 500;
            transition: all 0.15s ease;
        }
        .qcai-pill {
            display: inline-block;
            padding: 0.16rem 0.55rem;
            border-radius: 999px;
            font-size: 0.76rem;
            font-weight: 600;
            margin-right: 0.35rem;
        }
        .qcai-pill-ok { background: #dcfce7; color: #166534; }
        .qcai-pill-warn { background: #fef3c7; color: #92400e; }
        .qcai-pill-info { background: #dbeafe; color: #1e40af; }
        .qcai-sidebar-card {
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 0.75rem 0.85rem;
            margin-top: 0.6rem;
            font-size: 0.82rem;
            color: #334155;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_hero(title: str, subtitle: str, *, active_step: int | None = None) -> None:
    """Render a branded page header and optional 4-step workflow progress indicator."""
    st.markdown(
        f'<div class="qcai-hero"><h2>{title}</h2><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )
    if active_step is not None:
        items: list[str] = []
        for idx, (_num, label) in enumerate(WORKFLOW_STEPS, start=1):
            cls = "active" if idx == active_step else ("done" if idx < active_step else "")
            prefix = "✓" if idx < active_step else "①②③④"[idx - 1]
            items.append(f'<div class="qcai-step {cls}">{prefix} {label}</div>')
        st.markdown(f'<div class="qcai-stepper">{"".join(items)}</div>', unsafe_allow_html=True)


def render_sidebar_status() -> None:
    """Render persistent brand header and live readiness card in the left sidebar."""
    with st.sidebar:
        logo_png = ASSETS_DIR / "qcai_icon.png"
        col_logo, col_txt = st.columns([1, 3])
        if logo_png.exists():
            col_logo.image(str(logo_png), width=46)
        col_txt.markdown(
            f"**QuantumChem AI**<br><span style='font-size:0.78rem;color:#64748b;'>"
            f"团簇量化学研平台 v{__version__}</span>",
            unsafe_allow_html=True,
        )

        settings = load_app_settings()
        ds_ok = has_deepseek_key(settings)
        ssh_ok = bool(settings.ssh.host)
        try:
            proj_count = len(get_store().list_projects())
        except Exception:
            proj_count = 0

        ds_pill = (
            '<span class="qcai-pill qcai-pill-ok">AI 已就绪</span>'
            if ds_ok
            else '<span class="qcai-pill qcai-pill-warn">AI 未配 Key</span>'
        )
        ssh_pill = (
            '<span class="qcai-pill qcai-pill-info">集群已配置</span>'
            if ssh_ok
            else '<span class="qcai-pill qcai-pill-warn">离线模式</span>'
        )
        st.markdown(
            f'<div class="qcai-sidebar-card">'
            f'<div style="margin-bottom:0.4rem;">{ds_pill}{ssh_pill}</div>'
            f"<div>模型：<code>{settings.deepseek.model or 'deepseek-chat'}</code></div>"
            f"<div>本地项目数：<b>{proj_count}</b></div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        rt = get_runtime_status(get_db_path())
        if rt.get("running"):
            st.caption(f"运行模式：`{rt.get('mode', 'web')}` · 端口 `{rt.get('port', 8501)}`")
            if st.button("🛑 停止后台服务", use_container_width=True, key="sb_stop_svc"):
                stop_web_assistant(get_db_path(), include_orphans=True)
                st.toast("已发送停止信号，可关闭当前窗口。")

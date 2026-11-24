"""QuantumChem AI Streamlit multipage application entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from web.theme import ASSETS_DIR, inject_global_theme, render_sidebar_status  # noqa: E402

_icon_path = ASSETS_DIR / "qcai_icon.png"
st.set_page_config(
    page_title="QuantumChem AI 团簇量子化学助手",
    page_icon=str(_icon_path) if _icon_path.exists() else "⚛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_global_theme()

pages = [
    st.Page("pages/new_research.py", title="1. 新建研究", icon="🧪", default=True),
    st.Page("pages/plan_review.py", title="2. 方案书", icon="📋"),
    st.Page("pages/dashboard.py", title="3. 运行看板", icon="⚙️"),
    st.Page("pages/results.py", title="4. 结果与报告", icon="📊"),
    st.Page("pages/single_file_tools.py", title="5. 单文件工具", icon="🧰"),
    st.Page("pages/settings_page.py", title="6. 设置", icon="🔧"),
]

nav = st.navigation(pages)
render_sidebar_status()
nav.run()

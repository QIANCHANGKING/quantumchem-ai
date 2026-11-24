"""Page 2: Plan Review, Structured Decision Table, Overrides, and Run Confirmation."""

from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st

from qcai.core.models import CalcPlan, ResearchRequest
from qcai.pipeline import ProjectRecord
from qcai.planner import build_plan, format_plan_markdown
from web.state import get_store
from web.theme import render_page_hero


def render_plan_review_page() -> None:
    render_page_hero(
        "2. 计算方案书与决策覆盖",
        "每项理论方法、基组/ECP 与多重度均附带物理规则依据和文献来源，确认无误后方可提交执行。",
        active_step=2,
    )

    req_raw = st.session_state.get("pending_request")
    plan_raw = st.session_state.get("pending_plan")
    if not req_raw or not plan_raw:
        st.info("暂无待确认方案书，请先在「1. 新建研究」页面配置体系与目标。")
        st.page_link("pages/new_research.py", label="返回新建研究页面", icon="🧪")
        return

    req = ResearchRequest.model_validate(req_raw)
    plan = CalcPlan.model_validate(plan_raw)

    if nl_src := st.session_state.get("pending_nl_source"):
        b_col1, b_col2 = st.columns([3.2, 1.1])
        b_col1.success(f"✨ 已根据自然语言需求全自动生成方案书：{nl_src}")
        if b_col2.button("← 返回重新规划", use_container_width=True, key="btn_back_new_res"):
            st.switch_page("pages/new_research.py")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("预估总作业数", plan.estimated_jobs)
    c2.metric("预估计算量 (core·h)", f"{plan.estimated_core_hours:.2f}")
    c3.metric("规划执行阶段", len(plan.stages))
    c4.metric("自动规则决策数", len(plan.decisions))

    tab_plan, tab_override = st.tabs(["📋 方案书与决策明细", "🎛️ 参数覆盖微调"])

    with tab_plan:
        if plan.decisions:
            dec_rows = [
                {
                    "决策项": d.key,
                    "取值": str(d.value),
                    "规则依据": d.reason,
                    "规则来源": d.source_rule or "-",
                    "人工覆盖": "是" if d.overridden else "否",
                }
                for d in plan.decisions
            ]
            with st.expander("查看结构化决策与文献追溯表", expanded=True):
                st.dataframe(pd.DataFrame(dec_rows), use_container_width=True, hide_index=True)

        md_text = format_plan_markdown(plan)
        with st.container(border=True):
            st.markdown(md_text)
        st.download_button(
            "下载计算方案书 (Markdown)",
            data=md_text.encode("utf-8"),
            file_name="research_plan.md",
            mime="text/markdown",
        )

    with tab_override:
        with st.form("overrides_form"):
            cur_k = next(
                (int(d.value) for d in reversed(plan.decisions) if d.key == "candidate_k"), 8
            )
            cur_scf = next(
                (str(d.value) for d in reversed(plan.decisions) if d.key == "scf_strategy"),
                "default",
            )
            cur_nosymm = next(
                (bool(d.value) for d in reversed(plan.decisions) if d.key == "nosymm"),
                True,
            )

            fc1, fc2 = st.columns(2)
            new_k = int(
                fc1.number_input("候选异构体保留数 K", min_value=1, max_value=30, value=cur_k)
            )
            new_scf = fc2.selectbox(
                "SCF 收敛策略",
                options=["default", "robust"],
                index=0 if cur_scf == "default" else 1,
            )
            new_nosymm = st.checkbox("关闭对称性约束 (nosymm)", value=cur_nosymm)
            proj_title = st.text_input(
                "项目名称",
                value=st.session_state.get(
                    "pending_proj_title", f"Cluster_{'_'.join(req.composition.keys())}"
                ),
            )

            if st.form_submit_button("应用覆盖并更新方案书", use_container_width=True):
                overrides = dict(req.overrides)
                if new_k != cur_k:
                    overrides["candidate_k"] = new_k
                if new_scf != cur_scf:
                    overrides["scf_strategy"] = new_scf
                if new_nosymm != cur_nosymm:
                    overrides["nosymm"] = new_nosymm
                req = req.model_copy(update={"overrides": overrides})
                plan = build_plan(req)
                st.session_state["pending_proj_title"] = proj_title
                st.session_state["pending_request"] = req.model_dump()
                st.session_state["pending_plan"] = plan.model_dump()
                st.rerun()

    st.divider()
    default_title = st.session_state.get(
        "pending_proj_title", f"Cluster_{'_'.join(req.composition.keys())}"
    )
    if st.button(
        "确认方案并提交到运行队列",
        type="primary",
        use_container_width=True,
        key="btn_confirm_run",
    ):
        store = get_store()
        pid = f"proj_{uuid.uuid4().hex[:8]}"
        store.upsert_project(
            ProjectRecord(
                project_id=pid,
                title=default_title or pid,
                request_json=req.model_dump_json(),
                plan_json=plan.model_dump_json(),
                status="running",
            )
        )
        st.session_state["active_project_id"] = pid
        st.success(f"项目 {pid} 已创建并进入运行队列！请前往「运行看板」查看进度。")

    if st.session_state.get("active_project_id"):
        st.page_link(
            "pages/dashboard.py",
            label="下一步：进入实时调度进度看板 →",
            icon="⚙️",
            use_container_width=True,
        )


render_plan_review_page()

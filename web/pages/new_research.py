"""Page 1: New Research (One-Shot AI NL-to-Plan Automation & Manual Periodic-Table Tab)."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

import streamlit as st
from ase.io import read as ase_read

from qcai.ai import ParsedIntent, auto_plan_from_natural_language
from qcai.core.models import Cluster, ResearchRequest
from qcai.pipeline import ProjectRecord
from qcai.planner import build_plan
from web.state import (
    LANTHANOIDS,
    PERIODIC_ROWS,
    get_deepseek_key,
    get_store,
    has_deepseek_key,
    load_app_settings,
)
from web.theme import render_page_hero

RECIPE_OPTIONS = {
    "stability": "结构与稳定性（基态 / Eb / Δ₂E / 碎裂 / 掺杂）",
    "electronic": "电子结构（能级 / 能隙 / TDOS / 价电子计数）",
    "magnetism": "磁性与自旋（自旋阶梯 / 磁矩 / 自旋布居 / <S²>）",
    "pes": "光电子能谱对比（VDE / ADE）",
    "ionization": "电离能 / 电子亲和能（VIP / VEA）",
    "size_evolution": "尺寸演化（n = a…b 性质曲线）",
}

ACCURACY_LABELS = {
    "fast": "快速",
    "standard": "标准（默认）",
    "high": "高精度",
}

NL_EXAMPLES = [
    ("Al₆–₁₃Ni 掺杂演化", "研究 Al6-13Ni 团簇的稳定性和磁性，标准精度，预算 12 小时"),
    ("W@Au₁₂ 超原子", "高精度计算 W@Au12 内嵌团簇的电子结构和超原子闭壳层性质"),
    ("Fe₄ 自旋阶梯", "计算 Fe4 团簇的磁性与自旋态分布，标准精度"),
    ("重镧系超原子（多轮/推荐示例）", "重镧系内嵌金五环超原子中的“电子结构刚性”"),
]


def _format_formula(comp: dict[str, int | tuple[int, int]]) -> str:
    parts: list[str] = []
    for sym, cnt in comp.items():
        if isinstance(cnt, tuple):
            parts.append(f"{sym}{cnt[0]}–{cnt[1]}")
        elif cnt == 1:
            parts.append(sym)
        else:
            parts.append(f"{sym}{cnt}")
    return "".join(parts)


def _format_charges(charges: Any) -> str:
    if charges == "auto":
        return "自动推导"
    if isinstance(charges, list):
        return ", ".join(f"{int(q):+d}" if int(q) != 0 else "0" for q in charges)
    return str(charges)


def _commit_plan_and_open_review(
    req: ResearchRequest,
    *,
    title: str | None = None,
    nl_source: str | None = None,
) -> None:
    """Build deterministic CalcPlan, store in session state, and jump directly to Page 2."""
    plan = build_plan(req)
    st.session_state["pending_request"] = req.model_dump()
    st.session_state["pending_plan"] = plan.model_dump()
    if title:
        st.session_state["pending_proj_title"] = title
    else:
        st.session_state.pop("pending_proj_title", None)
    if nl_source:
        st.session_state["pending_nl_source"] = nl_source
    else:
        st.session_state.pop("pending_nl_source", None)
    st.switch_page("pages/plan_review.py")


def _clear_nl_dialogue() -> None:
    for k in ("nl_chat_history", "nl_last_intent", "nl_followup_input"):
        st.session_state.pop(k, None)


def _batch_create_proposals(proposals: list[Any], *, nl_source: str) -> list[tuple[str, str]]:
    """Build deterministic CalcPlans for a list of proposals and enqueue all projects."""
    del nl_source
    store = get_store()
    created: list[tuple[str, str]] = []
    for prop in proposals:
        plan = build_plan(prop.request)
        pid = f"proj_{uuid.uuid4().hex[:8]}"
        title = (prop.title or "").strip() or _format_formula(prop.request.composition)
        store.upsert_project(
            ProjectRecord(
                project_id=pid,
                title=title,
                request_json=prop.request.model_dump_json(),
                plan_json=plan.model_dump_json(),
                status="running",
            )
        )
        created.append((pid, title))
    if created:
        st.session_state["active_project_id"] = created[-1][0]
    return created


def _render_ai_tab() -> None:
    with st.container(border=True):
        st.subheader("🤖 自然语言一句话直达计算方案书（DeepSeek AI + 规则引擎）")
        st.caption(
            "直接用自然语言描述目标体系与科学问题，系统自动完成意图理解、规则推理与方案书生成并跳转审核；"
            "若研究对象指向一类元素或需要明确细节，AI 会同步生成可直接点击采用的推荐方案并支持一句话追问。"
        )

        ex_cols = st.columns(len(NL_EXAMPLES))
        for col, (label, prompt_text) in zip(ex_cols, NL_EXAMPLES, strict=True):
            if col.button(f"示例：{label}", use_container_width=True, key=f"ex_{label}"):
                st.session_state["nl_research_input"] = prompt_text
                _clear_nl_dialogue()

        nl_prompt = st.text_area(
            "用中文（或英文）描述你的团簇研究需求",
            key="nl_research_input",
            height=88,
            placeholder="例如：研究 Al6-13Ni 的稳定性和磁性，预算 12 小时；或：重镧系内嵌金五环超原子中的电子结构刚性",
        )

        c_ai_btn, c_ai_hint = st.columns([1.6, 3.0])
        if c_ai_btn.button(
            "🚀 自动规划并生成方案书",
            type="primary",
            disabled=not bool(nl_prompt.strip()),
            use_container_width=True,
            key="btn_ai_auto_plan",
        ):
            if not has_deepseek_key(load_app_settings()):
                st.warning(
                    "尚未检测到 DeepSeek API Key，请先在「6. 设置」配置，或切换右侧「手动精细配置」标签页。"
                )
                st.page_link(
                    "pages/settings_page.py",
                    label="前往「6. 设置」配置 DeepSeek API Key →",
                    icon="🔧",
                )
            else:
                with st.spinner("正在调用 DeepSeek 解析意图并由确定性规则引擎生成方案书..."):
                    try:
                        outcome = auto_plan_from_natural_language(
                            nl_prompt.strip(),
                            api_key=get_deepseek_key(),
                        )
                        if outcome.plan is not None and outcome.intent.request is not None:
                            _clear_nl_dialogue()
                            _commit_plan_and_open_review(
                                outcome.intent.request,
                                title=outcome.project_title,
                                nl_source=nl_prompt.strip(),
                            )
                        else:
                            q_txt = (
                                outcome.intent.clarification_question
                                or "请进一步明确具体元素符号或原子数范围，或直接采用下方 AI 推荐方案。"
                            )
                            st.session_state["nl_chat_history"] = [
                                ("user", nl_prompt.strip()),
                                ("assistant", q_txt),
                            ]
                            st.session_state["nl_last_intent"] = outcome.intent.model_dump()
                            st.rerun()
                    except Exception as exc:
                        st.error(f"自然语言自动规划失败：{exc}")

        c_ai_hint.caption(
            "AI 仅负责将研究语义转化为结构化参数并提出可选推荐，全部泛函、基组/ECP、自旋多重度与物理量均由确定性规则引擎严格生成。"
        )

    if batch_created := st.session_state.get("last_batch_created"):
        with st.container(border=True):
            summary_lines = "\n".join(f"- **{title}** (`{pid}`)" for pid, title in batch_created)
            st.success(
                f"已批量创建并提交 {len(batch_created)} 个计算项目到运行队列：\n\n{summary_lines}"
            )
            bc1, bc2 = st.columns([2.2, 1.0])
            bc1.page_link(
                "pages/dashboard.py",
                label="前往「3. 运行看板」查看全部批量任务进度 →",
                icon="⚙️",
                use_container_width=True,
            )
            if bc2.button("关闭此提示", use_container_width=True, key="btn_dismiss_batch_banner"):
                st.session_state.pop("last_batch_created", None)
                st.rerun()

    history_raw = st.session_state.get("nl_chat_history")
    last_intent_raw = st.session_state.get("nl_last_intent")
    if history_raw or last_intent_raw:
        history: list[tuple[str, str]] = [(str(r), str(c)) for r, c in (history_raw or [])]
        last_intent = ParsedIntent.model_validate(last_intent_raw) if last_intent_raw else None
        first_user = next((c for r, c in history if r == "user"), nl_prompt.strip())

        with st.container(border=True):
            st.subheader("💬 多轮澄清与 AI 推荐可执行方案")
            for role, content in history:
                with st.chat_message("user" if role == "user" else "assistant"):
                    st.markdown(content)

            if last_intent is not None and last_intent.suggested_proposals:
                props = last_intent.suggested_proposals[:10]
                st.markdown(
                    "**⚡ AI 拟定的可直接执行方案（点击任意一项立即自动生成方案书并跳转审核）：**"
                )
                if len(props) >= 2:
                    if st.button(
                        f"🚀 一键批量生成并提交全部 {len(props)} 个方案到运行队列",
                        type="primary",
                        use_container_width=True,
                        key="btn_batch_submit_proposals",
                    ):
                        try:
                            created = _batch_create_proposals(props, nl_source=first_user)
                            st.session_state["last_batch_created"] = created
                            _clear_nl_dialogue()
                            st.rerun()
                        except Exception as exc:
                            st.error(f"批量创建方案失败：{exc}")

                for row_start in range(0, len(props), 3):
                    row_props = props[row_start : row_start + 3]
                    prop_cols = st.columns(len(row_props))
                    for offset, (col, prop) in enumerate(zip(prop_cols, row_props, strict=True)):
                        idx = row_start + offset
                        with col, st.container(border=True):
                            st.markdown(f"**{prop.title}**")
                            goal_names = "、".join(
                                RECIPE_OPTIONS.get(r, r).split("（", 1)[0]
                                for r in prop.request.recipes
                            )
                            st.caption(
                                f"体系：`{_format_formula(prop.request.composition)}` · "
                                f"电荷：`{_format_charges(prop.request.charges)}` · "
                                f"精度：{ACCURACY_LABELS.get(prop.request.accuracy, prop.request.accuracy)}"
                            )
                            st.caption(f"目标：{goal_names}")
                            st.write(prop.rationale)
                            if st.button(
                                "⚡ 采用此方案并直达方案书",
                                type="primary",
                                use_container_width=True,
                                key=f"adopt_proposal_{idx}",
                            ):
                                try:
                                    _clear_nl_dialogue()
                                    _commit_plan_and_open_review(
                                        prop.request,
                                        title=prop.title,
                                        nl_source=f"{first_user} → 采用 AI 推荐方案：{prop.title}",
                                    )
                                except Exception as exc:
                                    st.error(f"采用方案失败：{exc}")

            st.divider()
            followup = st.text_input(
                "或继续补充一句细节（例如具体元素或尺寸），AI 立即自动生成方案书",
                key="nl_followup_input",
                placeholder="例如：就选 Lu@Au5，中性；或：对比 Dy@Au5 和 Lu@Au5",
            )
            f_c1, f_c2 = st.columns([2.2, 1.0])
            if f_c1.button(
                "✨ 发送补充并生成方案书",
                type="primary",
                disabled=not bool(followup.strip()),
                use_container_width=True,
                key="btn_ai_followup",
            ):
                if not has_deepseek_key(load_app_settings()):
                    st.warning("请先在「6. 设置」页面配置 DeepSeek API Key。")
                else:
                    with st.spinner("正在整合上下文并生成计算方案书..."):
                        try:
                            outcome = auto_plan_from_natural_language(
                                followup.strip(),
                                history=history,
                                api_key=get_deepseek_key(),
                            )
                            if outcome.plan is not None and outcome.intent.request is not None:
                                combined_src = f"{first_user}（补充：{followup.strip()}）"
                                _clear_nl_dialogue()
                                _commit_plan_and_open_review(
                                    outcome.intent.request,
                                    title=outcome.project_title,
                                    nl_source=combined_src,
                                )
                            else:
                                q_next = (
                                    outcome.intent.clarification_question
                                    or "请再明确具体元素符号或原子数范围，或直接采用上方推荐方案。"
                                )
                                history.append(("user", followup.strip()))
                                history.append(("assistant", q_next))
                                st.session_state["nl_chat_history"] = history
                                st.session_state["nl_last_intent"] = outcome.intent.model_dump()
                                st.session_state.pop("nl_followup_input", None)
                                st.rerun()
                        except Exception as exc:
                            st.error(f"补充规划失败：{exc}")
            if f_c2.button(
                "🔄 清空对话重新规划",
                use_container_width=True,
                key="btn_ai_reset",
            ):
                _clear_nl_dialogue()
                st.rerun()


def _render_manual_tab() -> None:
    if "chosen_elements_ms" not in st.session_state:
        st.session_state["chosen_elements_ms"] = ["Al", "Ni"]

    all_elements = [s for row in PERIODIC_ROWS for s in row if s] + LANTHANOIDS

    with st.container(border=True):
        st.subheader("⚛️ 体系组成与电荷配置")
        selected: list[str] = list(st.session_state["chosen_elements_ms"])

        with st.expander("展开交互式元素周期表点选（覆盖 H–Rn 与镧系）", expanded=False):
            for r_idx, row in enumerate(PERIODIC_ROWS):
                cols = st.columns(18)
                for c_idx, sym in enumerate(row):
                    if sym is None:
                        continue
                    is_sel = sym in selected
                    btn_lbl = f"✓{sym}" if is_sel else sym
                    if cols[c_idx].button(btn_lbl, key=f"pt_{r_idx}_{c_idx}_{sym}"):
                        if is_sel and len(selected) > 1:
                            selected.remove(sym)
                        elif not is_sel:
                            selected.append(sym)
                        st.session_state["chosen_elements_ms"] = selected
                        st.rerun()
            st.caption("镧系元素（4f 强关联体系，规则引擎会自动附加复核提示）：")
            ln_cols = st.columns(14)
            for idx, sym in enumerate(LANTHANOIDS):
                is_sel = sym in selected
                if ln_cols[idx].button(f"✓{sym}" if is_sel else sym, key=f"pt_ln_{sym}"):
                    if is_sel and len(selected) > 1:
                        selected.remove(sym)
                    elif not is_sel:
                        selected.append(sym)
                    st.session_state["chosen_elements_ms"] = selected
                    st.rerun()

        chosen = st.multiselect(
            "已选元素",
            options=all_elements,
            key="chosen_elements_ms",
        )
        selected = list(chosen)

        st.markdown("**原子数 / 尺寸范围**")
        composition: dict[str, int | tuple[int, int]] = {}
        comp_cols = st.columns(max(1, len(selected)))
        for i, el in enumerate(selected):
            with comp_cols[i]:
                use_range = st.checkbox(f"{el} 使用范围", key=f"range_{el}")
                if use_range:
                    lo = int(
                        st.number_input(
                            f"{el} 最小", min_value=1, max_value=40, value=6, key=f"lo_{el}"
                        )
                    )
                    hi = int(
                        st.number_input(
                            f"{el} 最大",
                            min_value=lo,
                            max_value=40,
                            value=max(lo, 13),
                            key=f"hi_{el}",
                        )
                    )
                    composition[el] = (lo, hi)
                else:
                    cnt = int(
                        st.number_input(
                            f"{el} 原子数",
                            min_value=1,
                            max_value=40,
                            value=4 if i == 0 else 1,
                            key=f"cnt_{el}",
                        )
                    )
                    composition[el] = cnt

    with st.container(border=True):
        st.subheader("🎯 研究目标、计算精度与初始结构")
        c1, c2, c3, c4 = st.columns([2.2, 1.1, 1.1, 1.1])
        with c1:
            recipes = st.multiselect(
                "研究目标",
                options=list(RECIPE_OPTIONS.keys()),
                default=["stability"],
                format_func=lambda k: RECIPE_OPTIONS[k],
                key="recipes_ms",
            )
        with c2:
            accuracy = st.selectbox(
                "精度档位",
                options=["fast", "standard", "high"],
                index=1,
                format_func=lambda a: ACCURACY_LABELS[a],
                key="accuracy_sb",
            )
        with c3:
            charge_mode = st.selectbox(
                "电荷态",
                options=["auto", "0", "-1", "+1"],
                index=0,
                format_func=lambda q: {
                    "auto": "自动推导",
                    "0": "中性 (0)",
                    "-1": "阴离子 (-1)",
                    "+1": "阳离子 (+1)",
                }[q],
                key="charge_mode_sb",
            )
        with c4:
            budget_h = st.number_input(
                "时间预算（小时，0 不限）",
                min_value=0.0,
                max_value=500.0,
                value=0.0,
                step=1.0,
                key="budget_ni",
            )

        uploaded_structs = st.file_uploader(
            "可选：上传初始结构（.xyz / .gjf / .cif，跳过全局搜索直接筛选）",
            type=["xyz", "gjf", "cif"],
            accept_multiple_files=True,
            key="init_struct_upload",
        )

    if st.button(
        "生成计算方案书", type="primary", use_container_width=True, key="btn_generate_plan"
    ):
        if not composition or not recipes:
            st.error("请至少选择一种元素与一个研究目标。")
            return
        parsed_clusters: list[Cluster] | None = None
        if uploaded_structs:
            parsed_clusters = []
            with tempfile.TemporaryDirectory() as tmp:
                for uf in uploaded_structs:
                    p = Path(tmp) / uf.name
                    p.write_bytes(uf.getvalue())
                    frames = ase_read(str(p), index=":")
                    if not isinstance(frames, list):
                        frames = [frames]
                    for idx, at in enumerate(frames):
                        parsed_clusters.append(
                            Cluster.from_ase(at, label=f"{p.stem}_{idx}", source=uf.name)
                        )
        try:
            charges_val: list[int] | str = "auto" if charge_mode == "auto" else [int(charge_mode)]
            req = ResearchRequest(
                composition=composition,
                recipes=list(recipes),
                accuracy=accuracy,  # type: ignore[arg-type]
                time_budget_hours=budget_h if budget_h > 0 else None,
                charges=charges_val,  # type: ignore[arg-type]
                structures=parsed_clusters,
            )
            _commit_plan_and_open_review(req, title=f"Cluster_{'_'.join(req.composition.keys())}")
        except Exception as exc:
            st.error(f"生成方案失败：{exc}")


def render_new_research_page() -> None:
    render_page_hero(
        "1. 新建团簇研究",
        "一句话自然语言描述即可全自动规划并直达方案书；也可随时切换标签页通过周期表或上传结构进行精细配置。",
        active_step=1,
    )

    tab_ai, tab_manual = st.tabs(
        ["🤖 AI 一句话全自动规划（推荐）", "🧪 手动精细配置（周期表 / 上传结构）"]
    )
    with tab_ai:
        _render_ai_tab()
    with tab_manual:
        _render_manual_tab()

    if st.session_state.get("pending_plan"):
        st.page_link(
            "pages/plan_review.py",
            label="已有待确认方案书：前往「2. 方案书」核对并提交 →",
            icon="📋",
            use_container_width=True,
        )


render_new_research_page()

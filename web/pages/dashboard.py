"""Page 3: Multi-Project Magpie-Style Routing Observation & Parallel Queue Dashboard."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from qcai.interfaces.runner import JobHandle
from qcai.launcher import get_runtime_status
from qcai.pipeline import JobRecord, PipelineWorker, ProjectRecord
from qcai.remote import DirectRunner, MockRunner, SSHClient
from web.routing_panel import (
    build_magpie_routing_panel_html,
    compute_routing_panel_height,
)
from web.state import get_db_path, get_projects_root, get_store, load_app_settings
from web.theme import render_page_hero

_STAGE_SHORT = {
    "S0_reference": "S0",
    "S1_search": "S1",
    "S2_dedup": "S2",
    "S3_screen": "S3",
    "S4_refine": "S4",
    "S5_ionic": "S5",
    "S6_postprocess": "S6",
    "S7_summary": "S7",
}

_STATUS_SORT_ORDER = {
    "needs_human": 0,
    "running": 1,
    "queued": 2,
    "done": 3,
    "cancelled": 4,
}

_STATUS_FILTER_LABELS = {
    "all": "全部状态",
    "running": "running（运行中）",
    "queued": "queued（等待槽位）",
    "done": "done（已完成）",
    "needs_human": "needs_human（需人工）",
    "cancelled": "cancelled（已取消）",
}


def _stage_badges_html(jobs: list[JobRecord]) -> str:
    if not jobs:
        return (
            '<div style="font-size:11.5px;color:#94a3b8;margin:4px 0 8px 0;">等待首次调度入队</div>'
        )
    pills: list[str] = []
    for st_name, short in _STAGE_SHORT.items():
        st_jobs = [j for j in jobs if j.stage == st_name]
        if not st_jobs:
            continue
        done_n = sum(1 for j in st_jobs if j.status == "done")
        run_n = sum(1 for j in st_jobs if j.status == "running")
        err_n = sum(1 for j in st_jobs if j.status == "needs_human")
        if err_n > 0:
            style = "background:#fee2e2;color:#991b1b;border:1px solid #fecaca;"
        elif done_n == len(st_jobs):
            style = "background:#dcfce7;color:#166534;border:1px solid #bbf7d0;"
        elif run_n > 0:
            style = "background:#dbeafe;color:#1e40af;border:1px solid #bfdbfe;"
        else:
            style = "background:#f1f5f9;color:#475569;border:1px solid #e2e8f0;"
        pills.append(
            f'<span style="{style}border-radius:999px;padding:1px 7px;'
            f'font-size:10.5px;font-weight:600;white-space:nowrap;">'
            f"{short} {done_n}/{len(st_jobs)}</span>"
        )
    return (
        '<div style="display:flex;flex-wrap:wrap;gap:4px;margin:4px 0 8px 0;">'
        + "".join(pills)
        + "</div>"
    )


def _status_ribbon_html(
    *,
    proj_count: int,
    run_n: int,
    queue_n: int,
    done_n: int,
    need_n: int,
) -> str:
    need_style = (
        "background:#fee2e2;color:#991b1b;" if need_n > 0 else "background:#f1f5f9;color:#475569;"
    )
    return (
        '<div style="display:flex;align-items:center;justify-content:space-between;'
        "flex-wrap:wrap;gap:8px;background:#ffffff;border:1px solid #e2e8f0;"
        'border-radius:12px;padding:8px 14px;margin:0.25rem 0 0.25rem 0;font-size:12.5px;">'
        f'<span style="font-weight:600;color:#334155;">队列总览 · {proj_count} 个项目</span>'
        '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
        f'<span style="background:#dcfce7;color:#166534;padding:2px 9px;border-radius:999px;font-weight:600;">运行中 {run_n}</span>'
        f'<span style="background:#e0f2fe;color:#0369a1;padding:2px 9px;border-radius:999px;font-weight:600;">排队中 {queue_n}</span>'
        f'<span style="background:#f1f5f9;color:#334155;padding:2px 9px;border-radius:999px;font-weight:600;">已完成 {done_n}</span>'
        f'<span style="{need_style}padding:2px 9px;border-radius:999px;font-weight:600;">需人工 {need_n}</span>'
        "</div></div>"
    )


def _render_project_card(proj: ProjectRecord, jobs: list[JobRecord]) -> None:
    tot = len(jobs)
    done_n = sum(1 for j in jobs if j.status == "done")
    run_n = sum(1 for j in jobs if j.status == "running")
    wait_n = sum(1 for j in jobs if j.status == "queued")
    need_n = sum(1 for j in jobs if j.status == "needs_human")
    pct = (done_n / tot) if tot > 0 else 0.0

    with st.container(border=True):
        st.markdown(f"**{html.escape(proj.title)}**")
        st.caption(
            f"`{proj.project_id}` · 状态 `{proj.status}` · "
            f"完成 {done_n}/{tot} · 运行 {run_n} · 待办 {wait_n}"
            + (f" · 异常 {need_n}" if need_n else "")
        )
        st.progress(pct)
        st.html(_stage_badges_html(jobs))

        b1, b2, b3 = st.columns(3)
        if proj.status == "running":
            if b1.button("⏸️ 暂停", width="stretch", key=f"card_pause_{proj.project_id}"):
                get_store().set_project_status(proj.project_id, "paused")
                st.rerun()
        else:
            if b1.button("▶️ 恢复", width="stretch", key=f"card_resume_{proj.project_id}"):
                get_store().set_project_status(proj.project_id, "running")
                st.rerun()

        if b2.button("🔍 明细", width="stretch", key=f"card_detail_{proj.project_id}"):
            st.session_state["dash_filter_project"] = proj.project_id
            st.rerun()

        if b3.button("📊 结果", width="stretch", key=f"card_result_{proj.project_id}"):
            st.session_state["active_project_id"] = proj.project_id
            st.switch_page("pages/results.py")


def _render_dashboard_body() -> None:
    store = get_store()
    projects = store.list_projects()
    if not projects:
        st.info("暂无项目，请先在「1. 新建研究」和「2. 方案书」页创建项目。")
        st.page_link("pages/new_research.py", label="前往新建研究页面", icon="🧪")
        return

    all_jobs = store.list_jobs()
    jobs_by_project: dict[str, list[JobRecord]] = {p.project_id: [] for p in projects}
    for job in all_jobs:
        jobs_by_project.setdefault(job.project_id, []).append(job)

    # Streamlined single-row global control strip
    c_exp, c_pause, c_resume, c_mock, c_refresh = st.columns([1.3, 1.0, 1.0, 1.5, 0.9])
    expand_routes = c_exp.checkbox("展开全部路由槽位", value=True, key="dash_expand_routes")
    if c_pause.button("⏸️ 暂停全部", width="stretch", key="dash_pause_all"):
        for p in projects:
            if p.status == "running":
                store.set_project_status(p.project_id, "paused")
        st.rerun()
    if c_resume.button("▶️ 恢复全部", width="stretch", key="dash_resume_all"):
        for p in projects:
            if p.status in {"paused", "needs_human"}:
                store.set_project_status(p.project_id, "running")
        st.rerun()
    if c_mock.button("模拟推进一轮 (Mock Tick)", width="stretch", key="dash_mock_tick"):
        cur_filter = str(st.session_state.get("dash_filter_project", "__ALL__"))
        target_pid = None if cur_filter == "__ALL__" else cur_filter
        pw = PipelineWorker(store, MockRunner(), projects_root=get_projects_root())
        stats = pw.step(project_id=target_pid)
        st.toast(f"调度执行: {stats}")
        st.rerun()
    if c_refresh.button("🔄 立即刷新", width="stretch", key="dash_refresh_now"):
        st.rerun()

    run_n = sum(1 for j in all_jobs if j.status == "running")
    queue_n = sum(1 for j in all_jobs if j.status == "queued")
    done_n = sum(1 for j in all_jobs if j.status == "done")
    need_n = sum(1 for j in all_jobs if j.status == "needs_human")
    st.html(
        _status_ribbon_html(
            proj_count=len(projects),
            run_n=run_n,
            queue_n=queue_n,
            done_n=done_n,
            need_n=need_n,
        )
    )

    # Primary block: Magpie-style multi-project live routing observation panel (full native SVG)
    settings = load_app_settings()
    rt = get_runtime_status(get_db_path())
    raw_wpid = rt.get("worker_pid")
    worker_pid = int(raw_wpid) if isinstance(raw_wpid, int) and rt.get("running") else None
    panel_html = build_magpie_routing_panel_html(
        projects,
        jobs_by_project,
        cluster_host=settings.ssh.host or "",
        worker_pid=worker_pid,
        expanded=expand_routes,
    )
    panel_height = compute_routing_panel_height(projects, jobs_by_project, expanded=expand_routes)
    components.html(panel_html, height=panel_height, scrolling=False)

    # Secondary block: parallel multi-project control grid
    with st.expander(
        f"📦 多项目并行控制面板（共 {len(projects)} 个项目）", expanded=len(projects) <= 12
    ):
        for row_start in range(0, len(projects), 3):
            row_projs = projects[row_start : row_start + 3]
            cols = st.columns(len(row_projs))
            for col, proj in zip(cols, row_projs, strict=True):
                with col:
                    _render_project_card(proj, jobs_by_project.get(proj.project_id, []))

    # Tertiary block: global / filtered job queue table
    proj_titles = {p.project_id: p.title for p in projects}
    proj_options = ["__ALL__", *[p.project_id for p in projects]]
    if st.session_state.get("dash_filter_project") not in proj_options:
        st.session_state["dash_filter_project"] = "__ALL__"

    with st.container(border=True):
        st.subheader("作业队列明细")
        f1, f2 = st.columns([2.2, 1.2])
        selected_filter_pid = f1.selectbox(
            "筛选项目",
            options=proj_options,
            format_func=lambda pid: (
                f"全部项目（共 {len(projects)} 个）"
                if pid == "__ALL__"
                else f"{proj_titles.get(pid, pid)} ({pid})"
            ),
            key="dash_filter_project",
        )
        selected_status = f2.selectbox(
            "筛选状态",
            options=list(_STATUS_FILTER_LABELS.keys()),
            format_func=lambda s: _STATUS_FILTER_LABELS.get(s, s),
            key="dash_filter_status",
        )

        filtered_jobs = [
            j
            for j in all_jobs
            if (selected_filter_pid == "__ALL__" or j.project_id == selected_filter_pid)
            and (selected_status == "all" or j.status == selected_status)
        ]
        filtered_jobs.sort(
            key=lambda j: (
                _STATUS_SORT_ORDER.get(j.status, 9),
                -(j.updated_at.timestamp() if j.updated_at else 0.0),
                j.job_id,
            )
        )

        if filtered_jobs:
            rows = [
                {
                    "项目": proj_titles.get(j.project_id, j.project_id),
                    "job_id": j.job_id,
                    "阶段": j.stage,
                    "团簇": j.cluster_label,
                    "q / M": f"{j.charge} / {j.multiplicity}",
                    "理论水平": j.level,
                    "状态": j.status,
                    "PID": j.pid or "-",
                    "自动修复": j.fixes,
                    "错误信息": j.error_message or "",
                }
                for j in filtered_jobs
            ]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.info("当前筛选条件下暂无作业记录。")

        running_ids = [j.job_id for j in filtered_jobs if j.status == "running"]
        if running_ids:
            with st.expander("取消运行中作业", expanded=False):
                cancel_id = st.selectbox(
                    "选择要取消的作业", options=running_ids, key="dash_cancel_sb"
                )
                if st.button("取消选中作业", type="secondary", key="dash_cancel_btn"):
                    job = store.get_job(cancel_id)
                    if job is not None:
                        if settings.ssh.host and settings.ssh.work_root:
                            ssh = SSHClient(settings.ssh)
                            try:
                                DirectRunner(ssh).cancel(
                                    JobHandle(job.job_id, job.pid, Path(job.remote_dir))
                                )
                            finally:
                                ssh.close()
                        job.status = "cancelled"
                        store.upsert_job(job)
                        st.rerun()

        fix_entries = [
            (j.job_id, json.loads(j.fixes)) for j in filtered_jobs if j.fixes and j.fixes != "[]"
        ]
        if fix_entries:
            with st.container(border=True):
                st.subheader("🔧 custodian 自动修复记录")
                for jid, fixes in fix_entries:
                    st.write(f"- `{jid}`: {fixes}")


@st.fragment(run_every=5)
def _live_dashboard_fragment() -> None:
    _render_dashboard_body()


def render_dashboard_page() -> None:
    render_page_hero(
        "3. 运行看板",
        "实时监控多项目 S0–S7 漏斗计算路由、远程队列并发与服务器端 custodian 自动容错修复记录。",
        active_step=3,
    )
    auto_refresh = st.checkbox("启用每 5 秒自动刷新", value=False, key="dash_autorefresh")
    if auto_refresh:
        _live_dashboard_fragment()
    else:
        _render_dashboard_body()


render_dashboard_page()

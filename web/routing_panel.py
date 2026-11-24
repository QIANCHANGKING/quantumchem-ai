"""Magpie-inspired multi-project real-time routing observation panel (native HTML5 + SVG)."""

from __future__ import annotations

import html
import json
from typing import Any

from qcai.pipeline.db import JobRecord, ProjectRecord

_LEFT_CARD_H = 66
_RIGHT_CARD_H = 62
_SUMMARY_H = 42
_GAP = 9
_SVG_W = 68

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

_STAGE_RANK = {name: idx for idx, name in enumerate(_STAGE_SHORT)}

# Curated low-saturation scientific palette: (accent, soft_bg, soft_border)
_PROJECT_PALETTE: tuple[tuple[str, str, str], ...] = (
    ("#4f46e5", "#eef2ff", "#c7d2fe"),  # Indigo
    ("#059669", "#ecfdf5", "#a7f3d0"),  # Emerald
    ("#0284c7", "#f0f9ff", "#bae6fd"),  # Sky
    ("#7c3aed", "#f5f3ff", "#ddd6fe"),  # Violet
    ("#d97706", "#fffbeb", "#fde68a"),  # Amber
    ("#e11d48", "#fff1f2", "#fecdd3"),  # Rose
    ("#0d9488", "#f0fdfa", "#99f6e4"),  # Teal
    ("#2563eb", "#eff6ff", "#bfdbfe"),  # Blue
)

_PANEL_CSS = """
html, body {
    margin: 0;
    padding: 0;
    background: transparent;
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC",
        "Microsoft YaHei", sans-serif;
    color: #0f172a;
    -webkit-font-smoothing: antialiased;
}
* { box-sizing: border-box; }
.mp-wrap {
    padding: 2px 2px 6px 2px;
}
.mp-topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 4px 10px 4px;
    font-size: 13px;
    flex-wrap: wrap;
    gap: 8px;
}
.mp-topbar-left {
    display: flex;
    align-items: center;
    gap: 8px;
}
.mp-topbar-title {
    font-weight: 700;
    color: #1e293b;
    letter-spacing: -0.01em;
}
.mp-topbar-sub {
    color: #64748b;
    font-size: 12.5px;
}
.mp-topbar-right {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11.5px;
    color: #475569;
}
.mp-meta-chip {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 999px;
    padding: 2px 10px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 11px;
    color: #475569;
}
.mp-dot {
    width: 8px;
    height: 8px;
    border-radius: 999px;
    display: inline-block;
    flex-shrink: 0;
}
.mp-dot-run {
    animation: mp-pulse 1.9s infinite;
}
@keyframes mp-pulse {
    0% { box-shadow: 0 0 0 0 rgba(22, 163, 74, 0.45); }
    70% { box-shadow: 0 0 0 6px rgba(22, 163, 74, 0); }
    100% { box-shadow: 0 0 0 0 rgba(22, 163, 74, 0); }
}
@keyframes mp-dash {
    to { stroke-dashoffset: -20; }
}
@keyframes mp-spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}
.mp-flow {
    stroke-dasharray: 5 5;
    animation: mp-dash 1.05s linear infinite;
}
.mp-board {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 16px;
    padding: 20px 22px 18px 22px;
    box-shadow: 0 4px 20px -4px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.04);
}
.mp-board-hdr {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 14px;
    flex-wrap: wrap;
}
.mp-board-title {
    font-size: 15.5px;
    font-weight: 700;
    color: #0f172a;
    letter-spacing: -0.01em;
    margin-bottom: 3px;
}
.mp-board-desc {
    font-size: 12.5px;
    color: #64748b;
    line-height: 1.45;
}
.mp-hdr-pill {
    font-size: 11.5px;
    font-weight: 600;
    color: #334155;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 999px;
    padding: 4px 11px;
    white-space: nowrap;
}
.mp-canvas {
    background-color: #fcfdfe;
    background-image: radial-gradient(#e2e8f0 1px, transparent 1px);
    background-size: 18px 18px;
    border: 1px solid #f1f5f9;
    border-radius: 13px;
    padding: 18px 16px;
}
.mp-graph {
    display: grid;
    grid-template-columns: minmax(200px, 260px) 68px 180px 68px minmax(260px, 1fr);
    align-items: center;
    width: 100%;
}
.mp-col {
    display: flex;
    flex-direction: column;
    gap: 9px;
    min-width: 0;
}
.mp-svg-col {
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 0;
}
.mp-proj-card,
.mp-job-card,
.mp-edge {
    transition: opacity 0.16s ease, transform 0.16s ease, box-shadow 0.16s ease;
}
.mp-proj-card {
    height: 66px;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 9px 12px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    min-width: 0;
    cursor: default;
}
.mp-proj-card.is-err {
    border-color: #fecaca;
    background: #fffafa;
}
.mp-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    min-width: 0;
}
.mp-row-left {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    flex: 1;
}
.mp-proj-name {
    font-size: 12.5px;
    font-weight: 600;
    color: #0f172a;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.mp-stage-chip {
    font-size: 10px;
    font-weight: 700;
    padding: 1px 5px;
    border-radius: 5px;
    background: #f1f5f9;
    color: #475569;
    flex-shrink: 0;
}
.mp-frac {
    font-size: 11px;
    font-weight: 700;
    color: #475569;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
.mp-bar-bg {
    width: 100%;
    height: 4.5px;
    background: #f1f5f9;
    border-radius: 999px;
    overflow: hidden;
}
.mp-bar-fill {
    height: 100%;
    border-radius: 999px;
    transition: width 0.25s ease;
}
.mp-mini-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 10.5px;
    color: #64748b;
    white-space: nowrap;
    gap: 4px;
}
.mp-mini-id {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 10px;
    color: #94a3b8;
}
.mp-hub {
    background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
    border: 1.6px solid #0f172a;
    border-radius: 16px;
    padding: 16px 14px;
    text-align: center;
    box-shadow: 0 12px 28px -8px rgba(15, 23, 42, 0.16), 0 0 0 4px rgba(15, 23, 42, 0.03);
}
.mp-hub-badge {
    width: 38px;
    height: 38px;
    border-radius: 11px;
    background: #0f172a;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 8px auto;
    box-shadow: 0 4px 10px rgba(15, 23, 42, 0.18);
}
.mp-hub-spin {
    animation: mp-spin 18s linear infinite;
    transform-origin: center;
}
.mp-hub-title {
    font-size: 14px;
    font-weight: 700;
    color: #0f172a;
    line-height: 1.2;
}
.mp-hub-host {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 11px;
    color: #64748b;
    margin: 3px 0 8px 0;
    word-break: break-all;
}
.mp-hub-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 9px;
    border-radius: 999px;
}
.mp-hub-pill-run { background: #dcfce7; color: #166534; }
.mp-hub-pill-err { background: #fee2e2; color: #991b1b; }
.mp-hub-pill-idle { background: #f1f5f9; color: #475569; }
.mp-hub-sub {
    font-size: 10.5px;
    color: #64748b;
    margin-top: 7px;
    font-variant-numeric: tabular-nums;
}
.mp-job-card {
    height: 62px;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 8px 12px 8px 11px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    min-width: 0;
    cursor: default;
}
.mp-job-card.is-err {
    border-color: #fecaca;
    background: #fffafa;
}
.mp-badge {
    font-size: 10.5px;
    font-weight: 600;
    padding: 1.5px 6px;
    border-radius: 6px;
    white-space: nowrap;
}
.mp-badge-stage { background: #f1f5f9; color: #334155; }
.mp-badge-fix { background: #fef3c7; color: #92400e; }
.mp-badge-run { background: #dcfce7; color: #166534; }
.mp-badge-err { background: #fee2e2; color: #991b1b; }
.mp-badge-done { background: #e0f2fe; color: #0369a1; }
.mp-job-title {
    font-size: 12px;
    font-weight: 600;
    color: #0f172a;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.mp-pid {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 11px;
    color: #64748b;
    white-space: nowrap;
}
.mp-job-sub {
    font-size: 11px;
    color: #64748b;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.mp-err-text {
    font-size: 11px;
    color: #b91c1c;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.mp-empty-slot {
    height: 62px;
    border: 1.4px dashed #cbd5e1;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #94a3b8;
    font-size: 12.5px;
    background: rgba(255, 255, 255, 0.72);
}
.mp-more-pill {
    height: 42px;
    border: 1px dashed #cbd5e1;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #475569;
    font-size: 12px;
    font-weight: 500;
    background: #f8fafc;
}
.mp-graph.is-hovering .mp-proj-card:not(.is-focused),
.mp-graph.is-hovering .mp-job-card:not(.is-focused) {
    opacity: 0.34;
}
.mp-graph.is-hovering .mp-edge:not(.is-focused) {
    opacity: 0.16;
}
.mp-graph.is-hovering .mp-proj-card.is-focused,
.mp-graph.is-hovering .mp-job-card.is-focused {
    box-shadow: 0 6px 16px -4px rgba(15, 23, 42, 0.14);
    transform: translateY(-1px);
}
.mp-graph.is-hovering .mp-edge.is-focused path {
    stroke-width: 2.6;
    stroke-opacity: 1;
}
.mp-footer {
    border-top: 1px solid #f1f5f9;
    margin-top: 16px;
    padding-top: 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 18px;
    flex-wrap: wrap;
}
.mp-footer-progress {
    flex: 1 1 240px;
    min-width: 200px;
}
.mp-footer-bar {
    width: 100%;
    height: 5px;
    background: #f1f5f9;
    border-radius: 999px;
    overflow: hidden;
}
.mp-footer-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, #2563eb 0%, #0ea5e9 100%);
}
.mp-footer-cap {
    font-size: 12px;
    color: #64748b;
    margin-top: 6px;
}
.mp-stats {
    display: flex;
    align-items: center;
    gap: 24px;
    flex-wrap: wrap;
}
.mp-stat {
    text-align: right;
    min-width: 46px;
}
.mp-stat-val {
    font-size: 22px;
    font-weight: 700;
    line-height: 1.1;
    color: #0f172a;
    font-variant-numeric: tabular-nums;
}
.mp-stat-val.is-err { color: #dc2626; }
.mp-stat-lbl {
    font-size: 11px;
    color: #64748b;
    margin-top: 3px;
}
"""

_HOVER_SCRIPT = """
<script>
(function() {
    var graph = document.querySelector('.mp-graph');
    if (!graph) return;
    var nodes = document.querySelectorAll('[data-pid]');
    function clearFocus() {
        graph.classList.remove('is-hovering');
        nodes.forEach(function(el) { el.classList.remove('is-focused'); });
    }
    document.querySelectorAll('.mp-proj-card[data-pid], .mp-job-card[data-pid]')
        .forEach(function(card) {
            card.addEventListener('mouseenter', function() {
                var pid = card.getAttribute('data-pid');
                if (!pid) return;
                graph.classList.add('is-hovering');
                nodes.forEach(function(el) {
                    if (el.getAttribute('data-pid') === pid) {
                        el.classList.add('is-focused');
                    } else {
                        el.classList.remove('is-focused');
                    }
                });
            });
            card.addEventListener('mouseleave', clearFocus);
        });
})();
</script>
"""


def _esc(val: Any) -> str:
    return html.escape(str(val or ""), quote=True)


def _count_fixes(job: JobRecord) -> int:
    if not job.fixes or job.fixes == "[]":
        return 0
    try:
        parsed = json.loads(job.fixes)
        return len(parsed) if isinstance(parsed, list) else 0
    except Exception:
        return 0


def _short_project_tag(proj: ProjectRecord) -> str:
    head = (proj.title or proj.project_id).strip().split()[0]
    if len(head) > 14:
        return head[:13] + "…"
    return head


def _current_stage_short(jobs: list[JobRecord]) -> str:
    if not jobs:
        return "待入队"
    for target_status in ("needs_human", "running", "queued", "done"):
        subset = [j for j in jobs if j.status == target_status]
        if subset:
            top = max(subset, key=lambda j: _STAGE_RANK.get(j.stage, -1))
            return _STAGE_SHORT.get(top.stage, top.stage)
    return _STAGE_SHORT.get(jobs[-1].stage, jobs[-1].stage)


def _compute_midpoints(heights: list[int], canvas_h: int) -> list[float]:
    if not heights:
        return []
    col_h = sum(heights) + _GAP * max(0, len(heights) - 1)
    y_cursor = (canvas_h - col_h) / 2.0
    mids: list[float] = []
    for h in heights:
        mids.append(y_cursor + h / 2.0)
        y_cursor += h + _GAP
    return mids


def _render_connector_svg(
    mids: list[float],
    edges: list[tuple[str, str, str]],
    canvas_h: int,
    *,
    left_to_center: bool,
) -> str:
    """Render native SVG cubic Bezier edges with flowing particles for active routes."""
    y_center = canvas_h / 2.0
    groups: list[str] = []
    for idx, (y_item, (pid, st_kind, accent)) in enumerate(zip(mids, edges, strict=True)):
        if left_to_center:
            x0, y0, x1, y1 = 4.0, y_item, float(_SVG_W - 4), y_center
            d = f"M {x0:.1f},{y0:.1f} C 36.0,{y0:.1f} 32.0,{y1:.1f} {x1:.1f},{y1:.1f}"
        else:
            x0, y0, x1, y1 = 4.0, y_center, float(_SVG_W - 4), y_item
            d = f"M {x0:.1f},{y0:.1f} C 36.0,{y0:.1f} 32.0,{y1:.1f} {x1:.1f},{y1:.1f}"

        pid_esc = _esc(pid)
        if st_kind == "run":
            dur = 1.7 + (idx % 4) * 0.2
            delay = (idx % 5) * 0.28
            inner = (
                f'<path d="{d}" stroke="{accent}" stroke-opacity="0.28" '
                'stroke-width="2" fill="none" />'
                f'<path d="{d}" class="mp-flow" stroke="{accent}" '
                'stroke-opacity="0.88" stroke-width="1.8" fill="none" />'
                f'<circle r="2.6" fill="{accent}">'
                f'<animateMotion dur="{dur:.2f}s" begin="{delay:.2f}s" '
                f'repeatCount="indefinite" path="{d}" />'
                "</circle>"
                f'<circle cx="{x0:.1f}" cy="{y0:.1f}" r="2.8" fill="{accent}" />'
                f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="3.2" fill="{accent}" />'
            )
        elif st_kind == "err":
            inner = (
                f'<path d="{d}" stroke="#dc2626" stroke-width="1.8" '
                'stroke-dasharray="4 3" stroke-opacity="0.9" fill="none" />'
                f'<circle cx="{x0:.1f}" cy="{y0:.1f}" r="2.8" fill="#dc2626" />'
                f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="3.2" fill="#dc2626" />'
            )
        elif st_kind == "done":
            inner = (
                f'<path d="{d}" stroke="#86efac" stroke-width="1.7" '
                'stroke-opacity="0.85" fill="none" />'
                f'<circle cx="{x0:.1f}" cy="{y0:.1f}" r="2.4" fill="#22c55e" />'
                f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="2.8" fill="#22c55e" />'
            )
        else:
            inner = (
                f'<path d="{d}" stroke="#cbd5e1" stroke-width="1.4" '
                'stroke-opacity="0.7" fill="none" />'
                f'<circle cx="{x0:.1f}" cy="{y0:.1f}" r="2.2" fill="#cbd5e1" />'
            )

        groups.append(f'<g class="mp-edge" data-pid="{pid_esc}">{inner}</g>')

    return (
        f'<svg width="{_SVG_W}" height="{canvas_h}" viewBox="0 0 {_SVG_W} {canvas_h}" '
        f'aria-hidden="true">{"".join(groups)}</svg>'
    )


def _project_visual_state(proj: ProjectRecord, jobs: list[JobRecord]) -> str:
    need_n = sum(1 for j in jobs if j.status == "needs_human")
    run_n = sum(1 for j in jobs if j.status == "running")
    if need_n > 0 or proj.status == "needs_human":
        return "err"
    if run_n > 0:
        return "run"
    if proj.status == "completed" or (jobs and all(j.status == "done" for j in jobs)):
        return "done"
    if proj.status == "paused":
        return "pause"
    return "idle"


def _select_visible_lanes(
    all_jobs: list[JobRecord], *, expanded: bool
) -> tuple[list[JobRecord], int, bool]:
    err_jobs = [j for j in all_jobs if j.status == "needs_human"]
    run_jobs = [j for j in all_jobs if j.status == "running"]
    active_lanes = err_jobs + run_jobs

    show_done_fallback = False
    if not active_lanes:
        done_jobs = sorted(
            [j for j in all_jobs if j.status == "done"],
            key=lambda j: j.updated_at.timestamp() if j.updated_at else 0.0,
            reverse=True,
        )
        if done_jobs:
            active_lanes = done_jobs[:4]
            show_done_fallback = True

    max_lanes = 24 if expanded else 6
    visible_lanes = active_lanes[:max_lanes]
    hidden_count = max(0, len(active_lanes) - len(visible_lanes))
    return visible_lanes, hidden_count, show_done_fallback


def _compute_canvas_dimensions(
    projects: list[ProjectRecord],
    jobs_by_project: dict[str, list[JobRecord]],
    *,
    expanded: bool,
) -> tuple[int, int, int]:
    all_jobs = [j for p in projects for j in jobs_by_project.get(p.project_id, [])]
    visible_lanes, hidden_count, _ = _select_visible_lanes(all_jobs, expanded=expanded)

    left_count = len(projects)
    left_total_h = left_count * _LEFT_CARD_H + _GAP * max(0, left_count - 1)

    right_heights = [_RIGHT_CARD_H] * (len(visible_lanes) if visible_lanes else 1)
    if hidden_count > 0:
        right_heights.append(_SUMMARY_H)
    right_total_h = sum(right_heights) + _GAP * max(0, len(right_heights) - 1)

    canvas_h = max(176, left_total_h, right_total_h)
    return canvas_h, left_total_h, right_total_h


def compute_routing_panel_height(
    projects: list[ProjectRecord],
    jobs_by_project: dict[str, list[JobRecord]],
    *,
    expanded: bool = True,
) -> int:
    """Compute iframe pixel height so the Magpie routing board never clips or scrolls."""
    canvas_h, _, _ = _compute_canvas_dimensions(projects, jobs_by_project, expanded=expanded)
    return canvas_h + 264


def build_magpie_routing_panel_html(
    projects: list[ProjectRecord],
    jobs_by_project: dict[str, list[JobRecord]],
    *,
    cluster_host: str = "",
    worker_pid: int | None = None,
    expanded: bool = True,
) -> str:
    """Render a Magpie-style multi-project live routing observation board in HTML5 + SVG."""
    all_jobs = [j for p in projects for j in jobs_by_project.get(p.project_id, [])]
    total_jobs = len(all_jobs)
    total_done = sum(1 for j in all_jobs if j.status == "done")
    total_running = sum(1 for j in all_jobs if j.status == "running")
    total_queued = sum(1 for j in all_jobs if j.status == "queued")
    total_need = sum(1 for j in all_jobs if j.status == "needs_human")
    total_fixes = sum(_count_fixes(j) for j in all_jobs)
    active_projects = sum(1 for p in projects if p.status == "running")

    if total_need > 0:
        top_dot_style = "background:#dc2626;"
        top_dot_cls = ""
        top_sub = f"注意 · {total_need} 个作业待人工排查，调度器统筹 {len(projects)} 个项目"
        board_title = f"存在需人工处理作业 · {total_need} 项待排查"
    elif total_running > 0 or active_projects > 0:
        top_dot_style = "background:#16a34a;"
        top_dot_cls = "mp-dot-run"
        top_sub = f"实时 · 调度器正在统筹 {len(projects)} 个项目"
        board_title = (
            f"实时并发调度中 · {total_running} 个作业运行中"
            if total_running > 0
            else f"调度器运行中 · {active_projects} 个活跃项目等待推进"
        )
    elif total_jobs > 0 and total_done == total_jobs:
        top_dot_style = "background:#0284c7;"
        top_dot_cls = ""
        top_sub = f"已全部完成 · 共 {len(projects)} 个项目"
        board_title = f"全部项目计算已完成 · 共 {total_done} 个作业"
    else:
        top_dot_style = "background:#94a3b8;"
        top_dot_cls = ""
        top_sub = f"空闲 · 当前共 {len(projects)} 个项目"
        board_title = "等待计算任务"

    proj_map = {p.project_id: p for p in projects}
    proj_palette_map: dict[str, tuple[str, str, str]] = {
        p.project_id: _PROJECT_PALETTE[idx % len(_PROJECT_PALETTE)]
        for idx, p in enumerate(projects)
    }

    # Left column: all projects simultaneously
    left_cards: list[str] = []
    left_heights: list[int] = []
    left_edges: list[tuple[str, str, str]] = []

    for p in projects:
        p_jobs = jobs_by_project.get(p.project_id, [])
        n_tot = len(p_jobs)
        n_done = sum(1 for j in p_jobs if j.status == "done")
        n_run = sum(1 for j in p_jobs if j.status == "running")
        n_wait = sum(1 for j in p_jobs if j.status == "queued")
        n_err = sum(1 for j in p_jobs if j.status == "needs_human")
        pct = int(round((n_done / n_tot) * 100)) if n_tot > 0 else 0
        vst = _project_visual_state(p, p_jobs)
        accent, soft_bg, soft_border = proj_palette_map[p.project_id]

        if vst == "err":
            dot_bg, dot_cls = "#dc2626", ""
            bar_bg = "#dc2626"
            card_border = "border-color:#fecaca;background:#fffafa;"
        elif vst == "run":
            dot_bg, dot_cls = accent, "mp-dot-run"
            bar_bg = accent
            card_border = f"border-color:{soft_border};border-left:3px solid {accent};"
        elif vst == "done":
            dot_bg, dot_cls = "#0284c7", ""
            bar_bg = "#0284c7"
            card_border = f"border-color:{soft_border};border-left:3px solid {accent};"
        elif vst == "pause":
            dot_bg, dot_cls = "#f59e0b", ""
            bar_bg = "#f59e0b"
            card_border = f"border-left:3px solid {soft_border};"
        else:
            dot_bg, dot_cls = "#94a3b8", ""
            bar_bg = accent
            card_border = f"border-left:3px solid {soft_border};"

        if n_tot == 0:
            mini_right = "尚未入队"
        else:
            parts: list[str] = []
            if n_run:
                parts.append(f'<b style="color:{accent};">{n_run} 运行</b>')
            if n_wait:
                parts.append(f"{n_wait} 待办")
            if n_err:
                parts.append(f'<b style="color:#dc2626;">{n_err} 异常</b>')
            if not parts:
                parts.append("已完成" if n_done == n_tot else f"{n_done} 完成")
            mini_right = " · ".join(parts[:2])

        stage_chip = _current_stage_short(p_jobs)
        title_esc = _esc(p.title)
        pid_esc = _esc(p.project_id)
        err_cls = " is-err" if vst == "err" else ""
        left_cards.append(
            f'<div class="mp-proj-card{err_cls}" data-pid="{pid_esc}" '
            f'style="{card_border}" title="{title_esc} ({pid_esc})">'
            f'<div class="mp-row">'
            f'<div class="mp-row-left">'
            f'<span class="mp-dot {dot_cls}" style="background:{dot_bg};"></span>'
            f'<span class="mp-proj-name">{title_esc}</span>'
            f'<span class="mp-stage-chip" style="background:{soft_bg};color:{accent};">'
            f"{_esc(stage_chip)}</span>"
            f"</div>"
            f'<span class="mp-frac">{n_done}/{n_tot}</span>'
            f"</div>"
            f'<div class="mp-bar-bg"><div class="mp-bar-fill" '
            f'style="width:{pct}%;background:{bar_bg};"></div></div>'
            f'<div class="mp-mini-meta"><span class="mp-mini-id">{pid_esc}</span>'
            f"<span>{mini_right}</span></div>"
            f"</div>"
        )
        left_heights.append(_LEFT_CARD_H)
        left_edges.append((p.project_id, vst, accent))

    # Right column: live remote job execution lanes
    visible_lanes, hidden_count, show_done_fallback = _select_visible_lanes(
        all_jobs, expanded=expanded
    )
    right_cards: list[str] = []
    right_heights: list[int] = []
    right_edges: list[tuple[str, str, str]] = []

    if not visible_lanes:
        empty_msg = (
            "当前无运行中作业"
            if total_queued == 0
            else f"等待集群槽位调度（{total_queued} 项待办）"
        )
        right_cards.append(f'<div class="mp-empty-slot">{_esc(empty_msg)}</div>')
        right_heights.append(_RIGHT_CARD_H)
        right_edges.append(("__empty__", "idle", "#cbd5e1"))
    else:
        for j in visible_lanes:
            proj = proj_map.get(j.project_id)
            proj_tag = _short_project_tag(proj) if proj else j.project_id
            stage_tag = _STAGE_SHORT.get(j.stage, j.stage)
            fix_n = _count_fixes(j)
            accent, soft_bg, soft_border = proj_palette_map.get(j.project_id, _PROJECT_PALETTE[0])

            if j.status == "needs_human":
                jst = "err"
                dot_style, dot_cls = "background:#dc2626;", ""
                card_style = "border-color:#fecaca;border-left:3px solid #dc2626;"
                st_badge = '<span class="mp-badge mp-badge-err">需人工</span>'
            elif j.status == "running":
                jst = "run"
                dot_style, dot_cls = f"background:{accent};", "mp-dot-run"
                card_style = f"border-color:{soft_border};border-left:3px solid {accent};"
                st_badge = '<span class="mp-badge mp-badge-run">运行中</span>'
            else:
                jst = "done"
                dot_style, dot_cls = "background:#0284c7;", ""
                card_style = f"border-left:3px solid {soft_border};"
                st_badge = '<span class="mp-badge mp-badge-done">已完成</span>'

            pid_txt = f"PID {_esc(j.pid)}" if j.pid else "等待 PID"
            fix_badge = (
                f'<span class="mp-badge mp-badge-fix">修复×{fix_n}</span>' if fix_n > 0 else ""
            )
            if j.status == "needs_human" and j.error_message:
                sub_left = f'<span class="mp-err-text">{_esc(j.error_message)}</span>'
            else:
                sub_left = f'<span class="mp-job-sub">{_esc(j.level or j.job_kind)}</span>'

            err_cls = " is-err" if jst == "err" else ""
            right_cards.append(
                f'<div class="mp-job-card{err_cls}" data-pid="{_esc(j.project_id)}" '
                f'style="{card_style}">'
                f'<div class="mp-row">'
                f'<div class="mp-row-left">'
                f'<span class="mp-dot {dot_cls}" style="{dot_style}"></span>'
                f'<span class="mp-badge" style="background:{soft_bg};color:{accent};">'
                f"{_esc(proj_tag)}</span>"
                f'<span class="mp-badge mp-badge-stage">{_esc(stage_tag)}</span>'
                f'<span class="mp-job-title">{_esc(j.cluster_label)} · '
                f"q={j.charge} M={j.multiplicity}</span>"
                f"</div>"
                f'<span class="mp-pid">{pid_txt}</span>'
                f"</div>"
                f'<div class="mp-row">{sub_left}'
                f'<div style="display:flex;align-items:center;gap:4px;flex-shrink:0;">'
                f"{fix_badge}{st_badge}</div></div>"
                f"</div>"
            )
            right_heights.append(_RIGHT_CARD_H)
            right_edges.append((j.project_id, jst, accent))

        if hidden_count > 0:
            label = (
                f"还有 {hidden_count} 个已完成/活跃槽位（开启「展开全部路由槽位」查看）"
                if show_done_fallback or not expanded
                else f"还有 {hidden_count} 个运行中槽位未展开"
            )
            right_cards.append(f'<div class="mp-more-pill">{_esc(label)}</div>')
            right_heights.append(_SUMMARY_H)
            right_edges.append(("__more__", "idle", "#cbd5e1"))

    canvas_h, _, _ = _compute_canvas_dimensions(projects, jobs_by_project, expanded=expanded)
    left_mids = _compute_midpoints(left_heights, canvas_h)
    right_mids = _compute_midpoints(right_heights, canvas_h)
    left_svg = _render_connector_svg(left_mids, left_edges, canvas_h, left_to_center=True)
    right_svg = _render_connector_svg(right_mids, right_edges, canvas_h, left_to_center=False)

    host_txt = _esc(cluster_host) if cluster_host else "local"
    if total_need > 0 and total_running == 0:
        hub_pill_cls = "mp-hub-pill-err"
        hub_pill_txt = f"{total_need} 项待排查"
    elif total_running > 0:
        hub_pill_cls = "mp-hub-pill-run"
        hub_pill_txt = f"● {total_running} 并发运行"
    else:
        hub_pill_cls = "mp-hub-pill-idle"
        hub_pill_txt = "空闲待命"

    hub_svg = (
        '<svg class="mp-hub-spin" width="22" height="22" viewBox="0 0 24 24" '
        'fill="none" stroke="#ffffff" stroke-width="1.8" aria-hidden="true">'
        '<circle cx="12" cy="12" r="2.2" fill="#ffffff" />'
        '<ellipse cx="12" cy="12" rx="9" ry="3.8" transform="rotate(30 12 12)" />'
        '<ellipse cx="12" cy="12" rx="9" ry="3.8" transform="rotate(-30 12 12)" />'
        '<ellipse cx="12" cy="12" rx="9" ry="3.8" transform="rotate(90 12 12)" />'
        "</svg>"
    )

    meta_right_parts: list[str] = []
    if cluster_host:
        meta_right_parts.append(f'<span class="mp-meta-chip">集群 {_esc(cluster_host)}</span>')
    if worker_pid:
        meta_right_parts.append(f'<span class="mp-meta-chip">Worker PID {_esc(worker_pid)}</span>')
    meta_right_html = "".join(meta_right_parts) or '<span class="mp-meta-chip">本地队列视图</span>'

    global_pct = int(round((total_done / total_jobs) * 100)) if total_jobs > 0 else 0
    need_cls = " is-err" if total_need > 0 else ""

    return (
        "<!DOCTYPE html>"
        '<html><head><meta charset="utf-8">'
        f"<style>{_PANEL_CSS}</style>"
        "</head><body>"
        '<div class="mp-wrap">'
        '<div class="mp-topbar">'
        '<div class="mp-topbar-left">'
        '<span class="mp-topbar-title">计算路由</span>'
        f'<span class="mp-dot {top_dot_cls}" style="{top_dot_style}"></span>'
        f'<span class="mp-topbar-sub">{_esc(top_sub)}</span>'
        "</div>"
        f'<div class="mp-topbar-right">{meta_right_html}</div>'
        "</div>"
        '<div class="mp-board">'
        '<div class="mp-board-hdr">'
        "<div>"
        f'<div class="mp-board-title">{_esc(board_title)}</div>'
        '<div class="mp-board-desc">'
        "悬停任意项目或作业卡片可高亮对应计算路由 · 实时展示 S0–S7 并发槽位与 custodian 自动修复。"
        "</div></div>"
        f'<div class="mp-hdr-pill">{len(projects)} 个项目同屏观测</div>'
        "</div>"
        '<div class="mp-canvas">'
        '<div class="mp-graph">'
        f'<div class="mp-col">{"".join(left_cards)}</div>'
        f'<div class="mp-svg-col">{left_svg}</div>'
        '<div class="mp-hub">'
        f'<div class="mp-hub-badge">{hub_svg}</div>'
        '<div class="mp-hub-title">qcai worker</div>'
        f'<div class="mp-hub-host">{host_txt}</div>'
        f'<span class="mp-hub-pill {hub_pill_cls}">{_esc(hub_pill_txt)}</span>'
        f'<div class="mp-hub-sub">{total_queued} 待调度 · {total_done} 完成</div>'
        "</div>"
        f'<div class="mp-svg-col">{right_svg}</div>'
        f'<div class="mp-col">{"".join(right_cards)}</div>'
        "</div></div>"
        '<div class="mp-footer">'
        '<div class="mp-footer-progress">'
        '<div class="mp-footer-bar"><div class="mp-footer-fill" '
        f'style="width:{global_pct}%;"></div></div>'
        '<div class="mp-footer-cap">'
        f"全局进度：{total_done} / {total_jobs} 作业 ({global_pct}%) · "
        f"活跃项目 {active_projects}/{len(projects)}"
        "</div></div>"
        '<div class="mp-stats">'
        f'<div class="mp-stat"><div class="mp-stat-val">{total_running}</div>'
        '<div class="mp-stat-lbl">运行中</div></div>'
        f'<div class="mp-stat"><div class="mp-stat-val">{total_queued}</div>'
        '<div class="mp-stat-lbl">待调度</div></div>'
        f'<div class="mp-stat"><div class="mp-stat-val">{total_done}</div>'
        '<div class="mp-stat-lbl">已完成</div></div>'
        f'<div class="mp-stat"><div class="mp-stat-val">{total_fixes}</div>'
        '<div class="mp-stat-lbl">自动修复</div></div>'
        f'<div class="mp-stat"><div class="mp-stat-val{need_cls}">{total_need}</div>'
        '<div class="mp-stat-lbl">需人工处理</div></div>'
        "</div></div></div></div>"
        f"{_HOVER_SCRIPT}"
        "</body></html>"
    )

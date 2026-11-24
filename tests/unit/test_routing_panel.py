"""Unit tests for the Magpie-style multi-project routing observation panel."""

from __future__ import annotations

from qcai.pipeline.db import JobRecord, ProjectRecord
from web.routing_panel import (
    build_magpie_routing_panel_html,
    compute_routing_panel_height,
)


def _mk_project(pid: str, title: str, status: str = "running") -> ProjectRecord:
    return ProjectRecord(
        project_id=pid,
        title=title,
        request_json="{}",
        plan_json="{}",
        status=status,
    )


def _mk_job(
    jid: str,
    pid: str,
    *,
    stage: str = "S3_screen",
    label: str = "TmAu5",
    status: str = "running",
    job_pid: str | None = "12345",
    fixes: str = "[]",
    error_message: str | None = None,
) -> JobRecord:
    return JobRecord(
        job_id=jid,
        project_id=pid,
        stage=stage,
        cluster_label=label,
        charge=0,
        multiplicity=3,
        level="PBE/def2-SVP",
        status=status,
        pid=job_pid,
        fixes=fixes,
        error_message=error_message,
    )


def test_routing_panel_idle_and_queued_only() -> None:
    p1 = _mk_project("proj_1", "Al4 稳定性研究", status="running")
    j1 = _mk_job("j1", "proj_1", label="Al4", status="queued", job_pid=None)
    html_out = build_magpie_routing_panel_html(
        [p1],
        {"proj_1": [j1]},
        cluster_host="100.74.91.19",
        worker_pid=44416,
    )

    assert html_out.startswith("<!DOCTYPE html>")
    assert "Al4 稳定性研究" in html_out
    assert "mp-empty-slot" in html_out
    assert "等待集群槽位调度" in html_out
    assert "<svg" in html_out
    assert "100.74.91.19" in html_out
    assert "Worker PID 44416" in html_out
    assert "待调度" in html_out
    assert "排队中" not in html_out
    assert compute_routing_panel_height([p1], {"proj_1": [j1]}) >= 400


def test_routing_panel_multi_project_parallel_and_collapsed_cap() -> None:
    projects = [
        _mk_project("p1", "Gd@Au₅ 电子结构刚性研究", status="running"),
        _mk_project("p2", "Tb@Au₅ 电子结构刚性研究", status="running"),
        _mk_project("p3", "Dy@Au₅ 电子结构刚性研究", status="running"),
        _mk_project("p4", "Ho@Au₅ 电子结构刚性研究", status="needs_human"),
        _mk_project("p5", "Lu@Au₅ 电子结构刚性研究", status="completed"),
    ]
    jobs_by_project = {
        "p1": [
            _mk_job("p1_r1", "p1", label="GdAu5_1", status="running", job_pid="1001"),
            _mk_job("p1_r2", "p1", label="GdAu5_2", status="running", job_pid="1002"),
            _mk_job("p1_q1", "p1", label="GdAu5_3", status="queued", job_pid=None),
        ],
        "p2": [
            _mk_job("p2_r1", "p2", label="TbAu5_1", status="running", job_pid="1003"),
            _mk_job("p2_r2", "p2", label="TbAu5_2", status="running", job_pid="1004"),
        ],
        "p3": [
            _mk_job(
                "p3_r1",
                "p3",
                label="DyAu5_1",
                status="running",
                job_pid="1005",
                fixes='["scf_xqc"]',
            ),
            _mk_job("p3_r2", "p3", label="DyAu5_2", status="running", job_pid="1006"),
        ],
        "p4": [
            _mk_job(
                "p4_e1",
                "p4",
                label="HoAu5_1",
                status="needs_human",
                job_pid="1007",
                fixes='["fix1", "fix2"]',
                error_message="L502 SCF did not converge",
            ),
            _mk_job("p4_r1", "p4", label="HoAu5_2", status="running", job_pid="1008"),
        ],
        "p5": [
            _mk_job(
                "p5_d1", "p5", stage="S4_refine", label="LuAu5_1", status="done", job_pid="900"
            ),
            _mk_job(
                "p5_d2", "p5", stage="S0_reference", label="atom_Lu", status="done", job_pid="901"
            ),
        ],
    }

    full_html = build_magpie_routing_panel_html(projects, jobs_by_project, expanded=True)
    for proj in projects:
        assert proj.title in full_html
        assert f'data-pid="{proj.project_id}"' in full_html
    assert "mp-flow" in full_html
    assert "<animateMotion" in full_html
    assert "is-hovering" in full_html
    assert "#4f46e5" in full_html
    assert "#059669" in full_html
    assert 'stroke="#dc2626"' in full_html
    assert "5 个项目同屏观测" in full_html
    assert "● 7 并发运行" in full_html
    assert "修复×2" in full_html
    # Totals: running=7, queued=1, done=2, fixes=3, needs_human=1
    assert '<div class="mp-stat-val">7</div><div class="mp-stat-lbl">运行中</div>' in full_html
    assert '<div class="mp-stat-val">1</div><div class="mp-stat-lbl">待调度</div>' in full_html
    assert '<div class="mp-stat-val">2</div><div class="mp-stat-lbl">已完成</div>' in full_html
    assert '<div class="mp-stat-val">3</div><div class="mp-stat-lbl">自动修复</div>' in full_html
    assert (
        '<div class="mp-stat-val is-err">1</div><div class="mp-stat-lbl">需人工处理</div>'
        in full_html
    )

    h_full = compute_routing_panel_height(projects, jobs_by_project, expanded=True)
    h_collapsed = compute_routing_panel_height(projects, jobs_by_project, expanded=False)
    assert h_full > h_collapsed >= 400

    collapsed_html = build_magpie_routing_panel_html(projects, jobs_by_project, expanded=False)
    assert "还有 2 个已完成/活跃槽位" in collapsed_html


def test_routing_panel_escapes_html_injection() -> None:
    p = _mk_project("p_xss", '<script>alert("x")</script>', status="needs_human")
    j = _mk_job(
        "j_xss",
        "p_xss",
        label="<img src=x>",
        status="needs_human",
        error_message="<script>boom()</script>",
    )
    out = build_magpie_routing_panel_html([p], {"p_xss": [j]})
    assert '<script>alert("x")' not in out
    assert "<script>boom()" not in out
    assert "<img src=x>" not in out
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in out
    assert "&lt;script&gt;boom()&lt;/script&gt;" in out

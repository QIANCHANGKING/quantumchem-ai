"""Thin privacy-preserving tool wrappers exposed to the AI agent (Section 6.10)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from qcai.analysis import summarize_cluster, summarize_project
from qcai.core.models import CalcPlan, CalcResult, Decision, ResearchRequest
from qcai.pipeline.db import JobStore
from qcai.planner import build_plan


class PendingActionRequest(BaseModel):
    """Side-effect action proposal requiring explicit user confirmation in UI."""

    action: Literal["run_project", "cancel_job", "pause_project"]
    target_id: str
    reason: str
    requires_confirmation: bool = True


def tool_plan_research(request: ResearchRequest) -> CalcPlan:
    """Plan a research workflow from a structured ResearchRequest."""
    return build_plan(request)


def tool_get_plan(store: JobStore, project_id: str) -> CalcPlan:
    """Retrieve the CalcPlan for an existing project."""
    proj = store.get_project(project_id)
    if proj is None or proj.plan_json is None:
        raise KeyError(f"Project {project_id!r} or its plan not found")
    return CalcPlan.model_validate_json(proj.plan_json)


def tool_get_summary(store: JobStore, project_id: str) -> dict[str, Any]:
    """Return privacy-preserving ProjectSummary without raw XYZ coordinates or raw logs."""
    jobs = store.list_jobs(project_id=project_id)
    results: list[CalcResult] = []
    for j in jobs:
        if j.result_path and Path(j.result_path).exists():
            results.append(
                CalcResult.model_validate_json(Path(j.result_path).read_text(encoding="utf-8"))
            )
    if not results:
        return {"project_id": project_id, "clusters": {}, "job_count": len(jobs)}

    grouped: dict[str, list[CalcResult]] = {}
    for r in results:
        grouped.setdefault(
            f"{r.final_geometry.label if r.final_geometry else r.job_id}", []
        ).append(r)

    clusters = {
        k: summarize_cluster(k, grp)
        for k, grp in grouped.items()
        if any(r.normal_termination and r.energy_hartree is not None for r in grp)
    }
    ps = summarize_project(project_id, clusters)
    # Strip full ground_state_geometry coordinates before sending to external LLM API
    payload = ps.model_dump()
    for cs_data in payload.get("clusters", {}).values():
        cs_data.pop("ground_state_geometry", None)
    return dict(payload)


def tool_get_job(store: JobStore, job_id: str) -> dict[str, Any]:
    """Return structured status and key parsed metrics for one job (never raw logs)."""
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(f"Job {job_id!r} not found")
    info: dict[str, Any] = {
        "job_id": job.job_id,
        "project_id": job.project_id,
        "stage": job.stage,
        "cluster_label": job.cluster_label,
        "charge": job.charge,
        "multiplicity": job.multiplicity,
        "level": job.level,
        "status": job.status,
        "attempts": job.attempts,
        "fixes": job.fixes,
        "error_message": job.error_message,
    }
    if job.result_path and Path(job.result_path).exists():
        res = CalcResult.model_validate_json(Path(job.result_path).read_text(encoding="utf-8"))
        info["normal_termination"] = res.normal_termination
        info["error_code"] = res.error_code
        info["energy_hartree"] = res.energy_hartree
        info["zpe_hartree"] = res.zpe_hartree
        info["imag_freqs"] = res.imag_freqs
        info["s2_before"] = res.s2_before
        info["s2_after"] = res.s2_after
        info["stable"] = res.stable
    return info


def tool_explain_decision(plan: CalcPlan, key: str) -> Decision | None:
    """Return the Decision explaining why a planning key was chosen."""
    for dec in reversed(plan.decisions):
        if dec.key == key:
            return dec
    return None


def tool_diagnose_job(store: JobStore, job_id: str) -> dict[str, Any]:
    """Return diagnostic error hints, custodian fixes, and suggested remediation."""
    job_info = tool_get_job(store, job_id)
    code = job_info.get("error_code")
    suggestions: list[str] = []
    if code == "L502":
        suggestions.append("SCF 未收敛：建议切换 robust SCF (`scf=(xqc,maxcycle=500)`) 或降低步长")
    elif code == "L9999":
        suggestions.append("几何优化步数耗尽：建议增加 `opt=(maxcycles=150)` 或更换初猜结构")
    elif job_info.get("imag_freqs"):
        suggestions.append("存在虚频：沿虚频简正模式微扰后重新优化 (`ImaginaryFreqHandler`)")
    elif job_info.get("stable") is False:
        suggestions.append("波函数存在不稳定性：建议启用 `stable=opt`")
    return {**job_info, "suggestions": suggestions}


def tool_request_action(
    action: Literal["run_project", "cancel_job", "pause_project"],
    target_id: str,
    reason: str,
) -> PendingActionRequest:
    """Create a pending confirmation request; side effects never execute automatically."""
    return PendingActionRequest(action=action, target_id=target_id, reason=reason)

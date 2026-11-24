"""DeepSeek pydantic-ai agents for NL planning and grounded result interpretation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from qcai.ai.guard import verify_grounded_numbers
from qcai.ai.tools import (
    PendingActionRequest,
    tool_diagnose_job,
    tool_explain_decision,
    tool_get_job,
    tool_get_plan,
    tool_get_summary,
    tool_request_action,
)
from qcai.config import load_settings, resolve_deepseek_key
from qcai.core.models import CalcPlan, ResearchRequest
from qcai.interfaces import LLMS, LLMProvider
from qcai.pipeline.db import JobStore
from qcai.planner import build_plan

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class ProposedPlan(BaseModel):
    """A concrete, ready-to-run ResearchRequest proposal suggested by the AI."""

    title: str
    rationale: str
    request: ResearchRequest


class ParsedIntent(BaseModel):
    """Structured output of natural-language research parsing."""

    needs_clarification: bool = False
    clarification_question: str | None = None
    request: ResearchRequest | None = None
    suggested_title: str | None = None
    suggested_proposals: list[ProposedPlan] = Field(default_factory=list)


class AutoPlanOutcome(BaseModel):
    """End-to-end outcome from natural language to deterministic CalcPlan."""

    intent: ParsedIntent
    plan: CalcPlan | None = None
    project_title: str | None = None


class InterpretationResult(BaseModel):
    """Grounded AI interpretation text and verification status."""

    text: str
    verified: bool
    unverified_numbers: list[float] = []


@dataclass
class AnalystDeps:
    """Runtime dependencies injected into the Analyst pydantic-ai Agent."""

    store: JobStore
    project_id: str
    observed_facts: list[dict[str, Any]] = field(default_factory=list)
    pending_actions: list[PendingActionRequest] = field(default_factory=list)


class DeepSeekLLMProvider(LLMProvider):
    """LLMProvider implementation backed by pydantic-ai DeepSeekProvider."""

    name = "deepseek"

    def build_model(self, model_name: str, api_key: str, *, base_url: str | None = None) -> Any:
        cleaned_url = (base_url or "").strip() or None
        provider = DeepSeekProvider(api_key=api_key, base_url=cleaned_url)
        return OpenAIChatModel(model_name, provider=provider)


if "deepseek" not in LLMS:
    LLMS.register("deepseek", DeepSeekLLMProvider())


def _resolve_model(
    api_key: str | None = None,
    model_override: Any = None,
    base_url: str | None = None,
) -> Any:
    if model_override is not None:
        return model_override
    settings = load_settings()
    key = (api_key or resolve_deepseek_key(settings)).strip()
    model_name = (
        os.environ.get("DEEPSEEK_MODEL", "").strip() or settings.deepseek.model or "deepseek-chat"
    )
    resolved_url = (
        base_url or os.environ.get("DEEPSEEK_BASE_URL", "") or settings.deepseek.base_url
    ).strip() or None
    return LLMS.get("deepseek").build_model(model_name, key, base_url=resolved_url)


def _default_project_title(req: ResearchRequest) -> str:
    """Build a compact formula-like project title from composition without element branching."""
    parts: list[str] = []
    for sym, cnt in req.composition.items():
        if isinstance(cnt, tuple):
            parts.append(f"{sym}{cnt[0]}-{cnt[1]}")
        elif cnt == 1:
            parts.append(sym)
        else:
            parts.append(f"{sym}{cnt}")
    return "".join(parts) or "Cluster_Research"


def parse_natural_language_request(
    instruction: str,
    *,
    api_key: str | None = None,
    model: Any = None,
    base_url: str | None = None,
) -> ResearchRequest:
    """Translate natural language instruction into ResearchRequest or raise on ambiguity."""
    intent = parse_natural_language_intent(
        instruction, api_key=api_key, model=model, base_url=base_url
    )
    if intent.needs_clarification or intent.request is None:
        raise ValueError(intent.clarification_question or "指令信息不足，请补充体系与研究目标。")
    return intent.request


def parse_natural_language_intent(
    instruction: str,
    *,
    history: list[tuple[str, str]] | None = None,
    api_key: str | None = None,
    model: Any = None,
    base_url: str | None = None,
) -> ParsedIntent:
    """Parse Chinese/English instruction into ParsedIntent (with optional multi-turn history)."""
    sys_prompt = (PROMPTS_DIR / "planner_system.md").read_text(encoding="utf-8")
    resolved = _resolve_model(api_key=api_key, model_override=model, base_url=base_url)
    agent: Agent[None, ParsedIntent] = Agent(
        resolved,
        output_type=ParsedIntent,
        system_prompt=sys_prompt,
        retries=2,
    )

    @agent.output_validator
    def _validate_intent(ctx: RunContext[None], output: ParsedIntent) -> ParsedIntent:
        del ctx
        if not output.needs_clarification:
            if output.request is None:
                raise ModelRetry(
                    "当 needs_clarification=false 时必须提供完整的 request；"
                    "若用户要求对比多个不同元素，请将 needs_clarification 设为 true、request 设为 null，"
                    "并在 suggested_proposals 中为每个具体元素分别生成独立的 ProposedPlan。"
                )
            try:
                build_plan(output.request)
            except Exception as exc:
                raise ModelRetry(
                    f"生成的 request 未通过确定性规则引擎校验：{exc}。"
                    "请使用合法的元素符号与研究目标重写，或改用 needs_clarification=true 并拆分为多个合法的 suggested_proposals。"
                ) from exc

        for idx, prop in enumerate(output.suggested_proposals):
            try:
                build_plan(prop.request)
            except Exception as exc:
                raise ModelRetry(
                    f"第 {idx + 1} 条推荐方案 ({prop.title!r}) 未通过确定性规则引擎校验：{exc}。"
                    "请确保每条推荐方案都使用真实周期表元素符号与合法参数。"
                ) from exc
        return output

    prompt_input = instruction
    if history:
        turns = "\n".join(
            f"[{'用户' if role == 'user' else '助手'}] {content.strip()}"
            for role, content in history
            if content.strip()
        )
        if turns:
            prompt_input = f"此前多轮对话记录：\n{turns}\n\n最新用户补充：{instruction}"
    res = agent.run_sync(prompt_input)
    return res.output


def auto_plan_from_natural_language(
    instruction: str,
    *,
    history: list[tuple[str, str]] | None = None,
    api_key: str | None = None,
    model: Any = None,
    base_url: str | None = None,
) -> AutoPlanOutcome:
    """Parse NL prompt (optionally multi-turn) and immediately build deterministic CalcPlan."""
    intent = parse_natural_language_intent(
        instruction,
        history=history,
        api_key=api_key,
        model=model,
        base_url=base_url,
    )
    if not intent.needs_clarification and intent.request is not None:
        plan = build_plan(intent.request)
        title = (intent.suggested_title or "").strip() or _default_project_title(intent.request)
        return AutoPlanOutcome(intent=intent, plan=plan, project_title=title)
    return AutoPlanOutcome(
        intent=intent,
        plan=None,
        project_title=(intent.suggested_title or "").strip() or None,
    )


def build_analyst_agent(model: Any) -> Agent[AnalystDeps, str]:
    """Create the pydantic-ai analyst agent with privacy-safe tools and numerical guard."""
    sys_prompt = (PROMPTS_DIR / "analyst_system.md").read_text(encoding="utf-8")
    agent: Agent[AnalystDeps, str] = Agent(
        model,
        deps_type=AnalystDeps,
        output_type=str,
        system_prompt=sys_prompt,
        retries=2,
    )

    @agent.tool
    def get_summary(ctx: RunContext[AnalystDeps], project_id: str | None = None) -> dict[str, Any]:
        pid = project_id or ctx.deps.project_id
        data = tool_get_summary(ctx.deps.store, pid)
        ctx.deps.observed_facts.append(data)
        return data

    @agent.tool
    def get_plan(ctx: RunContext[AnalystDeps], project_id: str | None = None) -> dict[str, Any]:
        pid = project_id or ctx.deps.project_id
        data = tool_get_plan(ctx.deps.store, pid).model_dump()
        ctx.deps.observed_facts.append(data)
        return data

    @agent.tool
    def get_job(ctx: RunContext[AnalystDeps], job_id: str) -> dict[str, Any]:
        data = tool_get_job(ctx.deps.store, job_id)
        ctx.deps.observed_facts.append(data)
        return data

    @agent.tool
    def explain_decision(
        ctx: RunContext[AnalystDeps], key: str, project_id: str | None = None
    ) -> dict[str, Any]:
        pid = project_id or ctx.deps.project_id
        plan = tool_get_plan(ctx.deps.store, pid)
        dec = tool_explain_decision(plan, key)
        out = dec.model_dump() if dec is not None else {"key": key, "found": False}
        ctx.deps.observed_facts.append(out)
        return out

    @agent.tool
    def diagnose_job(ctx: RunContext[AnalystDeps], job_id: str) -> dict[str, Any]:
        data = tool_diagnose_job(ctx.deps.store, job_id)
        ctx.deps.observed_facts.append(data)
        return data

    @agent.tool
    def propose_action(
        ctx: RunContext[AnalystDeps],
        action: str,
        target_id: str,
        reason: str,
    ) -> dict[str, Any]:
        req = tool_request_action(action, target_id, reason)  # type: ignore[arg-type]
        ctx.deps.pending_actions.append(req)
        return req.model_dump()

    @agent.output_validator
    def validate_numbers(ctx: RunContext[AnalystDeps], text: str) -> str:
        # Ensure at least project summary is included in grounded facts
        facts_bundle: list[Any] = list(ctx.deps.observed_facts)
        if not facts_bundle:
            facts_bundle.append(tool_get_summary(ctx.deps.store, ctx.deps.project_id))
        report = verify_grounded_numbers(text, facts_bundle)
        if not report.grounded:
            raise ModelRetry(
                f"回答中出现未在事实数据中查到的数值 {report.unverified_numbers}。"
                "请先调用工具核对并只输出真实数值。"
            )
        return text

    return agent


def interpret_project(
    store: JobStore,
    project_id: str,
    question: str = "请用中文总结本项目的基态结构、电子性质与关键异常。",
    *,
    api_key: str | None = None,
    model: Any = None,
    base_url: str | None = None,
) -> InterpretationResult:
    """Run grounded AI interpretation, marking unverified output red in UI on retry exhaustion."""
    resolved = _resolve_model(api_key=api_key, model_override=model, base_url=base_url)
    agent = build_analyst_agent(resolved)
    deps = AnalystDeps(store=store, project_id=project_id)
    try:
        res = agent.run_sync(question, deps=deps)
        return InterpretationResult(text=str(res.output), verified=True, unverified_numbers=[])
    except Exception as exc:
        # Check if output_validator failed after max retries
        summary = tool_get_summary(store, project_id)
        report = verify_grounded_numbers(str(exc), [summary, *deps.observed_facts])
        return InterpretationResult(
            text=f"AI 数值校验未通过，已拦截未核验文本：{exc}",
            verified=False,
            unverified_numbers=report.unverified_numbers,
        )

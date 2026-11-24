"""Unit tests for P8 AI tools, numerical hallucination guard, ModelRetry, and 50-instruction eval."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from ase.data import chemical_symbols
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from qcai.ai import (
    ParsedIntent,
    PendingActionRequest,
    ProposedPlan,
    auto_plan_from_natural_language,
    interpret_project,
    tool_diagnose_job,
    tool_explain_decision,
    tool_get_job,
    tool_get_summary,
    tool_request_action,
    verify_grounded_numbers,
)
from qcai.core.models import CalcResult, Cluster, ElectronicState, ResearchRequest
from qcai.core.physics import HA_TO_EV
from qcai.interfaces import LLMS
from qcai.pipeline import JobRecord, JobStore, ProjectRecord
from qcai.planner import build_plan
from tests.llm_eval.eval_runner import run_eval

INSTRUCTIONS_YAML = Path(__file__).resolve().parents[1] / "llm_eval" / "instructions.yaml"
_VALID_ELS = sorted(chemical_symbols[1:87], key=len, reverse=True)


def test_numerical_guard_grounded_unit_conversion_and_hallucination() -> None:
    facts = {
        "ground_state_energy_hartree": -972.741909,
        "homo_lumo_gap_ev": 1.85,
        "ground_state_multiplicity": 1,
        "binding_energy_ev_per_atom": 0.92,
    }
    # Exact and unit-converted (e.g. 1.85 eV -> 0.068 Ha) & rounded values pass
    gap_ha = 1.85 / HA_TO_EV
    good_text = (
        f"1. Na6 的基态多重度为 1，总能量为 -972.74 Ha，HOMO-LUMO 能隙为 1.85 eV（约 {gap_ha:.3f} Ha），"
        "平均结合能为 0.92 eV/atom（PBE0/def2-TZVP）。"
    )
    rep_good = verify_grounded_numbers(good_text, facts)
    assert rep_good.grounded is True
    assert rep_good.unverified_numbers == []

    # Fabricated numbers must be intercepted!
    bad_text = "Na6 基态总能量为 -972.74 Ha，但能隙高达 4.32 eV，自旋布居达到 85.4%。"
    rep_bad = verify_grounded_numbers(bad_text, facts)
    assert rep_bad.grounded is False
    assert 4.32 in rep_bad.unverified_numbers
    assert 85.4 in rep_bad.unverified_numbers


def _seed_store(tmp_path: Path) -> JobStore:
    db_path = tmp_path / "ai_test.sqlite"
    store = JobStore(db_path)
    req = ResearchRequest(composition={"Na": 4}, recipes=["stability"], accuracy="standard")
    plan = build_plan(req)
    store.upsert_project(
        ProjectRecord(
            project_id="p1",
            title="Na4",
            request_json=req.model_dump_json(),
            plan_json=plan.model_dump_json(),
            status="completed",
        )
    )
    c = Cluster(
        symbols=["Na", "Na", "Na", "Na"],
        positions=[(0, 0, 0), (3, 0, 0), (1.5, 2.6, 0), (1.5, 0.9, 2.4)],
        label="Na4",
    )
    res = CalcResult(
        job_id="j_ok",
        normal_termination=True,
        state=ElectronicState(charge=0, multiplicity=1),
        final_geometry=c,
        energy_hartree=-648.512,
        mo_energies_hartree=[[-0.25, -0.15, -0.05]],
        homo_indices=[1],
    )
    r_path = tmp_path / "j_ok.json"
    r_path.write_text(res.model_dump_json(), encoding="utf-8")
    store.upsert_job(
        JobRecord(
            job_id="j_ok",
            project_id="p1",
            stage="S4_refine",
            cluster_label="Na4",
            status="done",
            result_path=str(r_path),
        )
    )
    store.upsert_job(
        JobRecord(
            job_id="j_err",
            project_id="p1",
            stage="S3_screen",
            cluster_label="Na4",
            status="needs_human",
            error_message="L502",
            fixes='["scf_max_cycles=100"]',
        )
    )
    return store


def test_ai_tools_privacy_and_side_effect_confirmation(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    summary = tool_get_summary(store, "p1")
    # Privacy: raw XYZ coordinates stripped from summary sent to LLM
    for cs in summary["clusters"].values():
        assert "ground_state_geometry" not in cs

    j_info = tool_get_job(store, "j_ok")
    assert j_info["energy_hartree"] == pytest.approx(-648.512)
    diag = tool_diagnose_job(store, "j_err")
    assert diag["status"] == "needs_human"

    dec = tool_explain_decision(
        build_plan(ResearchRequest(composition={"Fe": 4}, recipes=["magnetism"])),
        "scf_strategy",
    )
    assert dec is not None and dec.value == "robust"

    pending = tool_request_action("run_project", "p1", "用户请求提交计算")
    assert isinstance(pending, PendingActionRequest)
    assert pending.requires_confirmation is True


def test_analyst_output_validator_model_retry_and_red_flag(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    assert "deepseek" in LLMS

    # Scenario 1: Attempt 1 hallucinates 9.99 eV -> ModelRetry -> Attempt 2 cites real -648.512 Ha
    calls = {"n": 0}

    def retry_then_fix(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] == 1:
            return ModelResponse(parts=[ToolCallPart("get_summary", {"project_id": "p1"})])
        if calls["n"] == 2:
            return ModelResponse(parts=[TextPart("基态能量 -648.512 Ha，但能隙高达 9.99 eV。")])
        return ModelResponse(parts=[TextPart("基态总能量为 -648.512 Ha，自旋多重度为 1。")])

    res_ok = interpret_project(store, "p1", model=FunctionModel(retry_then_fix))
    assert res_ok.verified is True
    assert calls["n"] == 3

    # Scenario 2: Always hallucinates -> retries exhausted -> returns verified=False for UI red mark
    def always_hallucinate(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        has_tool_ret = any(
            getattr(p, "part_kind", "") == "tool-return" for m in messages for p in m.parts
        )
        if not has_tool_ret:
            return ModelResponse(parts=[ToolCallPart("get_summary", {"project_id": "p1"})])
        return ModelResponse(parts=[TextPart("编造能量 -1234.56 Ha 与 77.7 eV。")])

    res_bad = interpret_project(store, "p1", model=FunctionModel(always_hallucinate))
    assert res_bad.verified is False
    assert "未通过" in res_bad.text


def _mock_rule_nl_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Deterministic FunctionModel simulating a strong NL planner for offline CI evaluation."""
    user_text = ""
    for m in messages:
        for p in m.parts:
            if getattr(p, "part_kind", "") == "user-prompt":
                user_text = str(p.content)

    # Check if explicit size/stoichiometry exists
    has_num = bool(re.search(r"\d+", user_text))
    if not has_num or "上次" in user_text or "几个" in user_text:
        payload = ParsedIntent(
            needs_clarification=True,
            clarification_question="请明确团簇的元素组成与原子数范围。",
            request=None,
        )
        return ModelResponse(
            parts=[ToolCallPart("final_result", json.loads(payload.model_dump_json()))]
        )

    # Extract composition (single formula token or dopant+host range, without double counting)
    comp: dict[str, int | tuple[int, int]] = {}
    endo_m = re.search(r"([A-Z][a-z]?)@([A-Z][a-z]?)(\d+)", user_text)
    range_m = re.search(r"([A-Z][a-z]?)(\d+)-(\d+)([A-Z][a-z]?)?", user_text)
    chinese_range = re.search(r"([A-Z][a-z]?)(\d+)\s*到\s*([A-Z][a-z]?)?(\d+)", user_text)
    if endo_m:
        comp = {endo_m.group(1): 1, endo_m.group(2): int(endo_m.group(3))}
    elif range_m:
        comp[range_m.group(1)] = (int(range_m.group(2)), int(range_m.group(3)))
        if range_m.group(4):
            comp[range_m.group(4)] = 1
    elif chinese_range:
        comp[chinese_range.group(1)] = (
            int(chinese_range.group(2)),
            int(chinese_range.group(4)),
        )
    else:
        paren_m = re.search(r"（((?:[A-Z][a-z]?\d*)+)）", user_text)
        formula_tokens = [
            m.group(1)
            for m in re.finditer(r"((?:[A-Z][a-z]?\d*)+)", user_text)
            if any(ch.isdigit() for ch in m.group(1))
        ]
        target_formula = (
            paren_m.group(1)
            if (paren_m and any(ch.isdigit() for ch in paren_m.group(1)))
            else (formula_tokens[0] if formula_tokens else "")
        )
        for el, cnt_s in re.findall(r"([A-Z][a-z]?)(\d*)", target_formula):
            comp[el] = int(cnt_s) if cnt_s else 1
        dop_m = re.search(r"([A-Z][a-z]?)\s*掺杂", user_text)
        if dop_m and dop_m.group(1) not in comp:
            comp[dop_m.group(1)] = 1

    cleaned_text = (
        user_text.replace("电子结构", "ELEC_STRUCT")
        .replace("光电子能谱", "PES_SPEC")
        .replace("电子亲和", "EA_PROP")
    )
    recipes: list[str] = []
    if any(k in user_text for k in ("稳定", "混合能", "基态")) or "结构" in cleaned_text:
        recipes.append("stability")
    if (
        "ELEC_STRUCT" in cleaned_text
        or "电子" in cleaned_text
        or any(k in user_text for k in ("能隙", "幻数", "超原子"))
    ):
        recipes.append("electronic")
    if any(k in user_text for k in ("磁", "自旋")):
        recipes.append("magnetism")
    if "光电子能谱" in user_text or "VDE" in user_text:
        recipes.append("pes")
    if "电离能" in user_text or "亲和能" in user_text:
        recipes.append("ionization")
    if "尺寸演化" in user_text:
        recipes.append("size_evolution")
    if not recipes:
        recipes = ["stability"]

    acc = "fast" if "快速" in user_text else ("high" if "高精度" in user_text else "standard")
    budget_m = re.search(r"预算\s*(\d+(?:\.\d+)?)\s*小时", user_text)
    budget = float(budget_m.group(1)) if budget_m else None

    charges: Any = "auto"
    if "电荷 -1" in user_text or "阴离子" in user_text and "光电子能谱" not in user_text:
        charges = [-1]
    elif "电荷 +1" in user_text or "阳离子" in user_text:
        charges = [1]

    if not comp or any(el not in _VALID_ELS for el in comp):
        payload = ParsedIntent(
            needs_clarification=True,
            clarification_question="未能识别完整元素符号与原子数，请补充。",
            request=None,
        )
    else:
        req = ResearchRequest(
            composition=comp,
            recipes=recipes,
            accuracy=acc,  # type: ignore[arg-type]
            time_budget_hours=budget,
            charges=charges,
        )
        payload = ParsedIntent(needs_clarification=False, request=req)
    return ModelResponse(
        parts=[ToolCallPart("final_result", json.loads(payload.model_dump_json()))]
    )


def test_50_instructions_catalog_and_eval_pipeline() -> None:
    cases = yaml.safe_load(INSTRUCTIONS_YAML.read_text(encoding="utf-8"))["instructions"]
    assert len(cases) == 50
    assert sum(1 for c in cases if c["needs_clarification"]) >= 8

    metrics = run_eval(INSTRUCTIONS_YAML, model=FunctionModel(_mock_rule_nl_model))
    assert metrics.total == 50
    assert metrics.accuracy >= 0.90, f"Eval accuracy {metrics.accuracy:.2f}: {metrics.failures}"


def test_auto_plan_single_turn_broad_proposals_and_multi_turn() -> None:
    # 1. Single-turn complete prompt -> directly builds deterministic CalcPlan
    direct = auto_plan_from_natural_language(
        "研究 Al6-13Ni 的稳定性和磁性，标准精度，预算 12 小时",
        model=FunctionModel(_mock_rule_nl_model),
    )
    assert direct.intent.needs_clarification is False
    assert direct.plan is not None
    assert direct.plan.estimated_jobs > 0
    assert direct.project_title == "Al6-13Ni"

    # 2. Broad prompt with family + multi-turn follow-up + one-click proposals
    def _broad_and_followup_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt_txt = ""
        for m in messages:
            for p in m.parts:
                if getattr(p, "part_kind", "") == "user-prompt":
                    prompt_txt = str(p.content)

        if "Lu@Au5" in prompt_txt and "此前多轮对话记录" in prompt_txt:
            payload = ParsedIntent(
                needs_clarification=False,
                suggested_title="Lu@Au₅ 电子结构刚性研究",
                request=ResearchRequest(
                    composition={"Lu": 1, "Au": 5},
                    recipes=["electronic", "stability"],
                    charges=[0],
                    accuracy="standard",
                ),
            )
        else:
            payload = ParsedIntent(
                needs_clarification=True,
                clarification_question="请指定具体的重镧系元素（如 Lu 或 Yb），或直接选用下方推荐方案。",
                suggested_proposals=[
                    ProposedPlan(
                        title="Lu@Au₅ 闭壳层基准体系",
                        rationale="Lu³⁺ 闭壳层 4f¹⁴ 可消除强静态相关，聚焦 Au₅ 环电子刚性。",
                        request=ResearchRequest(
                            composition={"Lu": 1, "Au": 5},
                            recipes=["electronic", "stability"],
                            charges=[0],
                        ),
                    ),
                    ProposedPlan(
                        title="Yb@Au₅ 对照体系",
                        rationale="对比相邻重镧系元素掺杂对能隙与几何刚性的调制。",
                        request=ResearchRequest(
                            composition={"Yb": 1, "Au": 5},
                            recipes=["electronic", "stability"],
                            charges=[0],
                        ),
                    ),
                ],
            )
        return ModelResponse(
            parts=[ToolCallPart("final_result", json.loads(payload.model_dump_json()))]
        )

    mock_m = FunctionModel(_broad_and_followup_model)
    broad = auto_plan_from_natural_language(
        "重镧系内嵌金五环超原子中的“电子结构刚性”",
        model=mock_m,
    )
    assert broad.plan is None
    assert broad.intent.needs_clarification is True
    assert len(broad.intent.suggested_proposals) == 2
    for prop in broad.intent.suggested_proposals:
        built = build_plan(prop.request)
        assert built.estimated_jobs > 0

    followup = auto_plan_from_natural_language(
        "就用 Lu@Au5，中性",
        history=[
            ("user", "重镧系内嵌金五环超原子中的“电子结构刚性”"),
            ("assistant", broad.intent.clarification_question or ""),
        ],
        model=mock_m,
    )
    assert followup.intent.needs_clarification is False
    assert followup.plan is not None
    assert followup.project_title == "Lu@Au₅ 电子结构刚性研究"
    assert followup.plan.request.composition == {"Lu": 1, "Au": 5}
    assert followup.plan.request.charges == [0]


def test_nl_planner_retries_on_wildcard_element_and_invalid_recipe() -> None:
    # 1. Attempt 1 outputs wildcard "Ln" -> rejected by Pydantic -> Attempt 2 expands 8 heavy lanthanides
    wildcard_calls = {"n": 0}
    heavy_ln = ["Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"]

    def wildcard_then_expand(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        wildcard_calls["n"] += 1
        if wildcard_calls["n"] == 1:
            # Raw JSON dict simulating LLM emitting invalid wildcard "Ln"
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "final_result",
                        {
                            "needs_clarification": False,
                            "request": {
                                "composition": {"Ln": 1, "Au": 5},
                                "recipes": ["electronic", "stability"],
                            },
                        },
                    )
                ]
            )
        proposals = [
            ProposedPlan(
                title=f"{el}@Au₅ 电子结构研究",
                rationale=f"对比 {el} 4f 局域电子与 Au₅ 壳层的耦合。",
                request=ResearchRequest(
                    composition={el: 1, "Au": 5},
                    recipes=["electronic", "stability"],
                    charges=[0],
                ),
            )
            for el in heavy_ln
        ]
        payload = ParsedIntent(
            needs_clarification=True,
            clarification_question="已为你展开全部 8 个重镧系独立体系方案，可直接一键批量提交或逐个点击审核。",
            request=None,
            suggested_proposals=proposals,
        )
        return ModelResponse(
            parts=[ToolCallPart("final_result", json.loads(payload.model_dump_json()))]
        )

    outcome = auto_plan_from_natural_language(
        "所有重镧系元素都考虑",
        history=[("user", "重镧系内嵌金五环超原子中的“电子结构刚性”")],
        model=FunctionModel(wildcard_then_expand),
    )
    assert wildcard_calls["n"] == 2
    assert outcome.plan is None
    assert outcome.intent.needs_clarification is True
    assert len(outcome.intent.suggested_proposals) == 8
    for prop in outcome.intent.suggested_proposals:
        assert build_plan(prop.request).estimated_jobs > 0

    # 2. Attempt 1 emits valid element but invalid recipe -> output_validator ModelRetry -> Attempt 2 fixes
    recipe_calls = {"n": 0}

    def bad_recipe_then_fix(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        recipe_calls["n"] += 1
        if recipe_calls["n"] == 1:
            payload = ParsedIntent(
                needs_clarification=False,
                request=ResearchRequest(
                    composition={"Tm": 1, "Au": 5},
                    recipes=["nonexistent_recipe"],
                ),
            )
        else:
            payload = ParsedIntent(
                needs_clarification=False,
                suggested_title="Tm@Au₅ 电子结构",
                request=ResearchRequest(
                    composition={"Tm": 1, "Au": 5},
                    recipes=["electronic", "stability"],
                ),
            )
        return ModelResponse(
            parts=[ToolCallPart("final_result", json.loads(payload.model_dump_json()))]
        )

    fixed = auto_plan_from_natural_language(
        "计算 Tm@Au5 的电子结构与稳定性",
        model=FunctionModel(bad_recipe_then_fix),
    )
    assert recipe_calls["n"] == 2
    assert fixed.plan is not None
    assert fixed.plan.request.composition == {"Tm": 1, "Au": 5}

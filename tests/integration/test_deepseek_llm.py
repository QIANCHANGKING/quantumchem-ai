"""Live DeepSeek API integration & 50+50 bilingual benchmark (run with `pytest -m llm`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from qcai.config import load_settings, resolve_deepseek_key
from tests.llm_eval.eval_runner import run_eval

INSTRUCTIONS_YAML = Path(__file__).resolve().parents[1] / "llm_eval" / "instructions.yaml"
INSTRUCTIONS_EN_YAML = Path(__file__).resolve().parents[1] / "llm_eval" / "instructions_en.yaml"


@pytest.mark.llm
def test_live_deepseek_50_instructions_accuracy() -> None:
    settings = load_settings()
    api_key = resolve_deepseek_key(settings)
    if not api_key:
        pytest.skip("DeepSeek API Key not configured")

    metrics = run_eval(INSTRUCTIONS_YAML, api_key=api_key)
    assert metrics.accuracy >= 0.90, (
        f"DeepSeek instruction accuracy {metrics.accuracy:.2%} < 90%: {metrics.failures}"
    )


@pytest.mark.llm
def test_live_deepseek_50_instructions_en_accuracy() -> None:
    settings = load_settings()
    api_key = resolve_deepseek_key(settings)
    if not api_key:
        pytest.skip("DeepSeek API Key not configured")

    metrics = run_eval(INSTRUCTIONS_EN_YAML, api_key=api_key)
    assert metrics.accuracy >= 0.90, (
        f"DeepSeek English instruction accuracy {metrics.accuracy:.2%} < 90%: {metrics.failures}"
    )

"""Spike 11: Verify pydantic-ai DeepSeekProvider, tool calling, and output_validator."""

import inspect

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.deepseek import DeepSeekProvider


class PlanSummary(BaseModel):
    cluster: str
    energy_ev: float


def main() -> None:
    print("DeepSeekProvider init sig:", inspect.signature(DeepSeekProvider.__init__))
    print("DeepSeekProvider base_url:", inspect.getsource(DeepSeekProvider))

    agent: Agent[dict[str, float], PlanSummary] = Agent(
        TestModel(),
        deps_type=dict[str, float],
        output_type=PlanSummary,
        system_prompt="Return summary.",
    )

    @agent.tool
    def lookup_energy(ctx: RunContext[dict[str, float]], name: str) -> float:
        return ctx.deps.get(name, 0.0)

    @agent.output_validator
    def check_numbers(ctx: RunContext[dict[str, float]], output: PlanSummary) -> PlanSummary:
        if output.energy_ev < -1e6:
            raise ModelRetry("Invalid energy")
        return output

    result = agent.run_sync("Summarize", deps={"Al13": -3.14})
    print("TestModel structured output:", result.output)
    print("PASS: spike_11_pydantic_ai_deepseek")


if __name__ == "__main__":
    main()

"""Abstract base class for LLM provider adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Interface for configuring an LLM backend (e.g., DeepSeek via pydantic-ai)."""

    name: str

    @abstractmethod
    def build_model(self, model_name: str, api_key: str, *, base_url: str | None = None) -> Any:
        """Construct a model instance compatible with the agent layer."""

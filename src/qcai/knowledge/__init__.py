"""YAML knowledge loader for domain rules and recipe declarations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

KNOWLEDGE_DIR = Path(__file__).resolve().parent
RULES_DIR = KNOWLEDGE_DIR / "rules"


def load_rule_yaml(filename: str) -> dict[str, Any]:
    """Load a YAML knowledge file from knowledge/rules/ or knowledge/."""
    path = RULES_DIR / filename
    if not path.exists():
        path = KNOWLEDGE_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Rule file not found: {RULES_DIR / filename}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data

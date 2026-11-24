"""Research planning, rule engine, and cost estimation."""

from qcai.planner.charges import derive_charge_plan
from qcai.planner.multiplicity import derive_multiplicity_candidates
from qcai.planner.planner import (
    ReferenceJobSpec,
    build_plan,
    derive_reference_systems,
    expand_composition,
    format_plan_markdown,
    validate_geometry_sanity,
    validate_theory_consistency,
)
from qcai.planner.rule_engine import SystemFeatures, extract_system_features

__all__ = [
    "ReferenceJobSpec",
    "SystemFeatures",
    "build_plan",
    "derive_charge_plan",
    "derive_multiplicity_candidates",
    "derive_reference_systems",
    "expand_composition",
    "extract_system_features",
    "format_plan_markdown",
    "validate_geometry_sanity",
    "validate_theory_consistency",
]

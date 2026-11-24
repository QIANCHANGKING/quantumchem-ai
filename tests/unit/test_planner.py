"""Unit tests for rule engine, planner, universality test set, and `qcai plan` CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from typer.testing import CliRunner

from qcai.cli import app
from qcai.core.models import CalcSpec, Cluster, ElectronicState, ResearchRequest
from qcai.planner import (
    ReferenceJobSpec,
    build_plan,
    derive_reference_systems,
    format_plan_markdown,
    validate_geometry_sanity,
    validate_theory_consistency,
)
from qcai.programs.gaussian.writer import BasisCoverageError


@pytest.mark.parametrize(
    ("composition", "recipes", "charges", "expect_tm", "expect_ecp", "expect_f"),
    [
        ({"Na": 6}, ["stability"], "auto", False, False, False),
        ({"Li": 8}, ["electronic"], "auto", False, False, False),
        ({"B": 12}, ["stability"], "auto", False, False, False),
        ({"Al": 13}, ["electronic"], [-1], False, False, False),
        ({"Si": 10}, ["stability"], "auto", False, False, False),
        ({"Fe": 4}, ["magnetism"], "auto", True, False, False),
        ({"Co": 6}, ["magnetism"], "auto", True, False, False),
        ({"Al": 12, "Ni": 1}, ["stability", "magnetism"], "auto", True, False, False),
        ({"Pd": 6}, ["stability"], "auto", True, True, False),
        ({"Pt": 4}, ["stability"], "auto", True, True, False),
        ({"Au": 8}, ["electronic"], "auto", True, True, False),
        ({"W": 1, "Au": 12}, ["electronic"], "auto", True, True, False),
        ({"Cu": 3, "Ag": 3}, ["stability"], "auto", True, True, False),
        ({"Au": 4, "Ag": 4}, ["stability"], "auto", True, True, False),
        ({"Al": 12, "Gd": 1}, ["magnetism"], "auto", False, True, True),
    ],
)
def test_universality_planning_across_periodic_table(
    composition: dict[str, int | tuple[int, int]],
    recipes: list[str],
    charges: list[int] | str,
    expect_tm: bool,
    expect_ecp: bool,
    expect_f: bool,
) -> None:
    req = ResearchRequest(
        composition=composition,
        recipes=recipes,
        accuracy="standard",
        charges=charges,  # type: ignore[arg-type]
    )
    plan = build_plan(req)
    assert plan.estimated_jobs > 0
    assert plan.estimated_core_hours > 0

    dec_map = {d.key: d.value for d in plan.decisions}
    assert dec_map["nosymm"] is True
    if expect_tm:
        assert dec_map["scf_strategy"] == "robust"
        assert dec_map["enable_stability_check"] is True
    if expect_ecp:
        assert dec_map["ecp_handling"] == "auto_def2_ecp"
    if expect_f:
        assert dec_map["f_block_warning"] is True


def test_size_downgrade_overrides_and_budget() -> None:
    # Large cluster (>20 atoms) downgrades refinement basis from def2-TZVP to def2-SVP
    large_req = ResearchRequest(
        composition={"Al": 24},
        recipes=["stability"],
        accuracy="standard",
        time_budget_hours=2.0,
    )
    large_plan = build_plan(large_req)
    dec_map = {d.key: d.value for d in large_plan.decisions}
    assert dec_map["refinement_basis"] == "def2-SVP"
    assert "budget_adjustment" in dec_map

    # User overrides are tracked with overridden=True
    ov_req = ResearchRequest(
        composition={"Na": 6},
        recipes=["pes"],
        accuracy="standard",
        overrides={"scf_strategy": "robust", "candidate_k": 4},
    )
    ov_plan = build_plan(ov_req)
    ov_decs = {d.key: d for d in ov_plan.decisions}
    assert ov_decs["scf_strategy"].overridden is True
    assert ov_decs["scf_strategy"].value == "robust"
    assert ov_decs["candidate_k"].value == 4
    assert ov_decs["charge_states"].value == [-1, 0]


def test_validation_geometry_theory_consistency_and_basis_block() -> None:
    # Overlapping atoms
    overlap = Cluster(
        symbols=["Au", "Au"],
        positions=[(0.0, 0.0, 0.0), (0.5, 0.0, 0.0)],
        label="overlap",
    )
    assert len(validate_geometry_sanity(overlap)) >= 1
    with pytest.raises(ValueError, match="geometry"):
        build_plan(
            ResearchRequest(composition={"Au": 2}, recipes=["stability"], structures=[overlap])
        )

    # Isolated atom
    isolated = Cluster(
        symbols=["Al", "Al", "Al"],
        positions=[(0.0, 0.0, 0.0), (2.5, 0.0, 0.0), (20.0, 0.0, 0.0)],
        label="isolated",
    )
    assert any("孤立原子" in err for err in validate_geometry_sanity(isolated))

    # Axiom A4: reference system theory consistency check
    target = CalcSpec(functional="PBE0", basis="def2-TZVP", dispersion="GD3BJ", tasks=["opt"])
    refs = derive_reference_systems([{"Al": 12, "Ni": 1}], target)
    validate_theory_consistency(target, refs)
    bad_ref = ReferenceJobSpec(
        label="bad",
        stoichiometry={"Ni": 1},
        state=ElectronicState(charge=0, multiplicity=3),
        calc_spec=target.model_copy(update={"basis": "def2-SVP"}),
    )
    with pytest.raises(ValueError, match="Axiom A4"):
        validate_theory_consistency(target, [bad_ref])

    # Unsupported basis via override blocks with BasisCoverageError
    with pytest.raises(BasisCoverageError):
        build_plan(
            ResearchRequest(
                composition={"Au": 4},
                recipes=["stability"],
                overrides={"screening_basis": "6-31G*"},
            )
        )


@settings(max_examples=20, deadline=None)
@given(
    el1=st.sampled_from(["Li", "B", "Al", "Si", "Fe", "Ni", "Cu", "Pd", "Au", "Gd"]),
    el2=st.sampled_from(["Na", "C", "Al", "Co", "Ag", "Pt", "W"]),
    n1=st.integers(min_value=1, max_value=6),
    n2=st.integers(min_value=1, max_value=4),
)
def test_arbitrary_element_pair_always_produces_valid_plan(
    el1: str, el2: str, n1: int, n2: int
) -> None:
    comp = {el1: n1 + n2} if el1 == el2 else {el1: n1, el2: n2}
    plan = build_plan(ResearchRequest(composition=comp, recipes=["stability"], accuracy="fast"))
    assert plan.estimated_jobs > 0


def test_cli_plan_command(tmp_path: Path) -> None:
    out_md = tmp_path / "plan.md"
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "plan",
            "--composition",
            "Al:6-13,Ni:1",
            "--recipes",
            "stability,magnetism",
            "--accuracy",
            "standard",
            "--budget",
            "12h",
            "--out",
            str(out_md),
        ],
    )
    assert res.exit_code == 0
    assert out_md.exists()
    content = out_md.read_text(encoding="utf-8")
    assert "QuantumChem AI 计算方案书" in content
    assert "Al:6-13, Ni:1" in content
    assert "S4_refine" in content
    assert format_plan_markdown(
        build_plan(
            ResearchRequest(
                composition={"Al": (6, 13), "Ni": 1},
                recipes=["stability", "magnetism"],
                time_budget_hours=12.0,
            )
        )
    )


def test_research_request_rejects_wildcard_and_invalid_elements() -> None:
    for bad_comp in ({"Ln": 1, "Au": 5}, {"TM": 1, "Au": 5}, {"X": 2}):
        with pytest.raises(ValidationError, match="非法元素符号"):
            ResearchRequest(composition=bad_comp, recipes=["stability"])

    with pytest.raises(ValidationError, match="composition 不能为空"):
        ResearchRequest(composition={}, recipes=["stability"])

    # Valid lanthanide and transition metal compositions succeed
    assert (
        build_plan(
            ResearchRequest(composition={"Tm": 1, "Au": 5}, recipes=["electronic"])
        ).estimated_jobs
        > 0
    )

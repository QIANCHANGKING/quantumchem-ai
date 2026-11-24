"""Integration tests for VMD 3D rendering and extended Origin 2024b plots."""

from __future__ import annotations

from pathlib import Path

import pytest

from qcai.analysis import ClusterSummary, IsomerEntry, ProjectSummary, SizeEvolutionPoint
from qcai.core.models import Cluster
from qcai.renderers import RENDERERS
from qcai.renderers.spec import (
    build_isomer_ranking_spec,
    build_size_evolution_spec,
    build_spin_ladder_spec,
    build_vde_ade_spec,
)
from qcai.renderers.vmd import VmdRenderer


@pytest.mark.vmd
def test_vmd_renders_cluster_png(tmp_path: Path) -> None:
    cluster = Cluster(
        symbols=["Cu", "Al", "Al", "Al"],
        positions=[(0.0, 0.0, 0.0), (2.4, 0.0, 0.0), (1.2, 2.1, 0.0), (1.2, 0.7, 2.0)],
        label="Al3Cu",
    )
    vmd = VmdRenderer()
    outputs = vmd.render_cluster(cluster, tmp_path)
    png_path = outputs[0]
    assert png_path.suffix == ".png"
    assert png_path.exists() and png_path.stat().st_size > 1000
    assert any(p.suffix == ".tcl" for p in outputs)


@pytest.mark.origin
def test_origin_renders_summary_plots(tmp_path: Path) -> None:
    origin = RENDERERS.get("origin")
    cs = ClusterSummary(
        cluster_label="Na4",
        stoichiometry={"Na": 4},
        charge=-1,
        ground_state_job_id="na4_gs",
        ground_state_multiplicity=2,
        ground_state_energy_hartree=-648.5,
        isomers=[
            IsomerEntry(
                job_id="j1",
                label="iso1",
                charge=-1,
                multiplicity=2,
                energy_hartree=-648.5,
                rel_energy_ev=0.0,
            ),
            IsomerEntry(
                job_id="j2",
                label="iso2",
                charge=-1,
                multiplicity=4,
                energy_hartree=-648.48,
                rel_energy_ev=0.54,
            ),
        ],
        spin_ladder=[(2, 0.0), (4, 0.54)],
        valence_electrons=5,
        jellium_magic=False,
        magnetic_moment_mu_b=1.0,
        vde_ev=1.42,
        ade_ev=1.28,
    )
    ps = ProjectSummary(
        project_id="na_evo",
        clusters={"Na4": cs},
        size_evolution=[
            SizeEvolutionPoint(
                size_n=3,
                cluster_label="Na3",
                energy_hartree=-486.2,
                binding_energy_ev_per_atom=0.8,
                delta2_e_ev=-0.2,
                homo_lumo_gap_ev=1.2,
                magnetic_moment_mu_b=1.0,
            ),
            SizeEvolutionPoint(
                size_n=4,
                cluster_label="Na4",
                energy_hartree=-648.5,
                binding_energy_ev_per_atom=1.0,
                delta2_e_ev=0.4,
                homo_lumo_gap_ev=1.8,
                magnetic_moment_mu_b=0.0,
            ),
        ],
    )
    for spec in (
        build_spin_ladder_spec(cs),
        build_isomer_ranking_spec(cs),
        build_size_evolution_spec(ps),
        build_vde_ade_spec(cs, experimental={"VDE": 1.45, "ADE": 1.30}),
    ):
        files = origin.render(spec, tmp_path)
        assert len(files) == 3
        assert all(p.exists() and p.stat().st_size > 0 for p in files)

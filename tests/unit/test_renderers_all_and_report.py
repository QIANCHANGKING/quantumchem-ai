"""Unit tests for all 10 Matplotlib figure kinds, py3Dmol, VMD Tcl, and PDF report."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from qcai.analysis import (
    ClusterSummary,
    IsomerEntry,
    ProjectSummary,
    SizeEvolutionPoint,
)
from qcai.cli import app
from qcai.core.models import Cluster, OrbitalComposition, PDOSData
from qcai.programs.gaussian.parser import parse_gaussian_log
from qcai.renderers import RENDERERS, build_figure_spec
from qcai.renderers.spec import (
    build_isomer_ranking_spec,
    build_levels_compare_spec,
    build_orb_comp_spec,
    build_pdos_spec,
    build_size_evolution_spec,
    build_spin_ladder_spec,
    build_vde_ade_spec,
)
from qcai.renderers.vmd import build_vmd_tcl
from qcai.renderers.web3d import align_cluster_principal_axes, build_py3dmol_html

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "data" / "golden"
CCLIB_DIR = Path(__file__).resolve().parents[1] / "data" / "cclib"


def test_all_10_figure_kinds_mpl(tmp_path: Path) -> None:
    mpl = RENDERERS.get("mpl")
    r_open = parse_gaussian_log(CCLIB_DIR / "dvb_un_sp.log")
    r_closed = parse_gaussian_log(CCLIB_DIR / "dvb_sp.out")

    specs = [
        build_figure_spec(r_open, "levels"),
        build_levels_compare_spec([r_closed, r_open]),
        build_figure_spec(r_open, "spin"),
        build_figure_spec(r_open, "dos"),
        build_pdos_spec(
            "al12cu",
            PDOSData(
                energies_ev=[-4.0, -2.0, 0.0, 2.0],
                tdos_alpha=[0.1, 0.8, 0.4, 0.2],
                tdos_beta=[-0.1, -0.7, -0.3, -0.2],
                pdos_series={"Al_alpha": [0.05, 0.5, 0.2, 0.1], "Cu_alpha": [0.05, 0.3, 0.2, 0.1]},
            ),
            homo_ev=-1.0,
        ),
        build_orb_comp_spec(
            "al12cu",
            [
                OrbitalComposition(
                    mo_index=92,
                    spin="alpha",
                    energy_ev=-5.1,
                    contributions={
                        "shell_s": 20.0,
                        "shell_p": 75.0,
                        "shell_d": 5.0,
                        "shell_f": 0.0,
                    },
                ),
                OrbitalComposition(
                    mo_index=93,
                    spin="alpha",
                    energy_ev=-3.2,
                    contributions={
                        "shell_s": 15.0,
                        "shell_p": 80.0,
                        "shell_d": 5.0,
                        "shell_f": 0.0,
                    },
                ),
            ],
        ),
        build_figure_spec(r_open, "s2"),
    ]

    c_na4 = Cluster(
        symbols=["Na", "Na", "Na", "Na"],
        positions=[(0, 0, 0), (3, 0, 0), (1.5, 2.6, 0), (1.5, 0.9, 2.4)],
        label="Na4",
    )
    cs = ClusterSummary(
        cluster_label="Na4",
        stoichiometry={"Na": 4},
        charge=-1,
        ground_state_job_id="na4_gs",
        ground_state_multiplicity=2,
        ground_state_energy_hartree=-648.5,
        ground_state_geometry=c_na4,
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
    specs.extend(
        [
            build_spin_ladder_spec(cs),
            build_isomer_ranking_spec(cs),
            build_size_evolution_spec(ps),
            build_vde_ade_spec(cs, experimental={"VDE": 1.45, "ADE": 1.30}),
        ]
    )

    for spec in specs:
        out = mpl.render(spec, tmp_path)
        assert len(out) == 2
        assert all(p.exists() and p.stat().st_size > 1000 for p in out)


def test_web3d_py3dmol_and_vmd_tcl_generation(tmp_path: Path) -> None:
    cluster = Cluster(
        symbols=["Cu", "Al", "Al", "Al"],
        positions=[(10.0, 2.0, 1.0), (12.4, 2.0, 1.0), (11.2, 4.1, 1.0), (11.2, 2.7, 3.0)],
        label="Al3Cu",
    )
    aligned = align_cluster_principal_axes(cluster)
    assert aligned.positions[0] != cluster.positions[0]

    html = build_py3dmol_html(cluster)
    assert "3Dmol" in html or "addModel" in html

    xyz = tmp_path / "c.xyz"
    tga = tmp_path / "c.tga"
    tcl = build_vmd_tcl(xyz, tga, dopant_indices=[0])
    assert "Orthographic" in tcl
    assert "render TachyonInternal" in tcl
    assert "index 0" in tcl
    assert "quit" in tcl


def test_cli_report_on_golden_samples_generates_pdf_and_html(tmp_path: Path) -> None:
    out_dir = tmp_path / "golden_report"
    runner = CliRunner()
    res = runner.invoke(
        app,
        ["report", str(GOLDEN_DIR), "--renderer", "mpl", "--out-dir", str(out_dir)],
    )
    assert res.exit_code == 0, res.stdout
    html_path = out_dir / "report.html"
    pdf_path = out_dir / "report.pdf"
    assert html_path.exists()
    assert pdf_path.exists() and pdf_path.stat().st_size > 15000

    html = html_path.read_text(encoding="utf-8")
    assert "QuantumChem AI" in html
    assert "<svg" in html
    assert "Gaussian 16" in html
    assert "ABNORMAL_TERMINATION" in html  # fault_scf_noconv surfaced truthfully
    assert "imaginary_freq" in html  # custodian repair record surfaced truthfully
    assert "Computational Methods" in html

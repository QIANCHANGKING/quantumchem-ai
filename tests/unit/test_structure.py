"""Unit tests for P4 structure generation, dopant site enumeration, and deduplication."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ase.calculators.lj import LennardJones

from qcai.core.models import Cluster
from qcai.core.physics import EV_TO_HA
from qcai.interfaces import GENERATORS
from qcai.remote.resources import ServerProbe, SoftwareStatus
from qcai.structure import (
    ABClusterGenerator,
    ScoredCluster,
    cluster_rmsd,
    deduplicate_clusters,
    enumerate_dopant_sites,
    read_abcluster_lm_dir,
    read_clusters_from_file,
    select_generator_name,
)
from qcai_remote.search import run_ase_ga_search


def _make_octahedron(symbol: str = "Au", d: float = 2.0) -> Cluster:
    coords = [
        (d, 0.0, 0.0),
        (-d, 0.0, 0.0),
        (0.0, d, 0.0),
        (0.0, -d, 0.0),
        (0.0, 0.0, d),
        (0.0, 0.0, -d),
    ]
    return Cluster(symbols=[symbol] * 6, positions=coords, label=f"{symbol}6_Oh")


def _make_icosahedron(symbol: str = "Al", r: float = 2.6, *, centered: bool = True) -> Cluster:
    phi = (1.0 + np.sqrt(5.0)) / 2.0
    raw = [
        (0, 1, phi),
        (0, -1, phi),
        (0, 1, -phi),
        (0, -1, -phi),
        (1, phi, 0),
        (-1, phi, 0),
        (1, -phi, 0),
        (-1, -phi, 0),
        (phi, 0, 1),
        (-phi, 0, 1),
        (phi, 0, -1),
        (-phi, 0, -1),
    ]
    scale = r / float(np.linalg.norm(raw[0]))
    verts = [(float(c[0] * scale), float(c[1] * scale), float(c[2] * scale)) for c in raw]
    if centered:
        coords = [(0.0, 0.0, 0.0), *verts]
        return Cluster(symbols=[symbol] * 13, positions=coords, label=f"{symbol}13_Ih")
    return Cluster(symbols=[symbol] * 12, positions=verts, label=f"{symbol}12_cage")


def _rotate_translate_permute(c: Cluster, seed: int = 7) -> Cluster:
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    shift = rng.uniform(-8.0, 8.0, size=3)
    perm = rng.permutation(len(c.symbols))
    coords = (np.asarray(c.positions) @ q.T + shift)[perm]
    syms = [c.symbols[i] for i in perm]
    pos = [(float(x), float(y), float(z)) for x, y, z in coords]
    return Cluster(symbols=syms, positions=pos, label=f"{c.label}_perm")


def test_dopant_site_enumeration_symmetry_counts() -> None:
    oh = _make_octahedron("Au")
    # Single substitution on Oh octahedron -> exactly 1 site (+ endohedral if hollow, test without endohedral first)
    single_oh = enumerate_dopant_sites(oh, "Ag", n_dopants=1, try_endohedral=False)
    assert len(single_oh) == 1
    assert single_oh[0].symbols.count("Ag") == 1

    # Double substitution on Oh octahedron -> exactly 2 sites (adjacent/cis vs opposite/trans)
    double_oh = enumerate_dopant_sites(oh, "Ag", n_dopants=2)
    assert len(double_oh) == 2

    # Centered icosahedron Al13 -> exactly 2 sites (center + surface)
    ih_centered = _make_icosahedron("Al", centered=True)
    single_ih = enumerate_dopant_sites(ih_centered, "Ni", n_dopants=1, try_endohedral=True)
    assert len(single_ih) == 2

    # Hollow icosahedral cage Au12 -> 1 surface substitution + 1 endohedral W@Au12
    ih_hollow = _make_icosahedron("Au", r=2.75, centered=False)
    doped_hollow = enumerate_dopant_sites(ih_hollow, "W", n_dopants=1, try_endohedral=True)
    assert len(doped_hollow) == 2
    assert any(len(c.symbols) == 13 and c.symbols[0] == "W" for c in doped_hollow)


def test_deduplication_rotation_translation_permutation_and_window() -> None:
    # Test both symmetric Ih and asymmetric bimetallic cluster
    base = Cluster(
        symbols=["Al", "Al", "Al", "Ni", "Cu", "Cu"],
        positions=[
            (0.0, 0.0, 0.0),
            (2.4, 0.2, 0.0),
            (1.1, 2.3, 0.4),
            (-1.5, 1.4, -0.6),
            (0.5, -2.0, 0.9),
            (-1.8, -1.2, 1.3),
        ],
        label="base",
    )
    dup = _rotate_translate_permute(base, seed=123)
    assert cluster_rmsd(base, dup) < 1e-8

    oh = _make_octahedron("Au")
    oh_dup = _rotate_translate_permute(oh, seed=456)
    assert cluster_rmsd(oh, oh_dup) < 1e-8

    distinct = Cluster(
        symbols=list(base.symbols),
        positions=[
            (0.0, 0.0, 0.0),
            (2.5, 0.0, 0.0),
            (5.0, 0.0, 0.0),
            (7.5, 0.0, 0.0),
            (1.2, 2.2, 0.0),
            (3.7, 2.2, 0.0),
        ],
        label="distinct",
    )
    too_high = ScoredCluster(cluster=distinct, energy_hartree=-10.0 + 2.5 * EV_TO_HA)
    cands = [
        ScoredCluster(cluster=base, energy_hartree=-10.0),
        ScoredCluster(cluster=dup, energy_hartree=-9.99),
        ScoredCluster(cluster=distinct, energy_hartree=-9.95),
        too_high,
    ]
    kept = deduplicate_clusters(cands, energy_window_ev=1.5, top_k=5)
    assert [k.cluster.label for k in kept] == ["base", "distinct"]


def test_abcluster_input_generation_lm_reader_and_ase_ga_fallback(tmp_path: Path) -> None:
    assert "abcluster" in GENERATORS
    assert "ase_ga" in GENERATORS

    inp, sh = ABClusterGenerator.build_isomer_files(
        {"Al": 4, "Ni": 1}, tmp_path / "abc", max_calcs=30, charge=0, multiplicity=2
    )
    assert "Al 4 Ni 1" in inp.read_text(encoding="utf-8")
    assert "--uhf 1" in sh.read_text(encoding="utf-8")

    # Simulate ABCluster LM directory output
    lm_dir = tmp_path / "abc" / "abc-LM"
    lm_dir.mkdir()
    (lm_dir / "0.xyz").write_text("2\n   -5.12345\nAl 0 0 0\nNi 2.3 0 0\n", encoding="utf-8")
    (lm_dir / "1.xyz").write_text("2\n   -5.00100\nAl 0 0 0\nNi 2.6 0 0\n", encoding="utf-8")
    lm_items = read_abcluster_lm_dir(lm_dir)
    assert len(lm_items) == 2
    assert lm_items[0].energy_hartree == pytest.approx(-5.12345)

    # Probe-based generator selection
    probe_abc = ServerProbe(software={"abcluster_isomer": SoftwareStatus(available=True)})
    assert select_generator_name(probe_abc) == "abcluster"
    assert select_generator_name(probe_abc, has_imported_structures=True) == "import"
    assert select_generator_name(ServerProbe(software={})) == "ase_ga"

    # Run ASE-GA fallback locally with LennardJones mock calculator
    out_xyz = tmp_path / "ga_out" / "candidates.xyz"
    run_ase_ga_search(
        {"Ar": 4},
        out_xyz,
        population_size=4,
        n_generations=1,
        calculator=LennardJones(),
    )
    assert out_xyz.exists()
    ga_items = read_clusters_from_file(out_xyz)
    assert len(ga_items) >= 4
    assert all(sc.energy_hartree is not None for sc in ga_items)

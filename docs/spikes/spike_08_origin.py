"""Spike 08: Verify originpro driving Origin 2024b hidden in background."""

import time
from pathlib import Path

import originpro as op


def main() -> None:
    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "origin_spike.png"
    svg_path = out_dir / "origin_spike.svg"
    opju_path = out_dir / "origin_spike.opju"
    for p in (png_path, svg_path, opju_path):
        if p.exists():
            p.unlink()

    t0 = time.perf_counter()
    op.set_show(False)
    op.new()
    wks = op.new_sheet("w", "SpikeData")
    wks.from_list(0, [1.0, 2.0, 3.0, 4.0], "Size n")
    wks.from_list(1, [2.10, 2.45, 2.38, 2.62], "Eb (eV)")

    graph = op.new_graph(template="line")
    gl = graph[0]
    plot = gl.add_plot(wks, 1, 0)
    plot.color = "#1f77b4"
    gl.rescale()

    graph.save_fig(str(png_path), type="png", width=1200)
    graph.save_fig(str(svg_path), type="svg")
    op.save(str(opju_path))
    op.exit()
    elapsed = time.perf_counter() - t0

    print(f"Elapsed: {elapsed:.2f}s")
    print(f"PNG: {png_path.exists()} ({png_path.stat().st_size if png_path.exists() else 0} bytes)")
    print(f"SVG: {svg_path.exists()} ({svg_path.stat().st_size if svg_path.exists() else 0} bytes)")
    print(f"OPJU: {opju_path.exists()} ({opju_path.stat().st_size if opju_path.exists() else 0} bytes)")
    assert png_path.exists() and png_path.stat().st_size > 0
    assert svg_path.exists() and svg_path.stat().st_size > 0
    print("PASS: spike_08_origin")


if __name__ == "__main__":
    main()

"""Spike 09: Verify Windows VMD batch rendering with TachyonInternal."""

import subprocess
import time
import tomllib
from pathlib import Path


def get_vmd_exe() -> Path:
    cfg_path = Path(__file__).resolve().parents[2] / "config" / "settings.toml"
    data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    return Path(data["vmd"]["executable"])


def main() -> None:
    vmd_exe = get_vmd_exe()
    assert vmd_exe.exists(), f"VMD not found at {vmd_exe}"

    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    xyz_path = out_dir / "au6.xyz"
    tcl_path = out_dir / "render.tcl"
    tga_path = out_dir / "au6.tga"
    if tga_path.exists():
        tga_path.unlink()

    xyz_path.write_text(
        "6\nAu6 octahedron\n"
        "Au  2.0  0.0  0.0\n"
        "Au -2.0  0.0  0.0\n"
        "Au  0.0  2.0  0.0\n"
        "Au  0.0 -2.0  0.0\n"
        "Au  0.0  0.0  2.0\n"
        "Au  0.0  0.0 -2.0\n",
        encoding="utf-8",
    )

    tcl = f"""
mol new {{{xyz_path.as_posix()}}} type xyz waitfor all
display projection Orthographic
color Display Background white
axes location Off
mol modstyle 0 0 CPK 1.0 0.3 20 20
render TachyonInternal {{{tga_path.as_posix()}}}
quit
"""
    tcl_path.write_text(tcl.strip() + "\n", encoding="utf-8")

    print(f"Testing VMD -dispdev text with {vmd_exe}...")
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(vmd_exe), "-dispdev", "text", "-e", str(tcl_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    dt = time.perf_counter() - t0
    print(f"-dispdev text exit={proc.returncode} in {dt:.2f}s, tga exists={tga_path.exists()}")

    if not tga_path.exists() or tga_path.stat().st_size == 0:
        print("Trying minimized window mode with -e ...")
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 6  # SW_MINIMIZE
        t1 = time.perf_counter()
        proc2 = subprocess.run(
            [str(vmd_exe), "-e", str(tcl_path)],
            startupinfo=si,
            capture_output=True,
            text=True,
            timeout=30,
        )
        dt2 = time.perf_counter() - t1
        print(f"minimized exit={proc2.returncode} in {dt2:.2f}s, tga exists={tga_path.exists()}")

    assert tga_path.exists() and tga_path.stat().st_size > 0
    print(f"Rendered image size: {tga_path.stat().st_size} bytes")
    print("PASS: spike_09_vmd")


if __name__ == "__main__":
    main()

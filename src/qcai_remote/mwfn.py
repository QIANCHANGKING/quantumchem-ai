"""Server-side Multiwfn batch runner hooked into qcai_remote.run_job."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def run_multiwfn_template(
    fchk_path: Path,
    stdin_text: str,
    out_log: Path,
    *,
    extra_rename: dict[str, str] | None = None,
) -> Path:
    """Run Multiwfn on `fchk_path` with `stdin_text` and write stdout/stderr to `out_log`."""
    exe = shutil.which("Multiwfn") or shutil.which("Multiwfn_noGUI")
    if exe is None:
        raise RuntimeError("Multiwfn executable not found in PATH")
    work_dir = fchk_path.parent
    proc = subprocess.run(
        [exe, fchk_path.name],
        input=stdin_text,
        cwd=work_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out_log.write_text(proc.stdout + ("\n" + proc.stderr if proc.stderr else ""), encoding="utf-8")
    if extra_rename:
        for src_name, dst_name in extra_rename.items():
            src = work_dir / src_name
            if src.exists():
                src.replace(work_dir / dst_name)
    return out_log

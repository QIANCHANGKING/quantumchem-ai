"""Deploy qcai_remote package and verify/install micromamba environment on server."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from qcai.remote.resources import ResourceManager, ServerProbe
from qcai.remote.ssh import SSHClient


def local_qcai_remote_dir() -> Path:
    """Return local path to `src/qcai_remote`."""
    return Path(__file__).resolve().parents[2] / "qcai_remote"


def sync_qcai_remote(ssh: SSHClient) -> PurePosixPath:
    """Upload `src/qcai_remote/*.py` to `<work_root>/_qcai_remote/qcai_remote/`."""
    pkg_parent = ssh.work_root / "_qcai_remote"
    remote_pkg = pkg_parent / "qcai_remote"
    ssh.ensure_dir(remote_pkg)

    local_dir = local_qcai_remote_dir()
    for py_file in sorted(local_dir.glob("*.py")):
        ssh.upload_file(py_file, remote_pkg / py_file.name)
    return pkg_parent


def deploy_and_probe(
    ssh: SSHClient,
    *,
    install_env: bool = False,
) -> tuple[ServerProbe, str | None]:
    """Sync qcai_remote, optionally ensure micromamba `qcai` env, and probe server."""
    py_exe = ssh.locate_qcai_python()
    if py_exe is None and install_env:
        install_res = ssh.install_micromamba_env()
        if install_res.exit_code != 0:
            raise RuntimeError(
                f"micromamba installation failed: {install_res.stderr or install_res.stdout}"
            )
        py_exe = ssh.locate_qcai_python()

    pkg_parent = sync_qcai_remote(ssh)
    probe_res = ssh.run_probe(pkg_parent, py_exe)
    if probe_res.exit_code != 0:
        raise RuntimeError(
            f"Remote probe failed (exit={probe_res.exit_code}): "
            f"{probe_res.stderr or probe_res.stdout}"
        )
    raw = json.loads(probe_res.stdout)
    return ResourceManager.from_raw_dict(raw), py_exe

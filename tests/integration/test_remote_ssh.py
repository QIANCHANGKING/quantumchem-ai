"""Integration tests against real SSH server (run with `pytest -m remote`)."""

from __future__ import annotations

import pytest

from qcai.config import load_settings
from qcai.remote import ResourceManager, SSHClient
from qcai.remote.deploy import deploy_and_probe


@pytest.mark.remote
def test_remote_deploy_and_probe() -> None:
    settings = load_settings()
    if not settings.ssh.host:
        pytest.skip("SSH settings not configured")
    ssh = SSHClient(settings.ssh)
    try:
        probe, py_exe = deploy_and_probe(ssh, install_env=False)
        assert py_exe is not None
        assert probe.physical_cores >= 1
        assert probe.software["g16"].available is True
        assert probe.software["Multiwfn"].available is True
        assert probe.python_packages["custodian"] is not None
        alloc = ResourceManager().plan(probe)
        assert alloc.nproc_per_job >= 1
        assert alloc.max_concurrent_jobs >= 1
    finally:
        ssh.close()

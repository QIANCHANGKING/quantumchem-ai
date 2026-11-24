"""Smoke tests for P0 environment verification."""

from typer.testing import CliRunner

from qcai import __version__
from qcai.cli import app


def test_version_command() -> None:
    """Verify CLI entrypoint responds with package version."""
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout

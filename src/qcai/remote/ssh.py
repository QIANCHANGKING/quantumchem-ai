"""Whitelisted SSH / SFTP client built on fabric with strict work_root isolation."""

from __future__ import annotations

import posixpath
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar

from fabric import Connection

from qcai.config import SSHSettings

_T = TypeVar("_T")


class SecurityError(RuntimeError):
    """Raised when a remote path or command violates security policy."""


@dataclass(frozen=True)
class CommandResult:
    """Result of a whitelisted remote command."""

    exit_code: int
    stdout: str
    stderr: str


def validate_remote_path(
    remote_path: str | PurePosixPath,
    work_root: str | PurePosixPath,
    *,
    allow_root: bool = True,
) -> PurePosixPath:
    """Ensure remote_path is absolute and strictly confined within work_root."""
    raw_root = str(work_root).strip()
    raw_target = str(remote_path).strip()
    if not raw_root.startswith("/") or not raw_target.startswith("/"):
        raise SecurityError(
            f"Remote paths must be absolute POSIX paths: root={raw_root!r}, target={raw_target!r}"
        )
    norm_root = posixpath.normpath(raw_root)
    norm_target = posixpath.normpath(raw_target)
    if norm_target == norm_root:
        if not allow_root:
            raise SecurityError(f"Operation forbidden on work_root itself: {norm_root!r}")
        return PurePosixPath(norm_target)
    prefix = "/" if norm_root == "/" else f"{norm_root}/"
    if not norm_target.startswith(prefix):
        raise SecurityError(f"Path {norm_target!r} escapes configured work_root {norm_root!r}")
    return PurePosixPath(norm_target)


class SSHClient:
    """Whitelisted SSH/SFTP wrapper; never exposes raw arbitrary shell execution."""

    def __init__(self, settings: SSHSettings, *, connection: Any = None) -> None:
        if not settings.work_root:
            raise ValueError("ssh.work_root must be configured")
        self.work_root = PurePosixPath(posixpath.normpath(settings.work_root))
        self._settings = settings
        self._conn = connection
        self._owns_connection = connection is None

    def _get_connection(self) -> Any:
        if self._conn is not None:
            if self._owns_connection:
                transport = getattr(self._conn, "transport", None)
                if transport is not None and not transport.is_active():
                    self.close()
            if self._conn is not None:
                return self._conn
        connect_kwargs: dict[str, Any] = {}
        if self._settings.key_path:
            key = str(Path(self._settings.key_path).expanduser())
            connect_kwargs["key_filename"] = key
        self._conn = Connection(
            host=self._settings.host,
            user=self._settings.username or None,
            port=self._settings.port,
            connect_kwargs=connect_kwargs,
            connect_timeout=15,
        )
        return self._conn

    @staticmethod
    def _is_transient_ssh_error(exc: BaseException) -> bool:
        if isinstance(exc, (OSError, EOFError)):
            return True
        return type(exc).__module__.startswith("paramiko")

    def _run_with_reconnect(self, fn: Callable[[Any], _T]) -> _T:
        for attempt in range(2):
            conn = self._get_connection()
            try:
                result = fn(conn)
                if self._owns_connection:
                    transport = getattr(conn, "transport", None)
                    if transport is not None and transport.is_active():
                        try:
                            transport.set_keepalive(30)
                        except Exception:
                            pass
                return result
            except Exception as exc:
                if attempt == 0 and self._owns_connection and self._is_transient_ssh_error(exc):
                    self.close()
                    continue
                raise
        raise AssertionError("unreachable")

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def _exec_whitelisted(self, cmd: str, *, warn: bool = True) -> CommandResult:
        res = self._run_with_reconnect(
            lambda conn: conn.run(cmd, hide=True, warn=warn, in_stream=False)
        )
        return CommandResult(
            exit_code=int(res.exited),
            stdout=str(res.stdout),
            stderr=str(res.stderr),
        )

    def ensure_dir(self, remote_dir: str | PurePosixPath) -> PurePosixPath:
        safe = validate_remote_path(remote_dir, self.work_root)
        res = self._exec_whitelisted(f"mkdir -p {shlex.quote(str(safe))}")
        if res.exit_code != 0:
            raise RuntimeError(f"Failed to create remote dir {safe}: {res.stderr}")
        return safe

    def list_dir(self, remote_dir: str | PurePosixPath) -> list[str]:
        safe = validate_remote_path(remote_dir, self.work_root)
        res = self._exec_whitelisted(f"ls -1 {shlex.quote(str(safe))}")
        if res.exit_code != 0:
            return []
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    def upload_file(self, local_path: Path, remote_path: str | PurePosixPath) -> None:
        safe = validate_remote_path(remote_path, self.work_root, allow_root=False)
        self.ensure_dir(safe.parent)
        self._run_with_reconnect(lambda conn: conn.put(str(local_path), remote=str(safe)))

    def download_file(self, remote_path: str | PurePosixPath, local_path: Path) -> None:
        safe = validate_remote_path(remote_path, self.work_root, allow_root=False)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        existed = local_path.exists()
        try:
            self._run_with_reconnect(lambda conn: conn.get(str(safe), local=str(local_path)))
        except Exception:
            if not existed and local_path.exists():
                local_path.unlink(missing_ok=True)
            raise

    def read_remote_text(self, remote_path: str | PurePosixPath) -> str | None:
        safe = validate_remote_path(remote_path, self.work_root, allow_root=False)
        res = self._exec_whitelisted(f"cat {shlex.quote(str(safe))}")
        if res.exit_code != 0:
            return None
        return res.stdout

    def locate_qcai_python(self) -> str | None:
        cmd = (
            'for p in "$HOME/micromamba/envs/qcai/bin/python" '
            '"$HOME/.local/share/mamba/envs/qcai/bin/python" '
            '"$HOME/mambaforge/envs/qcai/bin/python" '
            '"$HOME/miniconda3/envs/qcai/bin/python"; do '
            'if [ -x "$p" ]; then echo "$p"; exit 0; fi; done; '
            "command -v micromamba >/dev/null 2>&1 && "
            "micromamba run -n qcai which python 2>/dev/null || true"
        )
        res = self._exec_whitelisted(cmd)
        out = res.stdout.strip().splitlines()
        return out[-1].strip() if out and out[-1].strip() else None

    def install_micromamba_env(self) -> CommandResult:
        """Install micromamba without root (if missing) and create `qcai` env."""
        cmd = (
            "set -e; "
            'export PATH="$HOME/.local/bin:$HOME/bin:$PATH"; '
            "if ! command -v micromamba >/dev/null 2>&1; then "
            'mkdir -p "$HOME/.local/bin"; '
            "curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest "
            '| tar -xj -C "$HOME/.local/bin" --strip-components=1 bin/micromamba; '
            "fi; "
            'export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"; '
            'if [ ! -x "$MAMBA_ROOT_PREFIX/envs/qcai/bin/python" ]; then '
            "micromamba create -y -n qcai -c conda-forge "
            "python=3.11 xtb tblite-python ase pymatgen custodian cclib psutil && "
            "micromamba run -n qcai pip install --no-deps ase-ga; "
            "fi"
        )
        return self._exec_whitelisted(cmd)

    def run_probe(
        self, remote_pkg_parent: str | PurePosixPath, python_exe: str | None
    ) -> CommandResult:
        safe_parent = validate_remote_path(remote_pkg_parent, self.work_root)
        py = shlex.quote(python_exe) if python_exe else "python3"
        cmd = "bash -lc " + shlex.quote(
            f"PYTHONPATH={shlex.quote(str(safe_parent))} {py} "
            f"-m qcai_remote.probe --work-root {shlex.quote(str(self.work_root))}"
        )
        return self._exec_whitelisted(cmd)

    def run_verify(
        self, remote_pkg_parent: str | PurePosixPath, python_exe: str | None
    ) -> CommandResult:
        safe_parent = validate_remote_path(remote_pkg_parent, self.work_root)
        py = shlex.quote(python_exe) if python_exe else "python3"
        cmd = "bash -lc " + shlex.quote(
            f"PYTHONPATH={shlex.quote(str(safe_parent))} {py} -m qcai_remote.verify"
        )
        return self._exec_whitelisted(cmd)

    def launch_background(self, remote_dir: str | PurePosixPath, submit_cmd: str) -> CommandResult:
        safe_dir = validate_remote_path(remote_dir, self.work_root, allow_root=False)
        if not submit_cmd.startswith("nohup ") or ";" in submit_cmd or "&&" in submit_cmd:
            raise SecurityError(f"Disallowed submit command: {submit_cmd!r}")
        # Group in `{ ...; }` so `cd` finishes before `&` forks the background job without an enclosing subshell holding SSH FDs.
        cmd = f"cd {shlex.quote(str(safe_dir))} && {{ {submit_cmd}; }}"
        return self._exec_whitelisted(cmd)

    def query_ps(self, ps_cmd: str) -> CommandResult:
        tokens = shlex.split(ps_cmd)
        if not tokens or tokens[0] != "ps" or "-p" not in tokens:
            raise SecurityError(f"Disallowed ps command: {ps_cmd!r}")
        p_idx = tokens.index("-p")
        if p_idx + 1 >= len(tokens):
            raise SecurityError("Missing PID in ps command")
        pids = tokens[p_idx + 1].split(",")
        if not all(pid.isdigit() for pid in pids):
            raise SecurityError(f"Invalid PID list in ps command: {pids!r}")
        return self._exec_whitelisted(ps_cmd)

    def kill_process_group(self, pid: str) -> CommandResult:
        if not pid.strip().isdigit():
            raise SecurityError(f"Invalid PID for kill: {pid!r}")
        p = pid.strip()
        return self._exec_whitelisted(f"kill -TERM -- -{p} 2>/dev/null || kill -9 {p}")

    def clean_rwf_files(self, job_dir: str | PurePosixPath) -> CommandResult:
        safe_dir = validate_remote_path(job_dir, self.work_root, allow_root=False)
        return self._exec_whitelisted(f"rm -f {shlex.quote(str(safe_dir))}/*.rwf")

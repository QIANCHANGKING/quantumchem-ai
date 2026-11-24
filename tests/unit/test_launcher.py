"""Unit tests for QuantumChem AI desktop launcher, GUI entrypoint, and shortcuts."""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from qcai.launcher import (
    _build_arg_parser,
    create_desktop_shortcut,
    get_runtime_status,
    is_qcai_web_running,
    launch_web_assistant,
    resolve_available_port,
    runtime_state_path,
    stop_web_assistant,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_resolve_available_port_skips_occupied_and_reuses_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    occupied_port = int(sock.getsockname()[1])
    try:
        monkeypatch.setattr("qcai.launcher.is_qcai_web_running", lambda host, port: False)
        port, running = resolve_available_port(occupied_port, host="127.0.0.1", max_scan=10)
        assert running is False
        assert port != occupied_port
    finally:
        sock.close()

    monkeypatch.setattr(
        "qcai.launcher.is_qcai_web_running", lambda host, port: port == occupied_port
    )
    port2, running2 = resolve_available_port(occupied_port, host="127.0.0.1", max_scan=5)
    assert (port2, running2) == (occupied_port, True)


def test_launch_reuses_existing_instance_without_duplicate_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_urls: list[str] = []
    monkeypatch.setattr("qcai.launcher.resolve_available_port", lambda *a, **kw: (8509, True))
    monkeypatch.setattr(
        "qcai.launcher.open_assistant_window",
        lambda url, app_mode=True: opened_urls.append(url),
    )

    rc = launch_web_assistant(port=8509, open_browser=True)
    assert rc == 0
    assert opened_urls == ["http://127.0.0.1:8509"]


def test_runtime_status_and_stop_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "qcai.sqlite"
    assert get_runtime_status(db_path)["running"] is False

    state_file = runtime_state_path(db_path)
    state_file.write_text(
        json.dumps(
            {"host": "127.0.0.1", "port": 8599, "streamlit_pid": 999991, "worker_pid": 999992}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("qcai.launcher.is_qcai_web_running", lambda host, port, timeout=1.0: True)
    st = get_runtime_status(db_path)
    assert st["running"] is True
    assert st["port"] == 8599

    killed: list[int] = []
    monkeypatch.setattr("qcai.launcher._kill_pid", lambda pid: killed.append(pid) or True)
    res = stop_web_assistant(db_path)
    assert res["had_state"] is True
    assert killed == [999992, 999991]
    assert not state_file.exists()


def test_windows_launchers_assets_and_shortcut_in_tmp_dir(tmp_path: Path) -> None:
    for rel in (
        "scripts/launch.bat",
        "启动量子化学助手.bat",
        "启动量子化学助手(仅界面模式).bat",
        "启动量子化学助手(模拟演示).bat",
        "停止量子化学助手.bat",
        "生成桌面快捷方式.bat",
    ):
        p = REPO_ROOT / rel
        assert p.exists(), f"Missing launcher: {p}"
        p.read_bytes().decode("ascii")

    for asset in ("assets/qcai.ico", "assets/qcai_icon.png", "assets/qcai_logo.svg"):
        ap = REPO_ROOT / asset
        assert ap.exists() and ap.stat().st_size > 100

    if sys.platform == "win32":
        lnk = create_desktop_shortcut(repo_root=REPO_ROOT, desktop_dir=tmp_path)
        assert lnk.exists()
        assert lnk.stat().st_size > 100


def test_gui_flag_crlf_shift_regression_and_direct_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _build_arg_parser().parse_args(["--gui"])
    assert args.gui is True

    # Ensure all 6 launcher .bat files use CRLF and launch.bat never shifts inside (...)
    for rel in (
        "scripts/launch.bat",
        "启动量子化学助手.bat",
        "启动量子化学助手(仅界面模式).bat",
        "启动量子化学助手(模拟演示).bat",
        "停止量子化学助手.bat",
        "生成桌面快捷方式.bat",
    ):
        raw = (REPO_ROOT / rel).read_bytes()
        assert b"\r\n" in raw, f"{rel} should use Windows CRLF line endings"
        assert b"\n" not in raw.replace(b"\r\n", b""), f"{rel} has bare LF line endings"

    launch_txt = (REPO_ROOT / "scripts/launch.bat").read_text(encoding="ascii")
    assert not re.search(r"if\s+[^()\n]*\([^)]*\bshift\b", launch_txt, flags=re.IGNORECASE)

    if sys.platform == "win32":
        res = subprocess.run(
            ["cmd", "/c", "call scripts\\launch.bat --gui --status"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0
        gui_exe = REPO_ROOT / ".venv" / "Scripts" / "qcai-app.exe"
        if gui_exe.exists():
            res2 = subprocess.run(
                [str(gui_exe), "--status"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            assert res2.returncode == 0

    # Ensure is_qcai_web_running bypasses HTTP proxies and probes loopback directly
    class _HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/_stcore/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), _HealthHandler)
    srv_port = int(server.server_address[1])
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7900")
        monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:7900")
        assert is_qcai_web_running("127.0.0.1", srv_port, timeout=1.5) is True
    finally:
        server.shutdown()
        server.server_close()

"""Desktop launcher, silent GUI app entrypoint, and runtime lifecycle manager."""

from __future__ import annotations

import argparse
import base64
import ctypes
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_EDGE_PATHS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)
DEFAULT_CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def runtime_state_path(db: Path = Path("projects/qcai.sqlite")) -> Path:
    """Return path to JSON file storing active background Streamlit/worker PIDs."""
    return db.resolve().parent / ".qcai_runtime.json"


def _launcher_log_path(db: Path = Path("projects/qcai.sqlite")) -> Path:
    return db.resolve().parent / "logs" / "qcai_launcher.log"


def _log_launcher(db: Path, msg: str) -> None:
    """Append a timestamped diagnostic message to projects/logs/qcai_launcher.log."""
    try:
        log_path = _launcher_log_path(db)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def _show_windows_error(title: str, message: str) -> None:
    """Display a Windows message box for fatal GUI launcher failures."""
    if sys.platform != "win32":
        return
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return
    try:
        windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        pass


def _safe_print(msg: str) -> None:
    if sys.stdout is not None:
        try:
            print(msg, flush=True)
        except OSError:
            pass


def is_qcai_web_running(host: str, port: int, *, timeout: float = 1.5) -> bool:
    """Return True if a Streamlit server responds HTTP 200 directly via loopback."""
    conn: http.client.HTTPConnection | None = None
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", "/_stcore/health")
        resp = conn.getresponse()
        resp.read()
        return int(resp.status) == 200
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _is_port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def resolve_available_port(
    preferred_port: int = 8501,
    host: str = "127.0.0.1",
    *,
    max_scan: int = 20,
) -> tuple[int, bool]:
    """Return (port, already_running), reusing an active Streamlit instance if present."""
    if is_qcai_web_running(host, preferred_port):
        return preferred_port, True

    for candidate in range(preferred_port, preferred_port + max_scan + 1):
        if is_qcai_web_running(host, candidate):
            return candidate, True
        if not _is_port_in_use(host, candidate):
            return candidate, False
    raise RuntimeError(
        f"No free port available in range {preferred_port}..{preferred_port + max_scan}"
    )


def wait_for_server(host: str, port: int, *, timeout: float = 40.0) -> bool:
    """Wait until Streamlit's health endpoint returns HTTP 200."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_qcai_web_running(host, port, timeout=1.0):
            return True
        time.sleep(0.35)
    return False


def _find_app_browser() -> Path | None:
    for cand in (*DEFAULT_EDGE_PATHS, *DEFAULT_CHROME_PATHS):
        if cand.exists():
            return cand
    for name in ("msedge", "chrome", "google-chrome"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def open_assistant_window(url: str, *, app_mode: bool = True) -> None:
    """Open the assistant URL in a standalone browser app window or default browser."""
    if app_mode and sys.platform == "win32":
        browser = _find_app_browser()
        if browser is not None:
            try:
                subprocess.Popen(
                    [str(browser), f"--app={url}", "--new-window", "--window-size=1400,920"]
                )
                return
            except OSError:
                pass
    webbrowser.open(url)


def _resolve_app_path() -> Path:
    app_path = _repo_root() / "web" / "app.py"
    if app_path.exists():
        return app_path
    cwd_path = Path.cwd() / "web" / "app.py"
    if cwd_path.exists():
        return cwd_path
    raise FileNotFoundError(f"未找到 Web 入口文件: {app_path}")


def _resolve_python_exe() -> str:
    """Return python.exe (preferring console python for child subprocesses cleanly)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        sibling = exe.with_name("python.exe")
        if sibling.exists():
            return str(sibling)
    venv_py = _repo_root() / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return str(exe)


def _terminate_proc(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _kill_pid(pid: int | None) -> bool:
    """Terminate a recorded background process PID cleanly."""
    if not pid or pid <= 0 or pid == os.getpid():
        return False
    if sys.platform == "win32":
        res = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )
        return res.returncode == 0
    try:
        os.kill(pid, 15)
        return True
    except OSError:
        return False


def _find_orphan_repo_pids(repo_root: Path) -> list[int]:
    """Locate stale QuantumChem AI Streamlit/worker/launcher PIDs for this repo on Windows."""
    if sys.platform != "win32":
        return []
    app_target = str((repo_root / "web" / "app.py").resolve())
    ps_script = (
        "$ErrorActionPreference = 'SilentlyContinue';\n"
        f"$appTarget = '{app_target.replace("'", "''")}';\n"
        "Get-CimInstance Win32_Process | Where-Object {\n"
        "  $nm = $_.Name;\n"
        "  $cmd = $_.CommandLine;\n"
        "  $nm -and ($nm -imatch '^(pythonw?|qcai(-web|-app)?)\\.exe$') -and\n"
        "  $cmd -and ($cmd -notmatch '--stop|--status|--create-shortcut') -and (\n"
        "    ($cmd -like ('*streamlit*run*' + $appTarget + '*')) -or\n"
        "    ($cmd -match 'qcai\\.cli\\s+worker') -or\n"
        "    ($cmd -match '-m\\s+qcai\\.launcher')\n"
        "  )\n"
        "} | Select-Object -ExpandProperty ProcessId\n"
    )
    encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
    res = subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_CREATE_NO_WINDOW,
        check=False,
    )
    if res.returncode != 0:
        return []
    self_pid = os.getpid()
    parent_pid = os.getppid()
    pids: list[int] = []
    for line in (res.stdout or "").splitlines():
        tok = line.strip()
        if tok.isdigit():
            pid = int(tok)
            if pid not in (self_pid, parent_pid):
                pids.append(pid)
    return pids


def get_runtime_status(db: Path = Path("projects/qcai.sqlite")) -> dict[str, Any]:
    """Read runtime state JSON and probe whether the recorded web port is healthy."""
    state_file = runtime_state_path(db)
    if not state_file.exists():
        return {"running": False, "state_file": str(state_file)}
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        data: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    except Exception:
        return {"running": False, "state_file": str(state_file)}
    port = int(data.get("port", 8501))
    host = str(data.get("host", "127.0.0.1"))
    data["running"] = is_qcai_web_running(host, port, timeout=1.0)
    data["state_file"] = str(state_file)
    return data


def stop_web_assistant(
    db: Path = Path("projects/qcai.sqlite"),
    *,
    include_orphans: bool = False,
) -> dict[str, Any]:
    """Stop background Streamlit and Worker processes recorded in runtime JSON."""
    state_file = runtime_state_path(db)
    stopped: list[int] = []
    had_state = state_file.exists()

    if had_state:
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        for key in ("worker_pid", "streamlit_pid"):
            pid = data.get(key)
            if isinstance(pid, int) and pid not in stopped and _kill_pid(pid):
                stopped.append(pid)
        state_file.unlink(missing_ok=True)

    if include_orphans:
        for pid in _find_orphan_repo_pids(_repo_root()):
            if pid not in stopped and _kill_pid(pid):
                stopped.append(pid)

    if stopped or had_state:
        _log_launcher(
            db, f"stop_web_assistant: include_orphans={include_orphans} stopped={stopped}"
        )
    return {"stopped_pids": stopped, "had_state": had_state}


def _write_runtime_state(
    db: Path,
    *,
    host: str,
    port: int,
    streamlit_pid: int,
    worker_pid: int | None,
    mode: str,
) -> None:
    state_file = runtime_state_path(db)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}",
        "streamlit_pid": streamlit_pid,
        "worker_pid": worker_pid,
        "mode": mode,
        "started_at": datetime.now(UTC).isoformat(),
    }
    state_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def launch_web_assistant(
    *,
    port: int = 8501,
    db: Path = Path("projects/qcai.sqlite"),
    with_worker: bool = True,
    mock: bool = False,
    app_mode: bool = True,
    open_browser: bool = True,
    silent: bool = False,
) -> int:
    """Start QuantumChem AI Web + optional background worker, opening cleanly once ready."""
    host = "127.0.0.1"
    resolved_port, already_running = resolve_available_port(port, host=host)
    url = f"http://{host}:{resolved_port}"
    _log_launcher(
        db,
        f"launch requested: port={port}->resolved={resolved_port}, already_running={already_running}, "
        f"with_worker={with_worker}, mock={mock}, app_mode={app_mode}, open_browser={open_browser}, silent={silent}",
    )

    if already_running:
        _safe_print(f"QuantumChem AI 已在运行：{url}（直接打开窗口）")
        if open_browser:
            open_assistant_window(url, app_mode=app_mode)
            _log_launcher(db, f"opened existing instance window at {url}")
        return 0

    app_path = _resolve_app_path()
    py_exe = _resolve_python_exe()
    db.parent.mkdir(parents=True, exist_ok=True)
    logs_dir = db.resolve().parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["QCAI_DB_PATH"] = str(db.resolve())

    mode_name = "mock" if (with_worker and mock) else ("full" if with_worker else "ui_only")
    cflags = _CREATE_NO_WINDOW if (silent and sys.platform == "win32") else 0

    worker_proc: subprocess.Popen[bytes] | None = None
    worker_log_fh = None
    st_log_fh = None

    if with_worker:
        w_cmd = [py_exe, "-m", "qcai.cli", "worker", "--db", str(db)]
        if mock:
            w_cmd.append("--mock")
        if silent:
            worker_log_fh = (logs_dir / "qcai_worker.log").open("ab")
            worker_proc = subprocess.Popen(
                w_cmd,
                env=env,
                stdout=worker_log_fh,
                stderr=subprocess.STDOUT,
                creationflags=cflags,
            )
        else:
            worker_proc = subprocess.Popen(w_cmd, env=env)
        mode_lbl = "本地模拟 Worker" if mock else "后台队列 Worker"
        _safe_print(f"[QuantumChem AI] 已启动 {mode_lbl} (PID={worker_proc.pid})")
    else:
        _safe_print("[QuantumChem AI] 仅启动 Web 界面（未启动后台 Worker）")

    st_cmd = [
        py_exe,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        host,
        "--server.port",
        str(resolved_port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]

    if silent:
        st_log_fh = (logs_dir / "qcai_web.log").open("ab")
        st_proc = subprocess.Popen(
            st_cmd,
            env=env,
            stdout=st_log_fh,
            stderr=subprocess.STDOUT,
            creationflags=cflags,
        )
        _write_runtime_state(
            db,
            host=host,
            port=resolved_port,
            streamlit_pid=st_proc.pid,
            worker_pid=worker_proc.pid if worker_proc else None,
            mode=mode_name,
        )
        ready = wait_for_server(host, resolved_port, timeout=45.0)
        if worker_log_fh is not None:
            worker_log_fh.close()
        if st_log_fh is not None:
            st_log_fh.close()
        _log_launcher(
            db,
            f"silent startup complete: ready={ready}, st_pid={st_proc.pid}, "
            f"worker_pid={worker_proc.pid if worker_proc else None}, url={url}",
        )
        if ready and open_browser:
            open_assistant_window(url, app_mode=app_mode)
        return 0 if ready else 1

    st_proc = subprocess.Popen(st_cmd, env=env)
    _write_runtime_state(
        db,
        host=host,
        port=resolved_port,
        streamlit_pid=st_proc.pid,
        worker_pid=worker_proc.pid if worker_proc else None,
        mode=mode_name,
    )

    if open_browser:

        def _open_when_ready() -> None:
            if wait_for_server(host, resolved_port, timeout=45.0):
                _safe_print(f"\n[QuantumChem AI] 界面已就绪：{url}")
                _safe_print("按 Ctrl+C 或直接关闭本窗口即可停止服务。\n")
                open_assistant_window(url, app_mode=app_mode)

        threading.Thread(target=_open_when_ready, daemon=True).start()

    try:
        return int(st_proc.wait())
    except KeyboardInterrupt:
        _safe_print("\n正在关闭 QuantumChem AI...")
        return 0
    finally:
        _terminate_proc(st_proc)
        _terminate_proc(worker_proc)
        runtime_state_path(db).unlink(missing_ok=True)


def create_desktop_shortcut(
    *,
    repo_root: Path | None = None,
    desktop_dir: Path | None = None,
    name: str = "QuantumChem AI 量子化学助手.lnk",
) -> Path:
    """Create a Windows Desktop .lnk shortcut pointing to the windowless GUI launcher."""
    if sys.platform != "win32":
        raise RuntimeError("Desktop shortcut creation is only supported on Windows")

    root = (repo_root or _repo_root()).resolve()
    gui_exe = root / ".venv" / "Scripts" / "qcai-app.exe"
    target = gui_exe if gui_exe.exists() else (root / "启动量子化学助手.bat")

    custom_ico = root / "assets" / "qcai.ico"
    icon = custom_ico if custom_ico.exists() else (_find_app_browser() or Path(sys.executable))

    out_clause = (
        f"$desktop = '{str(desktop_dir.resolve()).replace("'", "''")}'"
        if desktop_dir is not None
        else "$desktop = [Environment]::GetFolderPath('Desktop')"
    )
    window_style = 1 if target.suffix.lower() == ".exe" else 7
    ps_script = (
        "$ErrorActionPreference = 'Stop';\n"
        "$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false);\n"
        f"{out_clause};\n"
        f"$lnkPath = Join-Path $desktop '{name.replace("'", "''")}';\n"
        "$sh = New-Object -ComObject WScript.Shell;\n"
        "$sc = $sh.CreateShortcut($lnkPath);\n"
        f"$sc.TargetPath = '{str(target).replace("'", "''")}';\n"
        f"$sc.WorkingDirectory = '{str(root).replace("'", "''")}';\n"
        f"$sc.WindowStyle = {window_style};\n"
        "$sc.Description = 'QuantumChem AI 团簇量子化学科研助手';\n"
        f"$sc.IconLocation = '{str(icon).replace("'", "''")},0';\n"
        "$sc.Save();\n"
        "Write-Output $lnkPath\n"
    )
    encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
    res = subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_CREATE_NO_WINDOW,
        check=False,
    )
    out_txt = (res.stdout or "").strip()
    err_txt = (res.stderr or "").strip()
    if res.returncode != 0 or not out_txt:
        raise RuntimeError(f"创建桌面快捷方式失败: {err_txt or out_txt}")
    return Path(out_txt.splitlines()[-1])


def _build_arg_parser(prog: str = "qcai-web") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Launch QuantumChem AI Streamlit desktop assistant",
    )
    parser.add_argument("--port", type=int, default=8501, help="Preferred local port")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("projects/qcai.sqlite"),
        help="SQLite database path",
    )
    parser.add_argument("--no-worker", action="store_true", help="Run UI only without worker")
    parser.add_argument("--mock", action="store_true", help="Use mock job runner")
    parser.add_argument(
        "--browser-tab",
        action="store_true",
        help="Open in regular browser tab instead of standalone app window",
    )
    parser.add_argument("--no-open", action="store_true", help="Do not open browser window")
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Run background services silently without a console window (logs in projects/logs/)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Alias for --silent windowless GUI launch",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop background QuantumChem AI services and exit",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current QuantumChem AI runtime status JSON and exit",
    )
    parser.add_argument(
        "--create-shortcut",
        action="store_true",
        help="Create a Windows Desktop shortcut and exit",
    )
    return parser


def main(argv: list[str] | None = None, *, default_silent: bool = False) -> int:
    """CLI entrypoint (`qcai-web` / `python -m qcai.launcher`)."""
    args = _build_arg_parser().parse_args(argv)
    if args.create_shortcut:
        lnk = create_desktop_shortcut()
        _safe_print(f"已创建桌面快捷方式：{lnk}")
        return 0
    if args.stop:
        info = stop_web_assistant(db=args.db, include_orphans=True)
        _safe_print(f"已停止后台进程：{info['stopped_pids'] or '当前无运行中的后台服务'}")
        return 0
    if args.status:
        _safe_print(json.dumps(get_runtime_status(db=args.db), ensure_ascii=False, indent=2))
        return 0
    return launch_web_assistant(
        port=args.port,
        db=args.db,
        with_worker=not args.no_worker,
        mock=args.mock,
        app_mode=not args.browser_tab,
        open_browser=not args.no_open,
        silent=args.silent or args.gui or default_silent,
    )


def main_gui(argv: list[str] | None = None) -> int:
    """Windowless GUI entrypoint (`qcai-app.exe` on Windows)."""
    default_db = Path("projects/qcai.sqlite")
    try:
        rc = main(argv, default_silent=True)
    except Exception as exc:
        _log_launcher(default_db, f"main_gui fatal exception:\n{traceback.format_exc()}")
        _show_windows_error(
            "QuantumChem AI 启动失败",
            f"启动过程中发生异常：{exc}\n\n请查看日志：\n"
            f"{_launcher_log_path(default_db)}\n"
            f"{default_db.resolve().parent / 'logs' / 'qcai_web.log'}",
        )
        return 1
    if rc != 0:
        _log_launcher(default_db, f"main_gui returned non-zero code: {rc}")
        _show_windows_error(
            "QuantumChem AI 启动超时",
            f"Web 服务未能正常就绪（退出码 {rc}）。\n\n请查看日志：\n"
            f"{_launcher_log_path(default_db)}\n"
            f"{default_db.resolve().parent / 'logs' / 'qcai_web.log'}",
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

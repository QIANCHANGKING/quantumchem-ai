"""End-to-end Playwright browser test for Streamlit Web flow (P7 acceptance)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright
from typer.testing import CliRunner

from qcai.cli import app
from qcai.pipeline import JobRecord, JobStore
from qcai.programs.gaussian.parser import parse_gaussian_log

GOLDEN_NA6_LOG = Path(__file__).resolve().parents[1] / "data" / "golden" / "na6" / "job.log"
CCLIB_UN_LOG = Path(__file__).resolve().parents[1] / "data" / "cclib" / "dvb_un_sp.log"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.4)
    raise TimeoutError(f"Timed out waiting for Streamlit at {url}")


def test_cli_web_help() -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["web", "--help"])
    assert res.exit_code == 0
    assert "Streamlit" in res.stdout


def test_browser_e2e_full_flow_and_offline_tools(tmp_path: Path) -> None:
    db_path = tmp_path / "e2e.sqlite"
    port = _free_port()
    env = dict(os.environ)
    env["QCAI_DB_PATH"] = str(db_path)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "web/app.py",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_http(url, timeout=35.0)

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url, wait_until="networkidle")

            # 1. 新建研究（默认 AI 全自动标签页）-> 切至手动精细配置 -> 点击后直达 2. 方案书
            page.get_by_text("1. 新建团簇研究").wait_for(timeout=15000)
            page.get_by_role("tab", name="🤖 AI 一句话全自动规划（推荐）").wait_for(timeout=15000)
            page.get_by_role("tab", name="🧪 手动精细配置（周期表 / 上传结构）").click()
            page.get_by_role("button", name="生成计算方案书").wait_for(timeout=15000)
            page.get_by_role("button", name="生成计算方案书").click()

            # 2. 自动跳转至 2. 方案书 -> 确认提交
            page.get_by_text("2. 计算方案书与决策覆盖").wait_for(timeout=15000)
            page.get_by_role("button", name="确认方案并提交到运行队列").click()
            page.get_by_text("已创建并进入运行队列").wait_for(timeout=15000)

            store = JobStore(db_path)
            projects = store.list_projects()
            assert len(projects) == 1
            pid = projects[0].project_id

            # 3. 运行看板 -> 模拟推进 & 注入完成结果
            page.get_by_role("link", name="3. 运行看板").click()
            page.get_by_text("3. 运行看板").wait_for(timeout=15000)
            page.get_by_role("button", name="模拟推进一轮 (Mock Tick)").click()
            page.get_by_text("排队中").wait_for(timeout=15000)

            # Seed parsed golden result into SQLite so Results & PDF work end-to-end
            res = parse_gaussian_log(GOLDEN_NA6_LOG, job_id="na6_gs")
            res_dir = tmp_path / pid / "results"
            res_dir.mkdir(parents=True, exist_ok=True)
            res_file = res_dir / "na6_gs.json"
            res_file.write_text(res.model_dump_json(indent=2), encoding="utf-8")
            store.upsert_job(
                JobRecord(
                    job_id="na6_gs",
                    project_id=pid,
                    stage="S4_refine",
                    cluster_label="Na6",
                    charge=0,
                    multiplicity=1,
                    level="PBE0/def2-TZVP",
                    status="done",
                    result_path=str(res_file),
                )
            )

            # 4. 结果与报告 -> 数据表、3D 预览、生成 PDF
            page.get_by_role("link", name="4. 结果与报告").click()
            page.get_by_text("4. 结果查看与出版级导出").wait_for(timeout=15000)
            page.get_by_text("导出数据表 (CSV)").wait_for(timeout=15000)
            page.get_by_role("button", name="生成 PDF / HTML 报告").click()
            page.get_by_role("button", name="下载 PDF 报告").wait_for(timeout=30000)
            assert (tmp_path / pid / "report" / "report.pdf").exists()

            # 5. 单文件工具（无服务器连接离线可用）
            page.get_by_role("link", name="5. 单文件工具").click()
            page.get_by_text("5. 单文件工具").wait_for(timeout=15000)
            file_inputs = page.locator("input[type='file']")
            file_inputs.nth(0).set_input_files(str(CCLIB_UN_LOG))
            page.get_by_text("-382.081393").wait_for(timeout=15000)

            xyz_file = tmp_path / "al2.xyz"
            xyz_file.write_text("2\nAl2\nAl 0.0 0.0 0.0\nAl 2.5 0.0 0.0\n", encoding="utf-8")
            page.get_by_role("tab", name="结构文件生成 .gjf").click()
            page.locator("input[type='file']").last.set_input_files(str(xyz_file))
            page.get_by_text("下载 .gjf").wait_for(timeout=15000)

            # 6. 设置 -> password input & doctor check
            page.get_by_role("link", name="6. 设置").click()
            page.get_by_text("6. 系统设置与环境自检").wait_for(timeout=15000)
            page.locator("input[type='password']").wait_for(timeout=15000)
            page.get_by_role("button", name="一键检测环境").click()
            page.get_by_text("Python 运行时").wait_for(timeout=15000)

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

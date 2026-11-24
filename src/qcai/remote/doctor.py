"""Environment diagnostics (`qcai doctor`) writing docs/environment.md without secrets."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from qcai.config import AppSettings
from qcai.remote.deploy import deploy_and_probe
from qcai.remote.resources import ResourceManager, ServerProbe
from qcai.remote.ssh import SSHClient


@dataclass(frozen=True)
class CheckItem:
    """Single diagnostic check outcome."""

    name: str
    ok: bool
    detail: str
    suggestion: str = ""


def _check_playwright() -> CheckItem:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = Path(p.chromium.executable_path)
            if exe.exists():
                return CheckItem("Playwright Chromium", True, f"可用 ({exe.name})")
        return CheckItem(
            "Playwright Chromium",
            False,
            "浏览器未安装",
            "运行 `uv run playwright install chromium`",
        )
    except Exception as exc:
        return CheckItem(
            "Playwright Chromium",
            False,
            f"检查失败 ({type(exc).__name__})",
            "运行 `uv run playwright install chromium`",
        )


def run_doctor(
    settings: AppSettings,
    *,
    local_only: bool = False,
    install_env: bool = False,
    output_doc: Path | None = None,
) -> tuple[list[CheckItem], ServerProbe | None]:
    """Run local and (optionally) remote environment checks and write docs/environment.md."""
    items: list[CheckItem] = [
        CheckItem(
            "Python 运行时",
            sys.version_info >= (3, 12),
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "请运行 `uv python pin 3.12 && uv sync`",
        )
    ]

    origin_exe = Path(settings.origin.executable) if settings.origin.executable else None
    items.append(
        CheckItem(
            "Origin 2024b",
            bool(origin_exe and origin_exe.exists()),
            "已配置且路径有效"
            if (origin_exe and origin_exe.exists())
            else "路径未配置或不存在（将降级为 Matplotlib）",
            "在 config/settings.toml [origin].executable 中填写 Origin64.exe 路径",
        )
    )

    vmd_exe = Path(settings.vmd.executable) if settings.vmd.executable else None
    items.append(
        CheckItem(
            "VMD (Windows)",
            bool(vmd_exe and vmd_exe.exists()),
            "已配置且路径有效"
            if (vmd_exe and vmd_exe.exists())
            else "路径未配置或不存在（3D 出图将仅用 py3Dmol）",
            "在 config/settings.toml [vmd].executable 中填写 vmd.exe 路径",
        )
    )

    items.append(_check_playwright())

    probe: ServerProbe | None = None
    if not local_only:
        if not settings.ssh.host or not settings.ssh.work_root:
            items.append(
                CheckItem(
                    "SSH 服务器连接",
                    False,
                    "config/settings.toml 中 [ssh] 未完整配置",
                    "请填写 host、port、username、key_path、work_root",
                )
            )
        else:
            ssh = SSHClient(settings.ssh)
            try:
                probe, py_exe = deploy_and_probe(ssh, install_env=install_env)
                items.append(
                    CheckItem(
                        "SSH 连接与 qcai_remote 同步",
                        True,
                        f"已连接；远端 Python: {'qcai micromamba 环境' if py_exe else '系统 python3'}",
                    )
                )
                for sw_key, sw_label, fix in [
                    ("g16", "Gaussian 16 (g16)", "确认服务器已加载 Gaussian 模块并加入 PATH"),
                    ("formchk", "Gaussian formchk", "确认 Gaussian bin 目录在 PATH 中"),
                    ("cubegen", "Gaussian cubegen", "确认 Gaussian bin 目录在 PATH 中"),
                    ("Multiwfn", "Multiwfn", "确认 Multiwfn 在 PATH 中或设置环境变量"),
                    ("xtb", "xTB", "运行 `qcai doctor --install-env` 或 micromamba 安装 xtb"),
                    ("abcluster_geom", "ABCluster (geom)", "请将 ABCluster geom 加入服务器 PATH"),
                    (
                        "abcluster_isomer",
                        "ABCluster (isomer)",
                        "可选：将 ABCluster isomer 加入 PATH",
                    ),
                    ("molclus", "molclus (可选)", "可选：将 molclus 加入 PATH"),
                    ("micromamba", "micromamba", "运行 `qcai doctor --install-env`"),
                ]:
                    st = probe.software.get(sw_key)
                    avail = bool(st and st.available)
                    ver = f" ({st.version})" if (st and st.version) else ""
                    items.append(
                        CheckItem(
                            sw_label,
                            avail,
                            f"可用{ver}" if avail else "未检测到",
                            "" if avail else fix,
                        )
                    )
                for pkg in ("custodian", "tblite", "pymatgen", "cclib", "ase", "psutil"):
                    pkg_ver = probe.python_packages.get(pkg)
                    items.append(
                        CheckItem(
                            f"远端 Python 包: {pkg}",
                            pkg_ver is not None,
                            f"版本 {pkg_ver}" if pkg_ver else "未安装",
                            "" if pkg_ver else "运行 `qcai doctor --install-env` 安装 qcai 环境",
                        )
                    )
            except Exception as exc:
                items.append(
                    CheckItem(
                        "SSH 连接与环境探测",
                        False,
                        f"失败: {type(exc).__name__}: {exc}",
                        "检查 SSH 密钥、端口及服务器网络连通性；若缺少环境可加 `--install-env`",
                    )
                )
            finally:
                ssh.close()

    if output_doc is not None:
        _write_environment_doc(output_doc, items, probe)
    return items, probe


def _write_environment_doc(path: Path, items: list[CheckItem], probe: ServerProbe | None) -> None:
    """Write sanitized environment report to docs/environment.md (zero credentials)."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# 环境诊断报告 (`qcai doctor`)",
        "",
        f"> 生成时间：{now}（已过滤全部凭据、主机地址与路径隐私）",
        "",
        "| 检查项 | 状态 | 详情 | 修复建议 |",
        "|--------|------|------|----------|",
    ]
    for it in items:
        mark = "✅" if it.ok else "❌"
        lines.append(f"| {it.name} | {mark} | {it.detail} | {it.suggestion or '—'} |")

    if probe is not None:
        alloc = ResourceManager().plan(probe)
        lines.extend(
            [
                "",
                "## 服务器硬件与资源摘要",
                "",
                f"- 物理核数 / 逻辑核数：{probe.physical_cores} / {probe.logical_cores}",
                f"- NUMA 节点数 / 每节点核数：{probe.numa_nodes} / {probe.cores_per_numa}",
                f"- 总内存 / 可用内存：{probe.total_mem_gb:.2f} GB / {probe.available_mem_gb:.2f} GB",
                f"- 系统负载 (1/5/15 min)：{probe.load_avg}",
                f"- Scratch 剩余空间：{probe.scratch_free_gb:.2f} GB",
                f"- 其他用户计算进程：{probe.other_users.other_user_process_count} 个"
                f"（约占用 {probe.other_users.estimated_other_busy_cores:.1f} 核）",
                f"- 建议单作业配额：`nproc={alloc.nproc_per_job}`, `mem={alloc.mem_gb_per_job}GB`, "
                f"最大并发 `{alloc.max_concurrent_jobs}`",
            ]
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

"""Command-line entry point for QuantumChem AI."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, cast

import typer
from ase.io import read as ase_read

from qcai import __version__
from qcai.analysis import summarize_cluster, summarize_project
from qcai.config import load_settings
from qcai.core.models import CalcResult, CalcSpec, Cluster, ElectronicState, ResearchRequest
from qcai.core.physics import (
    HA_TO_EV,
    homo_lumo_gap_hartree,
    ideal_s_squared,
    total_electrons,
)
from qcai.interfaces.runner import JobHandle
from qcai.launcher import launch_web_assistant
from qcai.pipeline import JobRecord, JobStore, PipelineWorker
from qcai.planner import build_plan, format_plan_markdown
from qcai.programs.gaussian.parser import parse_gaussian_log
from qcai.programs.gaussian.writer import write_gaussian_input
from qcai.remote import DirectRunner, MockRunner, SSHClient, run_doctor
from qcai.remote.deploy import deploy_and_probe
from qcai.renderers import RENDERERS, build_figure_spec
from qcai.renderers.vmd import VmdRenderer
from qcai.report import build_report

app = typer.Typer(
    name="qcai",
    help="QuantumChem AI: 面向原子团簇的量子化学科研助手",
    no_args_is_help=True,
)


@app.callback()
def main_callback() -> None:
    """QuantumChem AI command-line interface."""


@app.command()
def version() -> None:
    """Print package version."""
    typer.echo(f"qcai {__version__}")


@app.command()
def parse(
    log: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Gaussian 输出日志路径")],
    json_out: Annotated[
        Path | None,
        typer.Option("--json-out", "-o", help="可选：将完整 CalcResult JSON 写入文件"),
    ] = None,
) -> None:
    """解析 Gaussian 输出日志并输出摘要或 JSON。"""
    result = parse_gaussian_log(log)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(f"已写入解析结果：{json_out}")
        return

    gap_ha = homo_lumo_gap_hartree(result.mo_energies_hartree, result.homo_indices)
    gap_str = f"{gap_ha * HA_TO_EV:.3f} eV" if gap_ha is not None else "N/A"
    energy_str = f"{result.energy_hartree:.8f} Ha" if result.energy_hartree is not None else "N/A"
    typer.echo(
        f"Job: {result.job_id} | 正常结束: {result.normal_termination} | "
        f"错误码: {result.error_code or '无'}"
    )
    geom_str = (
        f"{''.join(result.final_geometry.symbols)} ({len(result.final_geometry.symbols)} atoms)"
        if result.final_geometry is not None
        else "未提取到几何"
    )
    typer.echo(f"体系: {geom_str} | q={result.state.charge}, M={result.state.multiplicity}")
    typer.echo(f"SCF 能量: {energy_str} | ZPE: {result.zpe_hartree} | HOMO-LUMO 隙: {gap_str}")
    if result.s2_before is not None or result.s2_after is not None:
        ideal = ideal_s_squared(result.state.multiplicity)
        typer.echo(f"<S²>: before={result.s2_before}, after={result.s2_after}, ideal={ideal:.4f}")
    if result.imag_freqs:
        typer.echo(f"虚频 (cm^-1): {result.imag_freqs}")


@app.command()
def plot(
    log: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Gaussian 输出日志路径")],
    kind: Annotated[
        Literal["levels", "spin", "dos", "s2"],
        typer.Option("--kind", "-k", help="图类型: levels|spin|dos|s2"),
    ] = "levels",
    renderer: Annotated[str, typer.Option("--renderer", "-r", help="渲染器: mpl|origin")] = "mpl",
    out_dir: Annotated[Path, typer.Option("--out-dir", "-o", help="输出目录")] = Path("plots"),
) -> None:
    """解析 Gaussian 日志并生成指定类型的可视化图表。"""
    result = parse_gaussian_log(log)
    spec = build_figure_spec(result, kind)
    impl = RENDERERS.get(renderer)
    outputs = impl.render(spec, out_dir)
    for path in outputs:
        typer.echo(f"生成图表：{path}")


def _parse_tasks(tasks_raw: str) -> list[Literal["sp", "opt", "freq", "stable"]]:
    valid = {"sp", "opt", "freq", "stable"}
    tasks: list[Literal["sp", "opt", "freq", "stable"]] = []
    for item in tasks_raw.split(","):
        tok = item.strip().lower()
        if not tok:
            continue
        if tok not in valid:
            raise typer.BadParameter(f"不支持的任务类型 {tok!r}，可选: {sorted(valid)}")
        tasks.append(cast(Literal["sp", "opt", "freq", "stable"], tok))
    return tasks or ["opt", "freq"]


@app.command()
def gen(
    structure: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="输入结构文件 (xyz/gjf/POSCAR等)")
    ],
    functional: Annotated[str, typer.Option("--functional", "-f", help="泛函")] = "PBE0",
    basis: Annotated[str, typer.Option("--basis", "-b", help="基组")] = "def2-TZVP",
    charge: Annotated[int, typer.Option("--charge", "-q", help="总电荷")] = 0,
    mult: Annotated[int | None, typer.Option("--mult", "-m", help="自旋多重度")] = None,
    tasks: Annotated[str, typer.Option("--tasks", "-t", help="任务列表，逗号分隔")] = "opt,freq",
    dispersion: Annotated[str, typer.Option("--dispersion", help="色散校正")] = "GD3BJ",
    scf: Annotated[
        Literal["default", "robust"], typer.Option("--scf", help="SCF 策略")
    ] = "default",
    nproc: Annotated[int, typer.Option("--nproc", help="CPU 核数")] = 8,
    mem: Annotated[int, typer.Option("--mem", help="内存 (GB)")] = 16,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="输出 .gjf 路径")] = None,
) -> None:
    """根据结构文件与参数生成 Gaussian .gjf 输入文件。"""
    atoms = ase_read(str(structure))
    if isinstance(atoms, list):
        atoms = atoms[-1]
    cluster = Cluster.from_ase(atoms, label=structure.stem, source=str(structure))
    resolved_mult = mult
    if resolved_mult is None:
        n_elec = total_electrons(cluster.symbols, charge)
        resolved_mult = 1 if n_elec % 2 == 0 else 2

    spec = CalcSpec(
        functional=functional,
        basis=basis,
        dispersion=dispersion or None,
        tasks=_parse_tasks(tasks),
        scf_strategy=scf,
    )
    out_path = out or structure.with_suffix(".gjf")
    written = write_gaussian_input(
        cluster,
        ElectronicState(charge=charge, multiplicity=resolved_mult),
        spec,
        out_path,
        nproc=nproc,
        mem_gb=mem,
    )
    typer.echo(f"已生成 Gaussian 输入文件：{written}")


def _parse_composition(raw: str) -> dict[str, int | tuple[int, int]]:
    comp: dict[str, int | tuple[int, int]] = {}
    for token in raw.split(","):
        part = token.strip()
        if not part:
            continue
        if ":" not in part:
            raise typer.BadParameter(f"组成格式错误 {part!r}，示例: Al:6-13,Ni:1")
        el, count_raw = part.split(":", 1)
        el = el.strip()
        count_raw = count_raw.strip()
        if "-" in count_raw:
            lo_s, hi_s = count_raw.split("-", 1)
            comp[el] = (int(lo_s), int(hi_s))
        else:
            comp[el] = int(count_raw)
    if not comp:
        raise typer.BadParameter("组成不能为空")
    return comp


def _parse_budget_hours(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = raw.strip().lower()
    if s.endswith("h"):
        s = s[:-1].strip()
    return float(s)


@app.command()
def plan(
    composition: Annotated[
        str, typer.Option("--composition", "-c", help="体系组成，如 Al:6-13,Ni:1")
    ],
    recipes: Annotated[
        str, typer.Option("--recipes", "-r", help="研究目标，逗号分隔")
    ] = "stability",
    accuracy: Annotated[
        Literal["fast", "standard", "high"],
        typer.Option("--accuracy", "-a", help="精度档位: fast|standard|high"),
    ] = "standard",
    budget: Annotated[str | None, typer.Option("--budget", help="时间预算，如 12h")] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="可选：保存 Markdown 方案书路径")
    ] = None,
) -> None:
    """生成研究计算方案书（Markdown）。"""
    req = ResearchRequest(
        composition=_parse_composition(composition),
        recipes=[r.strip() for r in recipes.split(",") if r.strip()],
        accuracy=accuracy,
        time_budget_hours=_parse_budget_hours(budget),
    )
    calc_plan = build_plan(req)
    md = format_plan_markdown(calc_plan)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        typer.echo(f"已保存方案书：{out}")
    else:
        typer.echo(md)


@app.command()
def doctor(
    local_only: Annotated[
        bool, typer.Option("--local-only", help="仅检测本机环境，不连接 SSH 服务器")
    ] = False,
    install_env: Annotated[
        bool, typer.Option("--install-env", help="若服务器缺少 qcai 环境则自动安装 micromamba 环境")
    ] = False,
    out: Annotated[Path, typer.Option("--out", "-o", help="环境报告输出路径（不含凭据）")] = Path(
        "docs/environment.md"
    ),
) -> None:
    """检测本机与远程计算环境，生成不含凭据的 docs/environment.md。"""
    settings = load_settings()
    items, _ = run_doctor(
        settings,
        local_only=local_only,
        install_env=install_env,
        output_doc=out,
    )
    for item in items:
        mark = "✅" if item.ok else "❌"
        hint = f" -> 建议: {item.suggestion}" if (not item.ok and item.suggestion) else ""
        typer.echo(f"{mark} {item.name}: {item.detail}{hint}")
    typer.echo(f"环境报告已写入：{out}")


@app.command()
def run(
    gjf: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="待提交的 .gjf 文件")],
    project: Annotated[str, typer.Option("--project", "-p", help="项目 ID")] = "single",
    job_id: Annotated[str | None, typer.Option("--job-id", help="作业 ID")] = None,
    db: Annotated[Path, typer.Option("--db", help="SQLite 数据库路径")] = Path(
        "projects/qcai.sqlite"
    ),
    mock: Annotated[bool, typer.Option("--mock", help="使用本地模拟执行器")] = False,
) -> None:
    """提交单个 Gaussian 作业到服务器（或模拟执行器）并写入 SQLite 作业表。"""
    resolved_id = job_id or f"{gjf.stem}_{uuid.uuid4().hex[:6]}"
    local_dir = db.parent / project / resolved_id
    local_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(gjf, local_dir / "job.gjf")
    job_json = {
        "job_id": resolved_id,
        "gjf_file": "job.gjf",
        "log_file": "job.log",
        "max_errors": 3,
        "run_formchk": True,
    }
    (local_dir / "job.json").write_text(
        json.dumps(job_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    store = JobStore(db)
    if mock:
        runner = MockRunner()
        r_dir = Path(f"/mock/{project}/{resolved_id}")
        handle = runner.submit(resolved_id, local_dir, r_dir, "")
    else:
        settings = load_settings()
        ssh = SSHClient(settings.ssh)
        try:
            py_exe = ssh.locate_qcai_python()
            direct = DirectRunner(ssh, remote_python=py_exe)
            r_dir_posix = PurePosixPath(settings.ssh.work_root) / project / resolved_id
            handle = direct.submit(resolved_id, local_dir, Path(str(r_dir_posix)), "")
        finally:
            ssh.close()

    store.upsert_job(
        JobRecord(
            job_id=resolved_id,
            project_id=project,
            stage="single",
            cluster_label=gjf.stem,
            status="running",
            pid=handle.pid,
            remote_dir=handle.remote_dir.as_posix(),
            local_dir=str(local_dir),
        )
    )
    typer.echo(f"已提交作业 {resolved_id} (pid={handle.pid})")


@app.command()
def status(
    project: Annotated[str | None, typer.Option("--project", "-p", help="按项目筛选")] = None,
    db: Annotated[Path, typer.Option("--db", help="SQLite 数据库路径")] = Path(
        "projects/qcai.sqlite"
    ),
    reconcile: Annotated[
        bool, typer.Option("--reconcile/--no-reconcile", help="是否与服务器对账")
    ] = True,
) -> None:
    """查看 SQLite 中的作业状态（可选与服务器对账）。"""
    store = JobStore(db)
    if reconcile:
        settings = load_settings()
        if settings.ssh.host and settings.ssh.work_root:
            ssh = SSHClient(settings.ssh)
            try:
                store.reconcile(DirectRunner(ssh), project_id=project)
            finally:
                ssh.close()

    jobs = store.list_jobs(project_id=project)
    if not jobs:
        typer.echo("暂无作业记录。")
        return
    for j in jobs:
        typer.echo(
            f"{j.job_id} | project={j.project_id} | status={j.status} | "
            f"pid={j.pid or '-'} | err={j.error_message or '-'}"
        )


@app.command()
def cancel(
    job_id: Annotated[str, typer.Argument(help="待取消的作业 ID")],
    db: Annotated[Path, typer.Option("--db", help="SQLite 数据库路径")] = Path(
        "projects/qcai.sqlite"
    ),
) -> None:
    """取消正在运行的作业并更新数据库状态。"""
    store = JobStore(db)
    job = store.get_job(job_id)
    if job is None:
        raise typer.BadParameter(f"未找到作业: {job_id!r}")
    settings = load_settings()
    ssh = SSHClient(settings.ssh)
    try:
        runner = DirectRunner(ssh)
        ok = runner.cancel(
            JobHandle(job_id=job.job_id, pid=job.pid, remote_dir=Path(job.remote_dir))
        )
    finally:
        ssh.close()
    job.status = "cancelled" if ok else job.status
    store.upsert_job(job)
    typer.echo(f"作业 {job_id} 取消结果: {ok}")


@app.command()
def worker(
    project: Annotated[str | None, typer.Option("--project", "-p", help="仅调度指定项目")] = None,
    db: Annotated[Path, typer.Option("--db", help="SQLite 数据库路径")] = Path(
        "projects/qcai.sqlite"
    ),
    once: Annotated[bool, typer.Option("--once", help="仅执行单轮调度后退出")] = False,
    interval: Annotated[float, typer.Option("--interval", help="轮询间隔 (秒)")] = 10.0,
    mock: Annotated[bool, typer.Option("--mock", help="使用本地模拟执行器")] = False,
) -> None:
    """启动后台流水线调度循环，支持断点续跑与并发控制。"""
    store = JobStore(db)
    projects_root = db.parent
    if mock:
        pw = PipelineWorker(store, MockRunner(), projects_root=projects_root)
        if once:
            stats = pw.step(project_id=project)
            typer.echo(f"Worker tick: {stats}")
        else:
            pw.run_loop(project_id=project, poll_interval=interval)
        return

    settings = load_settings()
    ssh = SSHClient(settings.ssh)
    try:
        probe, py_exe = deploy_and_probe(ssh, install_env=False)
        runner = DirectRunner(ssh, remote_python=py_exe)
        pw = PipelineWorker(
            store,
            runner,
            projects_root=projects_root,
            remote_work_root=settings.ssh.work_root,
            ssh=ssh,
            probe=probe,
            remote_python=py_exe,
        )
        if once:
            stats = pw.step(project_id=project)
            typer.echo(f"Worker tick: {stats}")
        else:
            pw.run_loop(project_id=project, poll_interval=interval)
    finally:
        ssh.close()


@app.command()
def pause(
    project_id: Annotated[str, typer.Argument(help="待暂停的项目 ID")],
    db: Annotated[Path, typer.Option("--db", help="SQLite 数据库路径")] = Path(
        "projects/qcai.sqlite"
    ),
) -> None:
    """暂停指定研究项目的新作业调度。"""
    store = JobStore(db)
    store.set_project_status(project_id, "paused")
    typer.echo(f"已暂停项目：{project_id}")


@app.command()
def resume(
    project_id: Annotated[str, typer.Argument(help="待恢复的项目 ID")],
    db: Annotated[Path, typer.Option("--db", help="SQLite 数据库路径")] = Path(
        "projects/qcai.sqlite"
    ),
) -> None:
    """恢复指定研究项目的流水线调度。"""
    store = JobStore(db)
    store.set_project_status(project_id, "running")
    typer.echo(f"已恢复项目：{project_id}")


@app.command()
def report(
    target: Annotated[str, typer.Argument(help="项目 ID 或包含计算日志的目录路径")],
    db: Annotated[Path, typer.Option("--db", help="SQLite 数据库路径")] = Path(
        "projects/qcai.sqlite"
    ),
    renderer: Annotated[
        str, typer.Option("--renderer", "-r", help="2D 渲染器: mpl|origin")
    ] = "mpl",
    out_dir: Annotated[Path | None, typer.Option("--out-dir", "-o", help="报告输出目录")] = None,
    with_vmd: Annotated[bool, typer.Option("--vmd", help="是否调用 VMD 渲染 3D 结构图")] = False,
) -> None:
    """为指定项目或日志目录一键生成完整 HTML 与 PDF 报告。"""
    target_path = Path(target)
    results: list[CalcResult] = []
    project_id = target

    if target_path.is_dir():
        project_id = target_path.name
        log_files = sorted(target_path.rglob("job.log"))
        if not log_files:
            log_files = sorted(list(target_path.glob("*.log")) + list(target_path.glob("*.out")))
        for lf in log_files:
            jid = lf.parent.name if lf.name == "job.log" else lf.stem
            res = parse_gaussian_log(lf, job_id=jid)
            st_file = lf.parent / "status.json"
            if st_file.exists():
                st_data = json.loads(st_file.read_text(encoding="utf-8"))
                res.fixes = [str(x) for x in st_data.get("fixes", [])]
            results.append(res)
        resolved_out = out_dir or (target_path / "report")
    else:
        store = JobStore(db)
        for job in store.list_jobs(project_id=target):
            if job.result_path and Path(job.result_path).exists():
                results.append(
                    CalcResult.model_validate_json(
                        Path(job.result_path).read_text(encoding="utf-8")
                    )
                )
        resolved_out = out_dir or (db.parent / target / "report")

    if not results:
        raise typer.BadParameter(f"未在 {target!r} 中找到可归纳的计算结果")

    grouped: dict[str, list[CalcResult]] = {}
    for r in results:
        if r.final_geometry is not None:
            from collections import Counter

            cnt = Counter(r.final_geometry.symbols)
            formula = "".join(f"{el}{n if n > 1 else ''}" for el, n in sorted(cnt.items()))
        else:
            formula = r.job_id
        key = f"{formula} (q={r.state.charge})"
        grouped.setdefault(key, []).append(r)

    clusters = {}
    for k, grp in grouped.items():
        if any(r.normal_termination and r.energy_hartree is not None for r in grp):
            clusters[k] = summarize_cluster(k, grp)

    summary = summarize_project(project_id, clusters)
    extra_imgs: list[tuple[Path, str]] = []
    used_vmd = False
    if with_vmd:
        vmd = VmdRenderer()
        for cs in clusters.values():
            if cs.ground_state_geometry is not None:
                vmd_outs = vmd.render_cluster(
                    cs.ground_state_geometry,
                    resolved_out / "vmd",
                    stem=cs.ground_state_job_id,
                )
                extra_imgs.append((vmd_outs[0], f"{cs.cluster_label} 基态 3D 结构 (VMD)"))
                used_vmd = True

    html_path, pdf_path = build_report(
        summary,
        results,
        resolved_out,
        renderer_name=renderer,
        extra_images=extra_imgs,
        used_vmd=used_vmd,
        render_pdf=True,
    )
    typer.echo(f"HTML 报告：{html_path}")
    if pdf_path is not None:
        typer.echo(f"PDF 报告：{pdf_path}")


@app.command()
def web(
    port: Annotated[int, typer.Option("--port", help="Streamlit 服务端口")] = 8501,
    db: Annotated[Path, typer.Option("--db", help="SQLite 数据库路径")] = Path(
        "projects/qcai.sqlite"
    ),
    with_worker: Annotated[
        bool, typer.Option("--worker/--no-worker", help="是否同时启动后台 worker")
    ] = True,
    mock: Annotated[bool, typer.Option("--mock", help="后台 worker 使用模拟执行器")] = False,
    app_mode: Annotated[
        bool, typer.Option("--app/--browser-tab", help="使用独立桌面应用窗口或浏览器标签页打开")
    ] = True,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="就绪后是否自动打开窗口")
    ] = True,
) -> None:
    """启动 Streamlit Web 界面与后台 qcai worker（通过 SQLite 通信）。"""
    launch_web_assistant(
        port=port,
        db=db,
        with_worker=with_worker,
        mock=mock,
        app_mode=app_mode,
        open_browser=open_browser,
    )


if __name__ == "__main__":
    app()

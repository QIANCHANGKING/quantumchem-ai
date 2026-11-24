# 决策记录

偏离或补充方案时在此记录：日期 / 决策 / 理由 / 提出者 / 确认。

| 日期 | 决策 | 理由 | 提出者 | 确认 |
|------|------|------|--------|------|
| 2026-11-18 | 采用 `QuantumChem_AI_开发方案.md` v2.0（复用优先·单 AI 执行版）取代 v1.5 与 OpenBot 多代理任务卡 | 用户指令以 v2.0 为唯一执行依据，清理旧 `openbot/` 与 `.worktrees/` | 用户 / AI | 用户 |
| 2026-11-18 | 固定 Python 3.12（`.python-version`）；在 `pyproject.toml` 中补充 `pyyaml`（dev 含 `hypothesis`、`types-PyYAML`） | YAML 规则引擎与属性测试必需（方案第 5 节、第 10 节） | AI | 方案隐含 |
| 2026-11-18 | 结构去重采用“距离矩阵特征值指纹预筛 + 三轴惯量主轴对齐匈牙利匹配 / `GeneticOrderMatcher`”，不直接单独使用 `pymatgen.HungarianOrderMatcher` | P0 `spike_03` 验证发现 `pymatgen.HungarianOrderMatcher` 仅对齐第一惯量主轴，对任意三维旋转给出错误大 RMSD（1.7–1.9 Å）；三轴对齐 + Kabsch 或 `GeneticOrderMatcher` 对 6–38 原子均在 <8 ms 内得到 ~1e-15 Å | AI | P0 Spike |
| 2026-11-18 | `basis_set_exchange` 覆盖查询使用 `bse.misc.transform_basis_name()` 规范化名称 | P0 `spike_04` 验证 `get_metadata()` 键名为规范化键（如 `6-31G*` → `6-31g_st_`） | AI | P0 Spike |
| 2026-11-18 | 使用 `pymatgen.GaussianInput` 生成含 ECP 的自定义基组时，构造后显式设置 `gin.basis_set = "GenECP"` | P0 `spike_05` 验证 `GaussianInput(..., gen_basis=...)` 默认把基组设成 `"Gen"`，含 ECP 块时 Gaussian 需要 `GenECP` | AI | P0 Spike |
| 2026-11-18 | `DirectRunner` 复用 `qtoolkit.io.shell.ShellIO` 的提交/查询/解析接口，取消作业时补充进程组级终止（`setsid` + `kill -TERM -- -<pgid>`） | P0 `spike_07` 验证 `ShellIO` 自带 `nohup ... & echo $!` 与 `ps` 解析，但默认 `CANCEL_CMD = "kill -9"` 不会连带终止 `g16` 子进程 | AI | P0 Spike |
| 2026-11-18 | Windows VMD 渲染器以 `-dispdev text -e` 运行，以输出文件存在且非空作为成功判据，容忍 Tcl 退出码 `0xC0000374` | P0 `spike_09` 验证 Windows 版 VMD 可无界面完成 `TachyonInternal` 渲染并生成有效 TGA，但进程退出清理阶段会返回 `3221226356` | AI | P0 Spike |
| 2026-11-18 | 服务器端 P3 🔍 验证：`custodian 2026.10.21` 的 `GaussianErrorHandler` 要求同时传入 `input_file` 与 `output_file`，已覆盖 `scf_convergence`/`opt_steps`/`linear_bend`/`insufficient_mem` 等 17 种模式；自研 `ImaginaryFreqHandler` 与 `InstabilityHandler`（含 `directory` 参数）补齐虚频与稳定性缺口 | 实机探测发现 `GaussianErrorHandler.__init__` 签名要求 `input_file` 与 `output_file` 均为必填；Multiwfn 实测版本为 `3.8(dev) 2025-Mar-10`；`tblite` (`GFN2-xTB`) 与 `ABCluster` (`geom`/`isomer`) 均可用 | AI | P3 Verify |
| 2026-11-18 | `write_gaussian_input` 与 `qcai_remote/run_job.py` 强制使用 LF (`\n`) 换行；`custodian.GaussianJob` 命令显式包含 `< job.gjf`；包装 `_SafeGaussianErrorHandler` 修复裸 `opt`/`scf` 触发 `NoneType.get` 与 `GaussianOutput` 频率解析崩溃；稳定波函数正则兼容 `"is already stable"` 与 `"is stable under"` | 真实 Gaussian 16 实机跑测暴露的 4 项生产级细节，全部修复并通过真实算例复测 | AI | P3 Golden |
| 2026-11-18 | 新增依赖 `ase-ga==1.0.3`（本机及服务器端 `qcai` 环境）作为 ASE 遗传算法实现；ABCluster 采用服务器实测确认的 `isomer` + `runxTB.sh`（独立子目录 + `--chrg`/`--uhf`/`--gfn 2`）格式 | `ase 3.29.0` 已将原 `ase.ga` 拆分为独立包 `ase-ga`；参考服务器 `/home/Ben/software/abcluster/abcluster-Release/testfiles/isomer/3-au8-xTB/` 确定精确输入语法 | AI | P4 |
| 2026-11-18 | `opt`/`freq` 与 `stable=opt` 共存时自动拆分为三段 `--Link1--`；`DirectRunner` 的 `submit.sh` 显式加载 `~/.bashrc` 与 `$HOME/.local/bin`；`probe.py` 用 `ps -eo user,pcpu,comm` 统计全部高负载外用户进程 | 实测 `g16` 禁止 `opt` 与 `stable=opt` 同行 (`Illegal IType`)；`--Link1--` 三步法已在真实 `g16` 通过；共享服务器其他用户 `cp2k.psmp` 满载时被 `ResourceManager` 准确识别并礼让 | AI | P4/P5 |
| 2026-11-18 | Multiwfn 模板严格绑定 `Version 3.8(dev) (2025-Mar-10)`：电荷用 `7->1/11`，自旋密度用 `15->-1->3->1->5`，PDOS 用 `10`（`DOS_curve.txt` 预处理紧邻负号粘连 `(?<=\d)-`），轨道成分用 `8->1`；`cubegen` 开壳层采用 `Spin=SCF` / `AMO=HOMO` / `BMO=HOMO` / `AMO=LUMO` / `BMO=LUMO` | 实机运行 `Multiwfn 3.8(dev)` 与 `cubegen` 在 `al12cu.fchk` 验证通过，真实 `DOS_curve.txt` 第 2860 行存在 Fortran 固定列宽负号粘连 | AI | P5 |
| 2026-11-18 | Origin 2024b 四联图默认模板采用内置 `PAN4`（找不到模板时回退 `line`） | 在 Origin 2024b 实机生成全 10 类 `.opju` 时确认内置四联图模板名为 `PAN4.OTP`，原 `"4panel"` 返回 `None` | AI | P6 |
| 2026-11-18 | `DeepSeekSettings` 增加 `base_url` 可选配置，并在 `qcai.config.resolve_deepseek_key` 统一按 `DEEPSEEK_API_KEY` → OS `keyring` → `config/settings.toml` 读取 | 支持 OpenAI 兼容 DeepSeek 节点（如自定义 `base_url` / `deepseek-v4.1-flash`）且保持 Web 与 CLI/pytest 密钥环一致 | AI / 用户 | P8 |

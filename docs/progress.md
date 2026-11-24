# 开发进度看板（v2.0）

状态：`待开始` / `进行中` / `已完成` / `阻塞（原因）`

| 阶段 | 内容 | 状态 | 备注 |
|------|------|------|------|
| P0 | 环境与能力验证（本地依赖 + 11 个 🔍 Spike 验证） | 已完成 | 服务器端验证（custodian / tblite / Multiwfn / g16）按方案推迟到 P3 |
| P1 | 离线核心：数据模型、Gaussian 解析、Matplotlib & Origin 轨道/自旋可视化、CLI | 已完成 | 30 项单元测试 + 4 项 Origin 2024b 集成测试全部通过 |
| P2 | 输入生成、规则引擎、规划器、研究目标模板（v1 三项基础功能离线闭环） | 已完成 | 53 项单元测试全部通过，离线 v1 三项基础功能已全部可用 |
| P3 | 远程执行、资源探测、服务器端 custodian 自愈、黄金样本 | 已完成 | 真实 `H₂`、BSE `GenECP` 与 10 份黄金样本全部在服务器实测并回归通过 |
| P4 | 结构搜索 + 漏斗流水线 + 耗时校准 | 进行中（等服务器空闲跑基准） | 本地代码与测试全通过；服务器实时探针仍高负载（`load_avg: [48.63, 48.72, 46.96]`），`ResourceManager` 主动限流 `allowed_new_jobs=0` |
| P5 | Multiwfn 模板与解析 + 物理量归纳 | 已完成 | 84 项单元测试全通过，Multiwfn 3.8(dev) 与 cubegen 均实测通过 |
| P6 | 出版级输出：Origin 全图 + VMD + PDF 报告 | 已完成 | 87 项单元测试 + VMD 集成测试全通过，初版脚本已就绪（待人类按需微调 `.otpu` 模板） |
| P7 | Streamlit Web 多页面 + `qcai web` | 已完成 | 89 项测试全通过，含真实 Chromium 浏览器 6 页面端到端及离线单文件工具测试 |
| P8 | DeepSeek 接入与防幻觉校验 | 已完成 | 93 项离线测试 + `pytest -m llm`（50 条中文科研指令 `deepseek-v4.1-flash` 实网评测）全部通过 |

## 待人类处理

- [x] 填写 `config/settings.toml` 中的 SSH、Origin 2024b 路径、VMD 路径（检测到均已填写且本机 Origin/VMD 路径有效）
- [x] **P0 检查点**：已确认并完成服务器端 `micromamba` (`qcai` 环境：`python=3.11 xtb tblite-python ase pymatgen custodian cclib psutil`) 安装（`ABCluster` 亦已就绪）
- [x] **P3 检查点**：已确认并完成首个真实 `H₂` 单点、BSE `GenECP` 验证及 10 份黄金样本实机运行，结果已回收至 `tests/data/golden/`
- [x] **P4 检查点**：已确认运行 7 簇文献基准（实时复查 `load_avg: [48.63, 48.72, 46.96]`、`allowed_new_jobs=0`，`ResourceManager` 自动暂停提交避免争抢他用户 `cp2k.psmp` 任务，待服务器负载回落后可随时运行）
- [ ] **P6 检查点**：（可选）已生成 10 类初版工程于 `projects/origin_drafts/`，可在 Origin 2024b 中微调后“另存模板为”至 `src/qcai/renderers/origin/templates/<kind>.otpu`
- [x] **P8 检查点**：已完成 API Key 写入 OS `keyring` 与 `[deepseek]` 自定义 `base_url` / `model` 配置，并实网跑通 `uv run pytest -o addopts="" -m llm -v`

## 阶段交付记录

### P8 AI 对话层与防幻觉校验（已完成，2026-11-18）
- **完成了什么**：
  - `src/qcai/ai/`：`prompts/planner_system.md`、`prompts/analyst_system.md`、`guard.py`（`collect_fact_numbers` 收集单位换算与基准物理常量、`verify_grounded_numbers` 容差匹配并在异常文本中定位未锚定数值）、`tools.py`（只读工具 `tool_get_summary` / `tool_get_plan` / `tool_get_job` / `tool_explain_decision` / `tool_diagnose_job` / `tool_plan_research` 与仅返回确认请求对象、不直接触发修改的 `tool_request_action`）、`agent.py`（注册 `LLMS["deepseek"]` 的 `DeepSeekLLMProvider`（支持自定义 `base_url`）、意图解析 `parse_natural_language_intent` / `parse_natural_language_request`、带 `@agent.output_validator` `ModelRetry` 二次验证及 `InterpretationResult.verified` 标记的 `build_analyst_agent` / `interpret_project`）。
  - `src/qcai/config.py`、`src/qcai/interfaces/llm.py` & `web/state.py`：统一 `resolve_deepseek_key` / `save_deepseek_key`（环境变量 → OS `keyring` → `settings.toml`）与 `DeepSeekSettings.base_url` 配置。
  - `web/pages/`：`new_research.py` 接入自然语言直接生成 `ResearchRequest` 并触发澄清提问或自动预填提交；`results.py` 接入 DeepSeek 结果解读入口，并在 `verified=False` 时以红色 `st.error` 警示框标红展示。
  - `tests/llm_eval/` & `tests/unit/test_ai_layer.py` & `tests/integration/test_deepseek_llm.py`：编写 50 条覆盖全周期表区间、研究目标、预算/精度与 8+ 歧义澄清的中文研究指令集（`instructions.yaml`）、评测器（`eval_runner.py`）、离线 `FunctionModel` 防幻觉/隐私边界/工具确认/50 条指令单测，以及 `@pytest.mark.llm` 实网评测用例。
- **如何验证**：
  - `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src`（74 个源文件）全部通过；
  - `uv run pytest -o addopts="" -m llm -v`：在 OpenAI 兼容节点（`deepseek-v4.1-flash`）上 50 条中文科研指令实网评测准确率 `>= 90%`，实测通过；
  - `uv run pytest -v`：93 项离线测试全部通过（8 项按默认标记 `not (remote or origin or vmd or llm)` 跳过），包含数值防幻觉单位换算与幻觉截获、`ModelRetry` 重试后 `verified=False` 标红标志、工具隐私边界、50 条中文指令全量离线评测。
- **遗留问题**：无。

### P7 Web（已完成，2026-11-18）
- **完成了什么**：
  - `web/`：`app.py`、`state.py`（SQLite 共享状态 + OS `keyring` 凭据存储与零回显）、`pages/new_research.py`（周期表点选/尺寸/目标/精度/结构上传）、`pages/plan_review.py`（决策展示/覆盖/确认提交）、`pages/dashboard.py`（`st.fragment(run_every=5)` 定时刷新/暂停/恢复/取消/修复记录）、`pages/results.py`（CSV 导出、`py3Dmol` 阈值滑块、Origin/VMD 出版渲染与 PDF 下载）、`pages/single_file_tools.py`（完全离线解析+绘图+.gjf 生成）、`pages/settings_page.py`（密码框 `keyring` 存储、`qcai doctor` 一键检测）。
  - `src/qcai/cli.py`：新增 `qcai web`（联动后台 `qcai worker` 与 Streamlit）。
- **如何验证**：
  - `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src` 全部通过；
  - `uv run pytest`（89 项测试，含 `tests/e2e/test_web_flow.py` 真实 Chromium 驱动 Streamlit 完成“新建研究 → 方案书 → 看板 → 结果与 PDF 下载 → 单文件工具离线解析与生成 → 设置”全流程）全部通过。
- **遗留问题**：无。

### P6 出版级输出：Origin 全图 + VMD + PDF（已完成，2026-11-18）
- **完成了什么**：
  - `src/qcai/renderers/spec.py`、`mpl/`、`origin/`：扩展支持第 6.7 节全部 10 类图（能级图、能级对比、TDOS/PDOS、前线轨道成分、原子自旋布居、自旋态能量阶梯、异构体能量排序、尺寸演化 4 面板、VDE/ADE 对比、`<S²>` 对比）；配置 `origin/templates/` 模板目录与说明。
  - `src/qcai/renderers/web3d/` & `vmd/`：基于原子质量加权惯量主轴的统一默认视角对齐 `align_cluster_principal_axes`、`py3Dmol` 交互预览、`VmdRenderer`（`Orthographic` + `TachyonInternal` + 掺杂高亮 + 等值面 + `.tcl`/`.xyz`/`.cube` 打包）。
  - `src/qcai/knowledge/` & `src/qcai/report/`：`bibliography.yaml`、`methods_text.yaml`（中/英文方法学段落）、`report.html.j2`（封面、目录、摘要、方法、结果、问题与说明、附录、文献）及 Playwright A4 PDF 输出、`qcai report` CLI。
- **如何验证**：
  - `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src`（70 个源文件）全部通过；
  - `uv run pytest`（87 项单元测试，含全部 10 类图 Matplotlib 出图、py3Dmol 与 VMD Tcl 生成、黄金样本一键生成真实 HTML + A4 PDF 报告并校验中文/SVG/故障记录/参考文献）全部通过；
  - `uv run pytest -o addopts="" -m vmd` 真实 VMD 批处理渲染集成测试通过。
- **遗留问题**：
  - 🧑 人类可随时在 Origin 2024b 中微调 `.opju` 图形并另存为 `src/qcai/renderers/origin/templates/<kind>.otpu`。

### P5 分析与归纳 + Multiwfn 模板/解析（已完成，2026-11-18）
- **完成了什么**：
  - `src/qcai/analysis/`：`energetics.py`（平均结合能 $E_b$、二阶差分 $\Delta_2 E$、碎裂能 $E_f$、嵌入能 $E_\text{emb}$、取代能 $E_\text{sub}$、混合能 $\Delta$、VDE/ADE/VIP/VEA）、`electronic.py`（仅按周期表族规则的凝胶价电子数与闭壳层幻数、能隙、元素电荷转移）、`spin.py`（自旋局域度 $f_\text{D}$、磁矩总结）、`summary.py`（`ClusterSummary`、`ProjectSummary` 及全部 5 类问题标记）。
  - `src/qcai/programs/multiwfn/`：`templates.py`（绑定服务器 `Multiwfn 3.8(dev) 2025-Mar-10` 的 `charge_spin`、`pdos`、`orb_comp` 模板）、`parsers.py`（含版本强制校验 `MultiwfnVersionError` 与 Fortran 粘连修复）、`cubegen.py`（粗/细格点与开闭壳层命令模板）。
  - `src/qcai_remote/mwfn.py` & `run_job.py`：服务器端 Multiwfn 批处理钩子。
  - 修复了 P4 实测发现的 Gaussian `opt`+`stable=opt` 不能同行问题（改为 3 段 `--Link1--`，并在真机 `g16` 通过）及 `probe.py` 他用户高负载进程统计。
  - 采集真实 `Al₁₂Cu` 的 `Multiwfn 3.8(dev)` 输出样本至 `tests/data/multiwfn/al12cu/`。
- **如何验证**：
  - `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src` 全部通过；
  - `uv run pytest`（84 项单元测试，含全部物理量手算测试、真实 `Multiwfn 3.8(dev)` 解析、版本不匹配报错测试、`cubegen` 预设测试）全部通过。
- **遗留问题**：无。

### P4 结构搜索 + 漏斗流水线（代码与离线验证已完成，2026-11-18）
- **完成了什么**：
  - `src/qcai/structure/`：`readers.py`（单/多帧 XYZ、ABCluster `-LM`、molclus 与评论行能量解析）、`dedup.py`（距离矩阵特征值指纹预筛 + 三轴惯量对齐匈牙利/Kabsch + `GeneticOrderMatcher`/`BruteForceOrderMatcher` 兜底）、`dopant_sites.py`（`PointGroupAnalyzer` 单掺杂等价类、多掺杂规范化组合去重与空腔内嵌）、`generators.py`（`ImportGenerator` > `ABClusterGenerator` > `MolclusGenerator` > `AseGaGenerator` 注册表）。
  - `src/qcai_remote/search.py`：服务器端统一搜索入口（支持 `ABCluster isomer` 与 `ase_ga` + `tblite GFN2-xTB` 兜底）。
  - `src/qcai/pipeline/`：`db.py`（扩展 `ProjectRecord`/`JobRecord`）、`stages.py`（幂等 S0–S7 漏斗推进与第 5.2 节自适应多重度扫描/提前终止/边界外扩）、`worker.py`（`PipelineWorker` 调度、并发控制、暂停/恢复、结果回收、定期重探、`.rwf` 清理）、`cli.py`（`qcai worker` / `qcai pause` / `qcai resume`）。
  - `src/qcai/planner/cost_model.py`：基于 numpy 最小二乘的已完成作业耗时校准 `calibrate_cost_model`。
  - `tests/data/benchmark/clusters.yaml`：涵盖 s/p/3d/5d/双金属/内嵌共 7 个带实证 DOI 的文献基准团簇清单。
- **如何验证**：
  - `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src` 全部通过；
  - `uv run pytest`（77 项单元测试，含八面体/二十面体等价位点数、旋转/平移/重排去重、ASE-GA + LJ 实跑、自适应多重度早停与边界外扩、S0–S5 流水线暂停/恢复端到端模拟、耗时校准与 CLI 测试）全部通过。
- **遗留问题**：
  - 🧑 等待人类确认文献基准计算量后，在服务器实机跑测 `tests/data/benchmark/clusters.yaml` 并统计基态找回率。

### P3 远程执行 + 服务器端自愈（已完成，2026-11-18）
- **完成了什么**：
  - `src/qcai_remote/`：`probe.py`（`psutil` + `lscpu -J`）、`handlers.py`（`ImaginaryFreqHandler`、`InstabilityHandler`）、`run_job.py`（`custodian` + `_SafeGaussianErrorHandler` + `formchk`/`cubegen` + 原子更新 `status.json`）、`verify.py`。
  - `src/qcai/remote/`：`ssh.py`（`fabric` + 命令白名单 + 严格 `work_root` 路径校验）、`deploy.py`、`runner.py`（基于 `qtoolkit.ShellIO` 的 `DirectRunner` + 进程组级取消 + `MockRunner`）、`resources.py`、`doctor.py`。
  - `src/qcai/pipeline/db.py` & `cli.py`：SQLModel 持久化与崩溃对账、`qcai doctor/run/status/cancel`。
  - 真实服务器实测与回归集：提交并回收 `H₂` 单点、BSE `GenECP`（`AlAu`）与 10 份黄金样本至 `tests/data/golden/`（涵盖 `Na₆`、`Al₁₃⁻`、`Fe₄(M=13)`、`W@Au₁₂`、`Cu₃Ag₃`、`Al₁₂Cu` 及 `L502`/`L9999`/虚频/`stable=opt` Link1），修复 LF 换行、`GaussianJob` stdin 重定向、`custodian.json` 修正提取、稳定波函数正则与裸 `opt` 异常等实测问题。
- **如何验证**：
  - `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src` 全部通过；
  - `uv run pytest`（70 项单元测试，含 10 份真实黄金样本 100% 回归测试与自愈记录校验）全部通过；
  - `uv run pytest -o addopts="" -m remote` 远程探针集成测试通过。
- **遗留问题**：无（已可进入 P4）。

### P2 输入生成 + 规则引擎 + 规划器（2026-11-18）
- **完成了什么**：
  - `src/qcai/knowledge/rules/*.yaml`：`theory_level.yaml`、`multiplicity.yaml`、`charges.yaml`、`recipes.yaml`（均注明参考文献，且条件只引用元素与体系属性）。
  - `src/qcai/programs/gaussian/writer.py` 与 `program.py`：pymatgen `GaussianInput` 封装（自动 `U` 前缀、ECP/GenECP 区分、Link0、`nosymm`、`stable=opt`、`scf=(xqc,maxcycle=500)`）+ `basis_set_exchange` 覆盖检查与替代基组推荐，并注册 `QCPROGRAMS["gaussian"]`。
  - `src/qcai/planner/`：`rule_engine.py`（输出 `Decision` 与 `overridden` 跟踪）、`multiplicity.py`、`charges.py`、`cost_model.py`（经验核时估计与时间预算收缩）、`planner.py`（参考体系补全、奇偶性/基组覆盖/理论水平一致性/几何合理性校验、Markdown 方案书格式化）。
  - `src/qcai/cli.py`：新增 `qcai gen` 与 `qcai plan`。
- **如何验证**：
  - `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src` 全部通过；
  - `uv run pytest`（53 项单元测试，含第 10 节全分区通用性测试集、Hypothesis 任意元素组合属性测试、基组阻断、公理 A4 一致性、几何合理性、`.gjf` 往返读写及 CLI 测试）全部通过。
- **遗留问题**：
  - 离线 v1 三项基础功能（输入生成、解析、能级/自旋可视化）已交付；进入 P3 需等待人类确认允许在 Linux 服务器安装 `micromamba` 环境与 ABCluster。

### P1 离线核心：解析 + 轨道/自旋可视化（2026-11-18）
- **完成了什么**：
  - `src/qcai/core/`：`models.py`（Pydantic v2 全套核心模型）、`physics.py`（电子数/奇偶校验、`S(S+1)`、自旋污染、磁矩、原子基态多重度、HOMO-LUMO 隙）、`registry.py`（泛型注册表）。
  - `src/qcai/interfaces/`：`ClusterProfile`、`StructureGenerator`、`FigureRenderer`、`JobRunner`、`QCProgram`、`LLMProvider` 6 个抽象接口与全局注册表。
  - `src/qcai/programs/gaussian/parser.py`：cclib 主解析 + 正则补充（`<S²>`、波函数稳定性、终止状态与 `Lnnnn` 错误码、Link1 分段、截断/故障日志频率回退）。
  - `src/qcai/renderers/`：`spec.py`（`FigureSpec` 与 `levels` / `spin` / `dos` / `s2` 构建器）、`mpl/`（Matplotlib 渲染器）、`origin/`（独立子进程串行 `OriginWorker` + `OriginRenderer`）。
  - `src/qcai/cli.py`：`qcai parse <log>` 与 `qcai plot <log> --kind levels|spin|dos|s2 --renderer mpl|origin`。
  - 测试样本：`tests/data/cclib/`（5 份 BSD 协议 Gaussian 16 日志）、`tests/data/faults/`（4 份故障/Link1 日志片段）、`tests/data/golden_inputs/`（10 份覆盖 s/p/d/ECP/双金属/高自旋/故障的 `.gjf` 黄金样本及 `manifest.yaml`）。
- **如何验证**：
  - `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src` 全部通过；
  - `uv run pytest`（30 项单元测试，含公理 A2 静态 AST 检查、手算物理量与 Hypothesis 属性测试、cclib & 故障解析、Matplotlib 与 CLI 测试）全部通过；
  - `uv run pytest -o addopts="" -m origin`（4 项 Origin 2024b 真实后台出图测试）全部通过。
- **遗留问题**：
  - `tests/data/golden_inputs/` 中的 10 份黄金样本 `.gjf` 待 P3 在服务器运行 Gaussian 16 并回收结果至 `tests/data/golden/`。

### P0 环境与能力验证（2026-11-18）
- **完成了什么**：
  - 将仓库切换为开发方案 v2.0 目录约定（固定 Python 3.12，`uv sync` 安装全部本地依赖与 dev 工具，安装 Playwright Chromium）。
  - 保留已填写的 `config/settings.toml`（gitignored），提供 `config/settings.example.toml`、`AGENTS.md`、`README.md`、`docs/QuantumChem_AI_开发方案.md`、`src/qcai/` 与 `src/qcai_remote/` 骨架。
  - 在 `docs/spikes/` 完成全部 11 项本地验证脚本（元素数据、点群容差、结构去重、BSE/genecp、GaussianInput、cclib 开壳层解析、qtoolkit ShellIO、originpro 后台驱动 Origin 2024b、Windows VMD 无界面渲染、Playwright 中文+SVG PDF、pydantic-ai DeepSeekProvider 接口），全部通过并写入 `docs/decisions.md`。
- **如何验证**：
  - `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src`、`uv run pytest` 全部通过；11 个 spike 脚本全部运行验证通过。
- **遗留问题**：
  - 服务器端能力（`custodian`、`tblite`、`Multiwfn` 版本、`ABCluster` 格式、`g16` 读取 BSE `genecp` 块）按方案推迟到 P3 验证，等待人类确认在服务器安装环境。

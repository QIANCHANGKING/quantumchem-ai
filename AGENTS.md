# AGENTS.md — QuantumChem AI 项目规则

> **唯一事实来源**：[`docs/QuantumChem_AI_开发方案.md`](docs/QuantumChem_AI_开发方案.md)（v2.0 复用优先 · 单 AI 执行版）。
> 任何偏离或新增依赖必须写入 [`docs/decisions.md`](docs/decisions.md)。

## 1. 不可违反的设计公理

1. **A1 数值确定性**：所有能量、轨道、自旋数值只来自计算程序输出的解析；LLM 只解释，永不生成数字。
2. **A2 通用性来自规则**：元素差异全部通过元素属性（pymatgen `Element` / ASE 数据）+ YAML 规则表达，代码中严禁出现特定元素的特例分支（如 `if element == "Au"`）。
3. **A3 默认值可见、可覆盖**：每个自动决策生成 `Decision(key, value, reason, source_rule)`，用户可逐项覆盖。
4. **A4 对比量同理论水平**：参考体系（孤立原子、纯主体、离子态）自动补齐，并由代码强制检查理论水平一致。
5. **A5 复用优先**：自研前先查方案第 3 节；新增依赖须写入 `docs/decisions.md`。
6. **A6 扩展靠接口**：体系类型、结构搜索器、渲染器、作业执行器、量化程序、LLM 都通过抽象基类 + 注册表接入。
7. **A7 core 纯净**：`core/`、`planner/`、`analysis/` 不做网络、SSH、子进程或 LLM 调用。
8. **A8 长任务放在服务器端**：失败修复和后处理在服务器上的作业包装脚本内完成，Windows 主机断网或休眠不影响计算。

## 2. 环境与命令规范

- Python 3.12（`uv python pin 3.12`），包管理使用 `uv`。
- Windows + PowerShell 下运行外部命令前先执行：
  ```powershell
  $OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  $env:PYTHONUTF8 = '1'
  ```
- 所有文件使用 UTF-8 编码；路径一律使用 `pathlib.Path`。
- 阶段结束必须全部通过：
  ```powershell
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src
  uv run pytest
  ```

## 3. 安全与禁止事项

- 凭据（SSH 密钥/密码、DeepSeek API Key）只存在 `config/settings.toml`（已被 `.gitignore` 忽略）或 `keyring`，严禁写入代码、git、日志或 LLM 上下文。
- 未经人类确认不得向服务器提交真实计算作业。
- 远程只允许执行白名单命令，读写路径必须严格位于 `work_root` 之下。

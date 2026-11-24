# QuantumChem AI

面向团簇（纯团簇 / 掺杂 / 双金属，元素不限）的量子化学科研助手：用户选择体系、研究目标与精度后，系统自动完成结构搜索 → Gaussian 计算 → 结果解析 → Multiwfn 分析 → Origin / VMD / 3Dmol 出图 → PDF 报告 → DeepSeek 解读。

## 一键打开（Windows 桌面应用封装）

- **首次在新电脑部署**：解压发布包后双击 [一键安装依赖.bat](一键安装依赖.bat) 自动创建 `.venv` 与注册入口（详细步骤见 [使用说明.md](使用说明.md)）
- **标准完整模式（无黑框静默启动 Web + 后台队列 Worker）**：直接双击 [启动量子化学助手.bat](启动量子化学助手.bat)
- **仅界面模式（离线工具 / 结果查看 / DeepSeek 解析与解读，不启远程 Worker）**：双击 [启动量子化学助手(仅界面模式).bat](启动量子化学助手(仅界面模式).bat)
- **模拟演示模式（Mock Worker）**：双击 [启动量子化学助手(模拟演示).bat](启动量子化学助手(模拟演示).bat)
- **一键停止后台服务**：双击 [停止量子化学助手.bat](停止量子化学助手.bat)，或在 Web 侧边栏 /「6. 设置」中点击 **「🛑 停止后台服务」**
- **创建带图标的桌面快捷方式**：双击 [生成桌面快捷方式.bat](生成桌面快捷方式.bat)（或 Web「6. 设置」一键生成），会在桌面生成带有 `assets/qcai.ico` 团簇图标、直连 `qcai-app.exe`（无黑框闪烁）的 `QuantumChem AI 量子化学助手.lnk`
- **命令行入口**：`.\.venv\Scripts\qcai.exe web`（前台日志模式）、`.\.venv\Scripts\qcai-app.exe`（无黑框 GUI 模式）、`.\.venv\Scripts\qcai-web.exe --status / --stop`

> 后台静默模式日志自动保存至 `projects/logs/qcai_web.log` 与 `projects/logs/qcai_worker.log`；重复点击启动器会自动唤起现有实例，不会重复启动 Worker。

## 学术论文与文档索引

| 文件 | 用途 |
|------|------|
| [paper/QuantumChem_AI_Paper.md](paper/QuantumChem_AI_Paper.md) | 介绍 QuantumChem AI 架构、算法与验证结果的学术论文手稿（另提供排版后的 HTML / A4 PDF） |
| [docs/QuantumChem_AI_开发方案.md](docs/QuantumChem_AI_开发方案.md) | 开发方案 v2.0（唯一执行依据） |
| [AGENTS.md](AGENTS.md) | 项目规则与设计公理 |
| [docs/progress.md](docs/progress.md) | 阶段进度、验证情况与“待人类处理”清单 |
| [docs/decisions.md](docs/decisions.md) | 架构与依赖决策记录 |
| [docs/spikes/](docs/spikes/) | P0 阶段能力验证脚本与结论 |

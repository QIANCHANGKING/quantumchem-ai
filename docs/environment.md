# 环境诊断报告 (`qcai doctor`)

> 生成时间：2026-11-24 13:04 UTC（已过滤全部凭据、主机地址与路径隐私）

| 检查项 | 状态 | 详情 | 修复建议 |
|--------|------|------|----------|
| Python 运行时 | ✅ | 3.12.12 | 请运行 `uv python pin 3.12 && uv sync` |
| Origin 2024b | ✅ | 已配置且路径有效 | 在 config/settings.toml [origin].executable 中填写 Origin64.exe 路径 |
| VMD (Windows) | ✅ | 已配置且路径有效 | 在 config/settings.toml [vmd].executable 中填写 vmd.exe 路径 |
| Playwright Chromium | ✅ | 可用 (chrome.exe) | — |

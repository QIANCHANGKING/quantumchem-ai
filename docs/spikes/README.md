# P0 能力验证脚本（Spikes）

运行任意脚本（Windows PowerShell 需先设置 UTF-8）：

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
uv run python docs/spikes/spike_01_elements.py
```

| 脚本 | 验证项 | 结果 |
|------|--------|------|
| `spike_01_elements.py` | pymatgen `Element` + ASE `ground_state_magnetic_moments`（含 Fe/Co/Ni/Cu/Au/Pt 抽查） | ✅ 通过 |
| `spike_02_pointgroup.py` | `PointGroupAnalyzer` 容差（理想与微扰团簇） | ✅ 通过 |
| `spike_03_dedup.py` | 距离矩阵特征值指纹 + `molecule_matcher` 速度与精度 | ✅ 通过（见决策记录） |
| `spike_04_bse_genecp.py` | `basis_set_exchange` 覆盖查询与 `gaussian94` + ECP 块 | ✅ 通过 |
| `spike_05_gaussian_input.py` | pymatgen `GaussianInput`（`nosymm` / `stable=opt` / `GenECP` / Link0 / 往返） | ✅ 通过 |
| `spike_06_cclib_parser.py` | `cclib` 解析开壳层 Gaussian 输出（`atomspins` 等）+ `GaussianOutput` 交叉核对 | ✅ 通过 |
| `spike_07_qtoolkit.py` | `qtoolkit.io.shell.ShellIO` 脚本与状态解析接口 | ✅ 通过 |
| `spike_08_origin.py` | `originpro` 后台驱动 Origin 2024b 导出 PNG/SVG/OPJU | ✅ 通过 |
| `spike_09_vmd.py` | Windows VMD `-dispdev text` + `TachyonInternal` 批处理渲染 | ✅ 通过（带退出码说明） |
| `spike_10_playwright_pdf.py` | Jinja2 → HTML → Playwright Chromium A4 PDF（中文字体 + SVG） | ✅ 通过 |
| `spike_11_pydantic_ai_deepseek.py` | `pydantic-ai` `DeepSeekProvider`、工具调用与 `output_validator` 接口 | ✅ 接口通过（实网调用待 P8 Key） |

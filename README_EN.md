# QuantumChem AI

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![Repository](https://img.shields.io/badge/GitHub-Repository-black.svg)](https://github.com/QIANCHANGKING/quantumchem-ai)
[![Zenodo DOI](https://img.shields.io/badge/Zenodo-DOI-blue.svg)](https://doi.org/10.5281/zenodo.24501860)

**QuantumChem AI** is an open-source, constitutionally governed automation platform for all-element atomic cluster quantum chemistry. Coupling deterministic periodic-table rules with `pydantic-ai` LLM intent parsing and anti-hallucination verification, it automates the full computational workflow from natural-language research prompts to global structural search, permutation-invariant isomer deduplication, fault-tolerant remote HPC execution, wavefunction post-processing, and publication-grade visualization.

---

## Key Architectural Highlights

- **Eight-Article Design Constitution (`C1–C8`)**: Enforced across runtime validators and continuous integration:
  - **AST-Verified Zero-Hardcoding Rule Engine (`C2`, `C3`)**: All functional, dispersion, Basis Set Exchange (`GenECP`), electron-parity, Hund-rule, and adaptive spin-multiplicity rules live in traceable YAML files (`src/qcai/knowledge/rules/*.yaml`). `tests/unit/test_axiom_no_element_branches.py` verifies via Python AST inspection that `src/` contains zero element-symbol conditional branches.
  - **Theory-Level Consistency (`C4`)**: Reference free atoms, neighboring sizes ($n \pm 1$), and ionic vertical/adiabatic states are automatically generated and verified to match cluster functional/basis/ECP specifications.
  - **Anti-Hallucination Numerical Guard (`C1`)**: Read-only LLM result interpretation (`interpret_project`) uses a unit-conversion-aware `@agent.output_validator` (`Ha <-> eV / kcal/mol / kJ/mol / %`) with `ModelRetry` and explicit blocking on ungrounded values.
- **Tri-Axial Principal-Inertia Isomer Deduplication & Symmetry Dopant Enumeration**: Three-stage geometric filtering (distance-matrix eigenvalue spectrum -> tri-axial principal-inertia Hungarian/Kabsch alignment -> genetic/brute-force permutation fallback) achieves $10^{-15}\text{ \AA}$ equivalence precision in $< 8\text{ ms}$, paired with `PointGroupAnalyzer` symmetry-unique substitutional and endohedral dopant enumeration.
- **Resilient Shared-HPC Execution & Three-Section `--Link1--` Self-Healing**: NUMA topology probing (`lscpu -J` + `psutil`), active user-load throttling, elastic core scaling (`4` up to `10–16` cores), SSH auto-reconnect with exit-poll race protection, three-section `--Link1--` (`opt` -> `stable=opt` -> `freq`), and server-side `custodian` 4f SCF escalation + tail-preserving recovery + `ImaginaryFreqHandler`.
- **Multi-Engine Post-Processing & Publication Output**: Version-locked Multiwfn 3.8(dev) parsing (`out_7`, `out_15`, `out_10`, `out_8`), 10 dual-engine Matplotlib / Origin 2024b plot types, inertia-aligned py3Dmol / VMD `TachyonInternal` ray-traced 3D rendering, and Playwright A4 PDF report compilation.

---

## Verified Benchmarks & Production Validation

- **10 Real Gaussian 16 Golden Benchmarks (`tests/data/golden/`)**: Spanning s-block (`Na6`), p-block superatom (`Al13-`), 3d high-spin (`Fe4`), 5d endohedral BSE `GenECP` (`W@Au12`), bimetallic (`Cu3Ag3`), open-shell doped (`Al12Cu`), 2-section `Link1` stability (`link1_stable_opt`), and automated fault recovery (`L9999`, imaginary frequency, and `L502` graceful human flagging).
- **Multiwfn 3.8(dev) Wavefunction Case Study (`tests/data/multiwfn/al12cu/`)**: Full Hirshfeld/ADCH charge, atomic spin population ($f_D(\mathrm{Cu}) = 3.91\%$), 3,000-point TDOS/PDOS, and frontier MO s/p/d decomposition of `Al12Cu`.
- **Heavy Lanthanide `Ln@Au5` (`Gd–Lu`) Autonomous Production Campaign (`paper/data/ln_au5_summary.json`)**: 9 projects, 230 pipeline jobs (221 Gaussian 16 runs totaling 1,399.78 CPU core-hours, 100% convergence with 7 automated 4f repairs and elastic NUMA core scaling), establishing the trivalent $8\mathrm{e}^-$ superatom HOMO–LUMO gap rigidity plateau ($2.524\text{–}2.812\text{ eV}$), $4f$ localized spin decoupling, and divalent $\mathrm{Yb}^{2+}$ spin delocalization.
- **Bilingual 50+50 Scientific Instruction Evaluation (`tests/llm_eval/`)**: **50/50 (100.0%)** on Chinese prompts (`instructions.yaml`) and **50/50 (100.0%)** on matched English prompts (`instructions_en.yaml`) using `deepseek-v4.1-flash`, passing the $\ge 90\%$ `pytest -m llm` gate.

---

## Installation (Python 3.12)

QuantumChem AI targets **Python 3.12** managed via `uv`:

```bash
# 1. Clone repository
git clone https://github.com/QIANCHANGKING/quantumchem-ai
cd quantumchem-ai

# 2. Install locked dependencies into .venv
uv sync

# 3. Optional: install Chromium for A4 PDF reports and E2E browser tests
uv run playwright install chromium

# 4. Optional (only for live SSH HPC / LLM features; NOT required for offline tests)
cp config/settings.example.toml config/settings.toml
# Store DeepSeek API key securely in OS keyring:
uv run python -c "from qcai.config import save_deepseek_key; save_deepseek_key('<YOUR_API_KEY>')"
```

---

## One-Command Offline Verification (115+ Tests)

All static checks, AST constitutional gates, and 115 offline unit + Playwright E2E tests run without external HPC access, Gaussian, Origin, VMD, or API keys:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Optional integration suites (require corresponding local software, SSH cluster, or API credentials):

```bash
uv run pytest -m llm tests/integration/test_deepseek_llm.py     # Live bilingual 50+50 LLM eval
uv run pytest -m origin tests/integration/test_origin_renderer.py
uv run pytest -m vmd tests/integration/test_vmd_and_origin_all.py
uv run pytest -m remote tests/integration/test_remote_ssh.py
```

---

## External Software Dependencies

QuantumChem AI orchestrates standard external quantum-chemistry and visualization packages (not bundled):

- **Gaussian 16 (Rev. C.02)** — commercial license ([gaussian.com](https://gaussian.com))
- **Multiwfn 3.8(dev)** — free academic software ([sobereva.com/multiwfn](http://sobereva.com/multiwfn/))
- **Origin 2024b** — commercial license on Windows ([originlab.com](https://www.originlab.com))
- **VMD** — free academic software ([ks.uiuc.edu/Research/vmd](https://www.ks.uiuc.edu/Research/vmd/))
- **ABCluster / GFN2-xTB (`tblite`)** — global search & semiempirical screening backends

---

## Citation & License

Released under the **MIT License** ([LICENSE](LICENSE)).

```bibtex
@software{qian2026quantumchemai,
  author  = {Qian, Changtian},
  title   = {QuantumChem AI: A Constitutionally Governed, Rule-Driven, and LLM-Assisted Automation Platform for All-Element Atomic Cluster Quantum Chemistry},
  year    = {2026},
  url     = {https://github.com/QIANCHANGKING/quantumchem-ai},
  doi     = {10.5281/zenodo.24501860}
}
```

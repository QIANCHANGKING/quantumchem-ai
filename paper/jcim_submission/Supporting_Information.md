# Supporting Information

**QuantumChem AI: A Rule-Governed Automation Platform with Grounded LLM Assistance for All-Element Atomic Cluster Quantum Chemistry**

Changtian Qian

*Department of Physics, Capital Normal University, Beijing 100048, China*

Repository: `https://github.com/QIANCHANGKING/quantumchem-ai` | Archival DOI: `10.5281/zenodo.24501860`

---

## Section S1: Offline Reproduction and 115+ Automated Verification Guide

1. **Environment Setup (Python 3.12 + uv):**
   - Clone `https://github.com/QIANCHANGKING/quantumchem-ai` (or unpack the Zenodo archive `10.5281/zenodo.24501860`).
   - Run `uv sync` in the repository root to create the locked Python 3.12 virtual environment (`.venv`).
   - Copy `config/settings.example.toml` to `config/settings.toml` only when connecting live SSH clusters or LLM endpoints; offline verification requires zero credentials.
2. **Full Offline Quality & Test Gate (115+ Tests):**
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```
   - The default `pytest` marker configuration (`-m 'not (remote or origin or vmd or llm)'`) executes all 115 offline unit, AST constitutional-gate, reference-log regression, Multiwfn output parsing, renderer, launcher, and headless Chromium Playwright E2E tests.
3. **Live Bilingual 50+50 LLM Benchmark Reproduction (Optional):**
   - Store an OpenAI-compatible DeepSeek API key in the OS keyring (`python -c "from qcai.config import save_deepseek_key; save_deepseek_key('...')"`) or `DEEPSEEK_API_KEY`, then run `uv run pytest -m llm tests/integration/test_deepseek_llm.py`.

---

## Section S2: Complete YAML Rule-Engine Specification

### S2.1 Accuracy Tiers (`theory_level.yaml`)

*Table S2.1: Deterministic accuracy-tier mapping in `src/qcai/knowledge/rules/theory_level.yaml`.*

| Tier | Search | Screening Level | Refinement Level | Tasks | Default K | Rationale & References |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| `fast` | GFN-xTB | PBE-GD3BJ/def2-SVP | None | SP / screen | 5 | GFN-xTB search followed by PBE-D3BJ/def2-SVP fast screening without TZVP refinement. (Perdew, Burke, Ernzerhof, PRL 1996, 77, 3865; Weigend, Ahlrichs, PCCP 2005, 7, 3297) |
| `standard` | GFN-xTB | PBE-GD3BJ/def2-SVP | PBE0-GD3BJ/def2-TZVP | opt, freq | 8 | GFN-xTB search -> PBE-D3BJ/def2-SVP screening -> PBE0-D3BJ/def2-TZVP opt+freq refinement. (Adamo, Barone, JCP 1999, 110, 6158; Grimme, Ehrlich, Goerigk, JCC 2011, 32, 1456) |
| `high` | GFN-xTB | PBE0-GD3BJ/def2-SVP | TPSSh-GD3BJ/def2-TZVP | opt, freq, stable | 12 | PBE0-D3BJ/def2-SVP screening -> TPSSh-D3BJ/def2-TZVP opt+freq+stability check. (Staroverov et al., JCP 2003, 119, 12129; Bauernschmitt, Ahlrichs, JCP 1996, 104, 9047) |

### S2.2 Element-Category and Size Rules (`theory_level.yaml` & `multiplicity.yaml`)

*Table S2.2: AST-verified element-attribute rules (`when` conditions evaluate periodic properties only, zero symbol branches).*

| Rule ID | Trigger Condition (`when`) | Applied Parameters (`then`) | Physical Rationale & References |
| :--- | :--- | :--- | :--- |
| `rule.cluster.nosymm` | `always=True` | `nosymm=True` | Disable symmetry constraints (`nosymm`) during cluster optimization to prevent artificial locking of Jahn-Teller distortions. (Jensen, Introduction to Computational Chemistry, 3rd ed.) |
| `rule.tm.robust_scf_and_stability` | `has_transition_metal=True` | `scf_strategy=robust`, `enable_stability_check=True`, `max_multiplicity_cap=12` | Enable robust SCF (`xqc,maxcycle=500`), wavefunction stability checks, and raise multiplicity cap to 12 for near-degenerate d-block clusters. (Cramer, Truhlar, PCCP 2009, 11, 10757; Bauernschmitt, Ahlrichs, JCP 1996, 104, 9047) |
| `rule.f_block.experimental_warning` | `has_f_block=True` | `f_block_warning=True`, `scf_strategy=robust` | Flag f-block systems (lanthanides/actinides) for potential static correlation/SOC review and enforce robust SCF. (Dolg, Cao, Chem. Rev. 2012, 112, 403) |
| `rule.size.basis_downgrade` | `max_atoms_gt=20`, `has_refinement=True` | `refinement_basis=def2-SVP`, `candidate_k_cap=5` | Downgrade refinement basis to def2-SVP and cap candidate count K=5 when cluster size exceeds 20 atoms. (Weigend, Ahlrichs, PCCP 2005, 7, 3297) |
| `rule.mult.parity_and_atomic_sum` | All compositions | `min_states=2`, `main_cap=6`, `tm_cap=12`, `early_stop=0.5 eV`, `expand=True` | Parity conservation `(Ne + M) mod 2 = 1`, atomic Hund-rule spin upper bound, early stop after 2 higher states, boundary expansion (Szabo, Ostlund, Modern Quantum Chemistry; ASE atomic ground_state_magnetic_moments). |

### S2.3 Charge States and Research Recipes (`charges.yaml` & `recipes.yaml`)

*Table S2.3: Recipe-to-stage, charge-state, and observable mappings.*

| Recipe Key | Default Charges | Pipeline Stages | Derived Analyses | Output Figures | Charge Rationale |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `stability` | `[0]` | `S0_reference, S1_search, S2_dedup, S3_screen, S4_refine, S7_summary` | ground_state, isomer_ranking, binding_energy, delta2_e, fragmentation_energy, doping_energetics | isomer_ranking | Neutral ground state by default (unless user specifies explicit charges). |
| `electronic` | `[0]` | `S0_reference, S1_search, S2_dedup, S3_screen, S4_refine, S6_postprocess, S7_summary` | mo_levels, homo_lumo_gap, tdos_pdos, orbital_composition, jellium_electron_count, charge_transfer | levels, dos, orbital_composition | Neutral state by default (unless user specifies explicit charges). |
| `magnetism` | `[0]` | `S0_reference, S1_search, S2_dedup, S3_screen, S4_refine, S6_postprocess, S7_summary` | spin_ladder, magnetic_moment, atomic_spin_population, spin_localization, s2_contamination | spin_ladder, spin, s2 | Neutral state by default (unless user specifies explicit charges). |
| `pes` | `[-1, 0]` | `S0_reference, S1_search, S2_dedup, S3_screen, S4_refine, S5_ionic, S7_summary` | vde, ade, experimental_comparison | vde_ade_comparison | Requires anion optimization, neutral single-point at anion geometry (VDE), and neutral optimization (ADE). |
| `ionization` | `[1, 0, -1]` | `S0_reference, S1_search, S2_dedup, S3_screen, S4_refine, S5_ionic, S7_summary` | vip, vea, aip, aea | ionization_energetics | Requires cation SP/opt (VIP/AIP), neutral opt, and anion SP/opt (VEA/AEA). |
| `size_evolution` | `[0]` | `S0_reference, S1_search, S2_dedup, S3_screen, S4_refine, S7_summary` | size_trends, delta2_e, fragmentation_energy | size_evolution_multipanel | Neutral sequence along n = a..b using selected property template. |
| `custom` | `[0]` | `S0_reference, S1_search, S2_dedup, S3_screen, S4_refine, S6_postprocess, S7_summary` | ground_state, mo_levels | levels | Neutral state by default; extensible per requested analysis. |

---

## Section S3: Reference Benchmarks, Heavy Lanthanide Dataset, Recovery Trace, and Coordinates

### S3.1 Ten Reference Gaussian 16 Benchmarks (`tests/data/golden/`)

*Table S3.1: Parsed quantum-chemical metrics and server-side `custodian` recovery outcomes across all 10 reference Gaussian 16 benchmark runs.*

| Benchmark ID | Species ($N$) | $q / M$ | Status | SCF Energy (Ha) | Gap $E_{\mathrm{g}}$ (eV) | $\langle S^2 \rangle$ | $n_{\text{imag}}$ | Link1 / Stable | Custodian Recovery Log |
| :--- | :--- | :---: | :---: | ---: | ---: | :---: | :---: | :---: | :--- |
| `na6` | Na6 (6) | 0 / 1 | `done` | -972.741909 | 1.090 | -- | 0 | 1 / -- | Normal convergence; zero imaginary frequencies. |
| `al13_anion` | Al13- (13) | -1 / 1 | `done` | -3149.265871 | 1.952 | -- | 0 | 1 / -- | 40e- closed-shell superatom; normal convergence. |
| `fe4` | Fe4 (4) | 0 / 13 | `done` | -5053.212837 | 0.259 | 42.0214 | 0 | 1 / -- | 3d high-spin (M=13); clean spin channels (ideal 42.0000). |
| `w_au12` | W@Au12 (13) | 0 / 1 | `done` | -1696.516466 | 3.337 | -- | 0 | 1 / -- | BSE GenECP 18e- endohedral superatom; normal convergence. |
| `cu3ag3` | Cu3Ag3 (6) | 0 / 1 | `done` | -5361.213378 | 1.908 | -- | 0 | 1 / -- | Bimetallic mixed basis/ECP; normal convergence. |
| `al12cu` | Al12Cu (13) | 0 / 2 | `done` | -4546.981501 | 0.277 | 0.8047 | 0 | 1 / -- | ImaginaryFreqHandler perturbed Jahn-Teller saddle to true minimum. |
| `fault_imag_freq` | Au4 saddle (4) | 0 / 1 | `done` | -543.167628 | 0.990 | -- | 0 | 1 / -- | ImaginaryFreqHandler displaced along normal mode (step_scale=0.25). |
| `fault_opt_maxsteps` | L9999 test (3) | 0 / 2 | `done` | -3427.042431 | 0.257 | 0.7500 | 0 | 1 / -- | Step-limit handler resumed geometry & raised opt_max_cycles=100. |
| `fault_scf_noconv` | L502 test (4) | 0 / 5 | `failed` | -5052.846030 | -- | 8.4967 | 0 | 1 / -- | Escalated maxcycle=100 -> xqc; cleanly marked failed & needs_human=True. |
| `link1_stable_opt` | Link1 test (2) | 0 / 3 | `done` | -3015.648103 | 2.287 | 2.0013 | 0 | 2 / True | 2-section Link1 parsed cleanly; wavefunction confirmed stable=True. |

### S3.2 Complete S4 Converged Isomers for Heavy Lanthanide Ln@Au5 (Gd-Lu)

*Table S3.2: All 19 converged S4 `PBE0-D3BJ/def2-TZVP (GenECP)` structures across the 8-element campaign plus standalone `Tm@Au5` reproduction (`proj_a9065c59`).*

| Element (Z) | Project ID | Rank | Job ID | $M$ | $E_{\text{SCF}}$ (Ha) | $\Delta E$ (eV) | $E_b$ (eV/atom) | $E_{\mathrm{g}}$ (eV) | $\langle S^2 \rangle$ | $f_{\min}$ ($\text{cm}^{-1}$) | PG | $d_{\text{Ln-Au}}$ ($\text{\AA}$) | $q_{\text{APT}}$ / spin(Ln) |
| :--- | :--- | :---: | :--- | :---: | ---: | ---: | ---: | ---: | :---: | ---: | :---: | :---: | :---: |
| Gd (64) | `proj_2c89192f` | 1 | `proj_2c89192f__s4__GdAu5_q0_i6_m8` | 8 | -1444.567777 | 0.0000 | 1.9915 | 1.679 | 15.7687 | 21.55 | Cs | 2.934+/-0.107 | +0.44 / +7.74 |
| Gd (64) | `proj_2c89192f` | 2 | `proj_2c89192f__s4__GdAu5_q0_i5_m8` | 8 | -1444.567776 | 0.0000 | 1.9915 | 1.678 | 15.7687 | 21.56 | Cs | 2.934+/-0.105 | +0.44 / +7.74 |
| Gd (64) | `proj_2c89192f` | 3 | `proj_2c89192f__s4__GdAu5_q0_i1_m10` | 10 | -1444.561747 | 0.1641 | 1.9641 | 1.429 | 24.7504 | 17.43 | Cs | 2.982+/-0.025 | +0.51 / +8.15 |
| Tb (65) | `proj_19154707` | 1 | `proj_19154707__s4__TbAu5_q0_i1_m7` | 7 | -1503.335694 | 0.0000 | 2.4078 | 2.665 | 12.0105 | 14.96 | Cs | 2.827+/-0.089 | +0.97 / +6.16 |
| Tb (65) | `proj_19154707` | 2 | `proj_19154707__s4__TbAu5_q0_i3_m7` | 7 | -1503.335354 | 0.0092 | 2.4063 | 2.478 | 12.0127 | 11.34 | C2v | 2.826+/-0.050 | +0.84 / +6.18 |
| Tb (65) | `proj_19154707` | 3 | `proj_19154707__s4__TbAu5_q0_i0_m9` | 9 | -1503.289812 | 1.2485 | 2.1997 | 2.311 | 20.0007 | 8.57 | C2v | 2.826+/-0.171 | +1.17 / +8.06 |
| Dy (66) | `proj_7a0ee451` | 1 | `proj_7a0ee451__s4__DyAu5_q0_i4_m6` | 6 | -1563.991806 | 0.0000 | 2.2908 | 2.702 | 8.7572 | 15.41 | Cs | 2.815+/-0.089 | +0.94 / +5.05 |
| Dy (66) | `proj_7a0ee451` | 2 | `proj_7a0ee451__s4__DyAu5_q0_i5_m8` | 8 | -1563.964931 | 0.7313 | 2.1689 | 1.505 | 15.7504 | 20.94 | Cs | 2.955+/-0.031 | +0.54 / +6.11 |
| Dy (66) | `proj_7a0ee451` | 3 | `proj_7a0ee451__s4__DyAu5_q0_i2_m6` | 6 | -1563.957081 | 0.9449 | 2.1333 | 2.154 | 8.7659 | 35.11 | C4v | 3.123+/-0.478 | +0.44 / +5.67 |
| Ho (67) | `proj_fc156187` | 1 | `proj_fc156187__s4__HoAu5_q0_i0_m5` | 5 | -1627.180455 | 0.0000 | 1.9691 | 2.754 | 6.0000 | 10.70 | C2v | 2.827+/-0.160 | +1.15 / +4.10 |
| Er (68) | `proj_fa892f93` | 1 | `proj_fa892f93__s4__ErAu5_q0_i4_m4` | 4 | -1694.269982 | 0.0000 | 2.0254 | 2.709 | 3.7500 | 14.51 | Cs | 2.791+/-0.080 | +0.92 / +3.06 |
| Er (68) | `proj_fa892f93` | 2 | `proj_fa892f93__s4__ErAu5_q0_i6_m4` | 4 | -1694.269048 | 0.0254 | 2.0211 | 2.428 | 3.7500 | 9.55 | C2v | 2.787+/-0.044 | +0.81 / +3.05 |
| Er (68) | `proj_fa892f93` | 3 | `proj_fa892f93__s4__ErAu5_q0_i1_m4` | 4 | -1694.228014 | 1.1420 | 1.8350 | 1.516 | 3.7501 | 21.65 | Cs | 2.946+/-0.012 | +0.59 / +2.20 |
| Tm (69) | `proj_735cfc68` | 1 | `proj_735cfc68__s4__TmAu5_q0_i0_m3` | 3 | -1764.511111 | 0.0000 | 1.7998 | 2.524 | 2.0000 | 10.14 | C2v | 2.805+/-0.150 | +1.11 / +2.04 |
| Tm (69) | `proj_a9065c59` | 1 | `proj_a9065c59__s4__TmAu5_q0_i0_m3` | 3 | -1764.510373 | 0.0000 | 1.7964 | 2.521 | 2.0000 | 9.76 | C2v | 2.805+/-0.150 | +1.11 / +2.04 |
| Yb (70) | `proj_51ac0f99` | 1 | `proj_51ac0f99__s4__YbAu5_q0_i6_m2` | 2 | -1838.137089 | 0.0000 | 1.8024 | 1.499 | 0.7501 | 21.83 | Cs | 2.928+/-0.016 | +0.57 / +0.18 |
| Yb (70) | `proj_51ac0f99` | 2 | `proj_51ac0f99__s4__YbAu5_q0_i0_m2` | 2 | -1838.137089 | 0.0000 | 1.8024 | 1.499 | 0.7501 | 21.90 | Cs | 2.928+/-0.017 | +0.57 / +0.18 |
| Yb (70) | `proj_51ac0f99` | 3 | `proj_51ac0f99__s4__YbAu5_q0_i2_m2` | 2 | -1838.134336 | 0.0749 | 1.7900 | 1.799 | 0.7500 | 16.80 | Cs | 2.947+/-0.056 | +0.63 / +0.06 |
| Lu (71) | `proj_9f91b2dc` | 1 | `proj_9f91b2dc__s4__LuAu5_q0_i0_m1` | 1 | -1915.063709 | 0.0000 | 2.2475 | 2.812 | -- | 10.68 | C2v | 2.782+/-0.143 | +1.06 / 0.00 |

### S3.3 Automated Server-Side `custodian` 4f Recovery Records (7 Fixes, 100% Success)

*Table S3.3: Complete automated fault-recovery trace from the 230-job `Ln@Au5` production campaign.*

| Project ID | Job ID | Stage | Cluster | $M$ | Detected Error | Automated Recovery Action |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- |
| `proj_19154707` | `proj_19154707__s3__TbAu5_q0_i3_m7` | `S3_screen` | `TbAu5_9` | 7 | SCF convergence failure | `scf=(yqc,maxcycle=512,vshift=500)` |
| `proj_19154707` | `proj_19154707__s4__TbAu5_q0_i0_m9` | `S4_refine` | `TbAu5_19` | 9 | Imaginary frequency | `perturb_along_imag_mode (step_scale=0.25)` |
| `proj_7a0ee451` | `proj_7a0ee451__s3__DyAu5_q0_i1_m10` | `S3_screen` | `DyAu5_1` | 10 | SCF convergence failure | `scf=(yqc,maxcycle=512,vshift=500)` |
| `proj_7a0ee451` | `proj_7a0ee451__s3__DyAu5_q0_i2_m2` | `S3_screen` | `DyAu5_2` | 2 | SCF convergence failure | `scf=(yqc,maxcycle=512,vshift=500)` |
| `proj_7a0ee451` | `proj_7a0ee451__s4__DyAu5_q0_i4_m6` | `S4_refine` | `DyAu5_4` | 6 | Optimization step limit | `from_final_structure` + `opt_max_cycles=100` |
| `proj_fa892f93` | `proj_fa892f93__s3__ErAu5_q0_i1_m8` | `S3_screen` | `ErAu5_1` | 8 | SCF convergence failure | `scf=(yqc,maxcycle=512,vshift=500)` |
| `proj_fa892f93` | `proj_fa892f93__s3__ErAu5_q0_i7_m8` | `S3_screen` | `ErAu5_7` | 8 | SCF convergence failure | `scf=(yqc,maxcycle=512,vshift=500)` |

### S3.4 Optimized Cartesian Coordinates (Angstrom)

#### S3.4.1 Six Converged Reference Benchmark Clusters

**na6** (q=0, M=1, E=-972.741909 Ha)
```xyz
6
na6 q=0 M=1 E=-972.741909 Ha
Na      -0.000243     0.000855     1.482626
Na       3.058598    -0.000729     0.031652
Na       0.945984     2.910997     0.034901
Na      -2.475515     1.798389     0.033364
Na      -2.474494    -1.798805     0.032591
Na       0.945671    -2.910706     0.034866
```

**al13_anion** (q=-1, M=1, E=-3149.265871 Ha)
```xyz
13
al13_anion q=-1 M=1 E=-3149.265871 Ha
Al       0.000000    -0.000000     0.000000
Al      -0.000000     1.400172     2.265551
Al      -0.000000    -1.400172     2.265551
Al      -0.000000     1.400172    -2.265551
Al      -0.000000    -1.400172    -2.265551
Al       1.400172     2.265551    -0.000000
Al      -1.400172     2.265551     0.000000
Al       1.400172    -2.265551    -0.000000
Al      -1.400172    -2.265551    -0.000000
Al       2.265551    -0.000000     1.400172
Al      -2.265551    -0.000000     1.400172
Al       2.265551     0.000000    -1.400172
Al      -2.265551     0.000000    -1.400172
```

**fe4** (q=0, M=13, E=-5053.212837 Ha)
```xyz
4
fe4 q=0 M=13 E=-5053.212837 Ha
Fe      -0.035069     0.060723     1.386948
Fe       1.295866    -0.060782    -0.495377
Fe      -0.665509     1.152690    -0.396209
Fe      -0.595289    -1.152630    -0.495363
```

**w_au12** (q=0, M=1, E=-1696.516466 Ha)
```xyz
13
w_au12 q=0 M=1 E=-1696.516466 Ha
W        0.000000     0.000000     0.000000
Au       0.000000     1.445007     2.338070
Au       0.000000    -1.445007     2.338070
Au       0.000000     1.445007    -2.338070
Au       0.000000    -1.445007    -2.338070
Au       1.445007     2.338070     0.000000
Au      -1.445007     2.338070     0.000000
Au       1.445007    -2.338070     0.000000
Au      -1.445007    -2.338070     0.000000
Au       2.338070     0.000000     1.445007
Au      -2.338070     0.000000     1.445007
Au       2.338070     0.000000    -1.445007
Au      -2.338070     0.000000    -1.445007
```

**cu3ag3** (q=0, M=1, E=-5361.213378 Ha)
```xyz
6
cu3ag3 q=0 M=1 E=-5361.213378 Ha
Cu       0.020123     0.019497     0.000000
Cu       2.429877     0.019497     0.000000
Cu       1.225000     2.100879     0.000000
Ag      -1.289886     2.168157    -0.000000
Ag       3.739886     2.168157    -0.000000
Ag       1.225000    -2.189361    -0.000000
```

**al12cu** (q=0, M=2, E=-4546.981501 Ha)
```xyz
13
al12cu q=0 M=2 E=-4546.981501 Ha
Cu       0.000092     0.000048    -0.000101
Al       0.081319     1.359470     2.185761
Al      -0.000981    -1.433132     2.286157
Al       0.001008     1.433070    -2.286233
Al      -0.081611    -1.359758    -2.185651
Al       1.433458     2.321631     0.000900
Al      -1.305815     2.217726    -0.061562
Al       1.305936    -2.217621     0.061514
Al      -1.433427    -2.321637    -0.000634
Al       2.292062     0.016908     1.421761
Al      -2.174354    -0.099237     1.306945
Al       2.174384     0.099350    -1.307091
Al      -2.292069    -0.016819    -1.421766
```

#### S3.4.2 Eight Heavy Lanthanide Ln@Au5 (Gd-Lu) Ground-State Coordinates

**Gd@Au5 Ground State (`GdAu5_gs.xyz`)**
```xyz
6
Gd@Au5 ground state (proj_2c89192f, PBE0/def2-TZVP, M=8, E=-1444.567777 Ha, Eg=1.679 eV)
Au        -1.861628      -1.459457       0.046773
Au         0.591427       1.368844      -0.988200
Au         2.553699       0.000786       0.536858
Au         0.592190      -1.369318      -0.987740
Au        -1.860820       1.460471       0.048091
Gd        -0.018623      -0.001661       1.683726
```

**Tb@Au5 Ground State (`TbAu5_gs.xyz`)**
```xyz
6
Tb@Au5 ground state (proj_19154707, PBE0/def2-TZVP, M=7, E=-1503.335694 Ha, Eg=2.665 eV)
Au         2.710350       0.083062      -0.944989
Au         1.280180       1.699032       0.698998
Au        -1.310665       1.677517       0.700124
Au         0.032580      -2.980650       0.827058
Au        -2.715507       0.037732      -0.942135
Tb         0.003794      -0.640371      -0.420214
```

**Dy@Au5 Ground State (`DyAu5_gs.xyz`)**
```xyz
6
Dy@Au5 ground state (proj_7a0ee451, PBE0/def2-TZVP, M=6, E=-1563.991806 Ha, Eg=2.702 eV)
Au        -2.707577      -0.039445      -0.953050
Au         2.689270      -0.076419      -0.966423
Au         1.285014      -1.690399       0.714326
Au         0.034436       2.944831       0.847803
Au        -1.305566      -1.659584       0.709813
Dy         0.005362       0.631525      -0.427228
```

**Ho@Au5 Ground State (`HoAu5_gs.xyz`)**
```xyz
6
Ho@Au5 ground state (proj_fc156187, PBE0/def2-TZVP, M=5, E=-1627.180455 Ha, Eg=2.754 eV)
Au        -1.179955       2.386076       0.001355
Au         1.989508      -0.000027       2.284678
Au        -1.170782      -2.389098      -0.003253
Au        -2.176945      -0.003529      -0.000900
Au         1.993711       0.004797      -2.281985
Ho         0.650221       0.002128       0.000125
```

**Er@Au5 Ground State (`ErAu5_gs.xyz`)**
```xyz
6
Er@Au5 ground state (proj_fa892f93, PBE0/def2-TZVP, M=4, E=-1694.269982 Ha, Eg=2.709 eV)
Au         1.281300      -1.690156      -0.721476
Au        -1.311407      -1.669953      -0.723929
Au         0.029536       2.957102      -0.845106
Au         2.650470      -0.081319       0.991685
Au        -2.653139      -0.038372       0.991121
Er         0.003816       0.615537       0.362357
```

**Tm@Au5 Ground State (`TmAu5_gs.xyz`)**
```xyz
6
Tm@Au5 ground state (proj_735cfc68, PBE0/def2-TZVP, M=3, E=-1764.511111 Ha, Eg=2.524 eV)
Au        -1.918960       0.006453       2.315292
Au         1.120801      -2.380928       0.004703
Au        -1.916149      -0.002618      -2.316989
Au         2.149741      -0.002806       0.001200
Au         1.127958       2.378509      -0.004121
Tm        -0.656879       0.001621      -0.000100
```

**Yb@Au5 Ground State (`YbAu5_gs.xyz`)**
```xyz
6
Yb@Au5 ground state (proj_51ac0f99, PBE0/def2-TZVP, M=2, E=-1838.137089 Ha, Eg=1.499 eV)
Au         2.642157       0.001264       0.368030
Au        -1.926903      -1.420842      -0.015737
Au         0.598752      -1.429510      -0.882683
Au         0.598077       1.427793      -0.884450
Au        -1.927391       1.421183      -0.015482
Yb         0.017424       0.000128       1.627964
```

**Lu@Au5 Ground State (`LuAu5_gs.xyz`)**
```xyz
6
Lu@Au5 ground state (proj_9f91b2dc, PBE0/def2-TZVP, M=1, E=-1915.063709 Ha, Eg=2.812 eV)
Au         1.106391      -2.372169      -0.007395
Au        -1.913485      -0.005102       2.282899
Au        -1.914163       0.010089      -2.282478
Au         1.115599       2.369122       0.007231
Au         2.162501      -0.003624      -0.000284
Lu        -0.626859       0.001896       0.000030
```


---

## Section S4: Complete Bilingual (50 Chinese + 50 English) Instruction Benchmark

Live end-to-end evaluation was executed via `tests/llm_eval/eval_runner.py` against `deepseek-v4.1-flash` on both the Chinese benchmark (`tests/llm_eval/instructions.yaml`: **50/50 = 100.0%**) and the matched English benchmark (`tests/llm_eval/instructions_en.yaml`: **50/50 = 100.0%**). Both suites exceed the 90% acceptance gate (`pytest -m llm`).

*Table S4.1: Category-level bilingual parsing accuracy across all 50 paired scientific instructions.*

| Category | Cases | Chinese Pass / Total | Chinese Acc. | English Pass / Total | English Acc. |
| :--- | :---: | :---: | :---: | :---: | :---: |
| s-block | 6 | 6/6 | 100.0% | 6/6 | 100.0% |
| p-block | 8 | 8/8 | 100.0% | 8/8 | 100.0% |
| 3d-TM / doped | 12 | 12/12 | 100.0% | 12/12 | 100.0% |
| 4d/5d-TM & bimetallic | 13 | 13/13 | 100.0% | 13/13 | 100.0% |
| Lanthanide (4f) | 3 | 3/3 | 100.0% | 3/3 | 100.0% |
| Ambiguous (clarification) | 8 | 8/8 | 100.0% | 8/8 | 100.0% |
| **Total** | **50** | **50/50** | **100.0%** | **50/50** | **100.0%** |

*Table S4.2: Complete 50-item paired evaluation matrix (English prompt text from `instructions_en.yaml` paired with identical-schema Chinese benchmark outcomes from `instructions.yaml`).*

| ID | Category | English Instruction Prompt | Expected Target | ZH Outcome | EN Outcome |
| :---: | :--- | :--- | :--- | :---: | :---: |
| 1 | s-block | Study the structure and stability of the Na6 cluster at standard accuracy | `comp={'Na': 6}; rec=stability; acc=standard` | PASS (4.4s) | PASS (4.4s) |
| 2 | s-block | Compute the electronic structure of the Li8 cluster and check whether it is a magic-number cluster | `comp={'Li': 8}; rec=electronic; acc=standard` | PASS (3.5s) | PASS (3.7s) |
| 3 | s-block | Perform a fast assessment of the ground-state structure of the K4 cluster | `comp={'K': 4}; rec=stability; acc=fast` | PASS (3.3s) | PASS (5.0s) |
| 4 | s-block | Compute the stability and electronic structure of the Na8 cluster at high accuracy | `comp={'Na': 8}; rec=stability,electronic; acc=high` | PASS (3.9s) | PASS (3.3s) |
| 5 | s-block | Analyze the size evolution trend from Na4 to Na8 clusters with a 10-hour time budget | `comp={'Na': [4, 8]}; rec=size_evolution; acc=standard; t=10.0h` | PASS (3.7s) | PASS (5.2s) |
| 6 | p-block | Calculate the electronic structure and stability of the B12 cluster | `comp={'B': 12}; rec=electronic,stability; acc=standard` | PASS (5.2s) | PASS (4.5s) |
| 7 | p-block | Investigate the electronic structure and HOMO-LUMO gap of the Al13 anion (charge -1) | `comp={'Al': 13}; rec=electronic; acc=standard; q=[-1]` | PASS (3.9s) | PASS (3.6s) |
| 8 | p-block | Compute the structural stability of the Si10 cluster at high accuracy | `comp={'Si': 10}; rec=stability; acc=high` | PASS (3.5s) | PASS (4.9s) |
| 9 | p-block | Compare the photoelectron spectrum VDE and ADE of the Si6 cluster | `comp={'Si': 6}; rec=pes; acc=standard` | PASS (3.2s) | PASS (6.2s) |
| 10 | p-block | Compute the ionization energy and electron affinity of the Ge8 cluster | `comp={'Ge': 8}; rec=ionization; acc=standard` | PASS (7.3s) | PASS (7.6s) |
| 11 | p-block | Analyze the size evolution and structural stability of Al5 to Al13 clusters | `comp={'Al': [5, 13]}; rec=size_evolution,stability; acc=standard` | PASS (4.2s) | PASS (5.5s) |
| 12 | 3d-TM / doped | Calculate the magnetism and spin-state distribution of the Fe4 cluster | `comp={'Fe': 4}; rec=magnetism; acc=standard` | PASS (6.8s) | PASS (4.2s) |
| 13 | 3d-TM / doped | Study the structural stability and magnetic moment of the Co6 cluster at high accuracy | `comp={'Co': 6}; rec=stability,magnetism; acc=high` | PASS (3.2s) | PASS (10.4s) |
| 14 | 3d-TM / doped | Investigate the stability and magnetism of Ni-doped Al6 to Al13 (Al6-13Ni) clusters at standard accuracy with a 12-hour budget | `comp={'Al': [6, 13], 'Ni': 1}; rec=stability,magnetism; acc=standard; t=12.0h` | PASS (4.0s) | PASS (4.7s) |
| 15 | 3d-TM / doped | Compute the electronic structure and stability of Ti-doped Si12 (TiSi12) | `comp={'Ti': 1, 'Si': 12}; rec=electronic,stability; acc=standard` | PASS (4.9s) | PASS (4.0s) |
| 16 | 3d-TM / doped | Perform a fast screening of the magnetism of the Cr3 cluster | `comp={'Cr': 3}; rec=magnetism; acc=fast` | PASS (5.7s) | PASS (5.0s) |
| 17 | 3d-TM / doped | Calculate the spin multiplicity ladder of the Mn4 cluster with a 6-hour time budget | `comp={'Mn': 4}; rec=magnetism; acc=standard; t=6.0h` | PASS (4.7s) | PASS (3.9s) |
| 18 | 3d-TM / doped | Study the structural stability and photoelectron spectrum comparison of the Cu6 cluster | `comp={'Cu': 6}; rec=stability,pes; acc=standard` | PASS (11.2s) | PASS (3.7s) |
| 19 | 3d-TM / doped | Calculate the electronic structure and magnetism of the V2Al6 cluster | `comp={'V': 2, 'Al': 6}; rec=electronic,magnetism; acc=standard` | PASS (4.4s) | PASS (6.2s) |
| 20 | 4d/5d-TM & bimetallic | Investigate the structural stability of the Pd6 cluster | `comp={'Pd': 6}; rec=stability; acc=standard` | PASS (3.7s) | PASS (4.2s) |
| 21 | 4d/5d-TM & bimetallic | Calculate the stability and electronic structure of the Pt4 cluster at high accuracy | `comp={'Pt': 4}; rec=stability,electronic; acc=high` | PASS (3.0s) | PASS (3.0s) |
| 22 | 4d/5d-TM & bimetallic | Study the photoelectron spectrum and electronic structure of the Au8 cluster | `comp={'Au': 8}; rec=pes,electronic; acc=standard` | PASS (3.2s) | PASS (6.3s) |
| 23 | 4d/5d-TM & bimetallic | Compute the electronic structure and closed-shell superatom properties of the endohedral W@Au12 cluster | `comp={'W': 1, 'Au': 12}; rec=electronic; acc=standard` | PASS (10.3s) | PASS (4.4s) |
| 24 | 4d/5d-TM & bimetallic | Compute the magnetism and structural stability of the Rh5 cluster with a 15-hour budget | `comp={'Rh': 5}; rec=magnetism,stability; acc=standard; t=15.0h` | PASS (3.6s) | PASS (5.2s) |
| 25 | 4d/5d-TM & bimetallic | Investigate the electronic structure and ionization energy of the MoAu5 cluster | `comp={'Mo': 1, 'Au': 5}; rec=electronic,ionization; acc=standard` | PASS (5.7s) | PASS (6.0s) |
| 26 | 4d/5d-TM & bimetallic | Run a fast calculation of the stability of the Ag6 cluster | `comp={'Ag': 6}; rec=stability; acc=fast` | PASS (3.4s) | PASS (3.5s) |
| 27 | 4d/5d-TM & bimetallic | Study the stability and electronic structure of the bimetallic Cu3Ag3 alloy cluster | `comp={'Cu': 3, 'Ag': 3}; rec=stability,electronic; acc=standard` | PASS (3.6s) | PASS (3.3s) |
| 28 | 4d/5d-TM & bimetallic | Compute the mixing energy and structural stability of the bimetallic Au4Ag4 cluster at high accuracy | `comp={'Au': 4, 'Ag': 4}; rec=stability; acc=high` | PASS (4.8s) | PASS (3.3s) |
| 29 | 4d/5d-TM & bimetallic | Investigate the electronic structure and photoelectron spectrum of the Pt2Au4 alloy cluster | `comp={'Pt': 2, 'Au': 4}; rec=electronic,pes; acc=standard` | PASS (4.1s) | PASS (3.7s) |
| 30 | 4d/5d-TM & bimetallic | Analyze the magnetism and structural stability of the bimetallic Cu2Pd4 cluster | `comp={'Cu': 2, 'Pd': 4}; rec=magnetism,stability; acc=standard` | PASS (5.3s) | PASS (3.8s) |
| 31 | Lanthanide (4f) | Investigate the magnetism of the Gd-doped Al12 (GdAl12) cluster | `comp={'Gd': 1, 'Al': 12}; rec=magnetism; acc=standard` | PASS (3.5s) | PASS (4.2s) |
| 32 | Lanthanide (4f) | Perform a fast assessment of the stability and spin properties of Eu-doped Au6 (EuAu6) | `comp={'Eu': 1, 'Au': 6}; rec=stability,magnetism; acc=fast` | PASS (12.4s) | PASS (4.4s) |
| 33 | Lanthanide (4f) | Calculate the electronic structure of the CeSi10 cluster with a 24-hour budget | `comp={'Ce': 1, 'Si': 10}; rec=electronic; acc=standard; t=24.0h` | PASS (4.8s) | PASS (3.6s) |
| 34 | p-block | Study the stability and ionization energy of the C10 cluster at standard accuracy | `comp={'C': 10}; rec=stability,ionization; acc=standard` | PASS (4.4s) | PASS (8.9s) |
| 35 | s-block | Compute the ionization energy and electron affinity of the Mg6 cluster at high accuracy | `comp={'Mg': 6}; rec=ionization; acc=high` | PASS (8.3s) | PASS (3.8s) |
| 36 | 4d/5d-TM & bimetallic | Analyze the size evolution properties of Au3 to Au8 clusters with an 18-hour time budget | `comp={'Au': [3, 8]}; rec=size_evolution; acc=standard; t=18.0h` | PASS (4.2s) | PASS (6.3s) |
| 37 | 3d-TM / doped | Investigate the magnetic moment and spin population of Fe-doped Au5 (FeAu5) | `comp={'Fe': 1, 'Au': 5}; rec=magnetism; acc=standard` | PASS (4.4s) | PASS (7.2s) |
| 38 | 3d-TM / doped | Compute the electronic structure and stability of the CoAl6 cation (charge +1) | `comp={'Co': 1, 'Al': 6}; rec=electronic,stability; acc=standard; q=[1]` | PASS (3.5s) | PASS (3.6s) |
| 39 | 3d-TM / doped | Study the photoelectron spectrum and magnetism of the Ni4 anion (charge -1) | `comp={'Ni': 4}; rec=pes,magnetism; acc=standard; q=[-1]` | PASS (3.6s) | PASS (4.0s) |
| 40 | p-block | Run a fast scan of the structural stability of the Ga8 cluster with a 4-hour budget | `comp={'Ga': 8}; rec=stability; acc=fast; t=4.0h` | PASS (11.3s) | PASS (3.8s) |
| 41 | 4d/5d-TM & bimetallic | Compute the magnetism, electronic structure, and stability of the bimetallic Ru3Cu3 cluster | `comp={'Ru': 3, 'Cu': 3}; rec=magnetism,electronic,stability; acc=standard` | PASS (3.3s) | PASS (4.7s) |
| 42 | 3d-TM / doped | Study the stability and electronic structure of the Zn8 cluster | `comp={'Zn': 8}; rec=stability,electronic; acc=standard` | PASS (5.8s) | PASS (4.0s) |
| 43 | Ambiguous (clarification) | Compute the stability of a metal cluster | `clarification=True` | PASS (6.1s) | PASS (6.3s) |
| 44 | Ambiguous (clarification) | Run a gold cluster calculation and check its magnetism | `clarification=True` | PASS (6.5s) | PASS (17.3s) |
| 45 | Ambiguous (clarification) | I want to study Al-Ni alloy clusters at high accuracy | `clarification=True` | PASS (12.2s) | PASS (12.8s) |
| 46 | Ambiguous (clarification) | Run a structural search and property analysis | `clarification=True` | PASS (4.7s) | PASS (7.2s) |
| 47 | Ambiguous (clarification) | Use DFT to compare the HOMO-LUMO gaps of a few small clusters | `clarification=True` | PASS (17.3s) | PASS (8.3s) |
| 48 | Ambiguous (clarification) | Check the photoelectron spectrum of Fe clusters | `clarification=True` | PASS (12.4s) | PASS (7.7s) |
| 49 | Ambiguous (clarification) | Study the size evolution of silicon clusters with an 8-hour budget | `clarification=True` | PASS (9.2s) | PASS (14.9s) |
| 50 | Ambiguous (clarification) | Recompute the previous result | `clarification=True` | PASS (3.8s) | PASS (6.2s) |

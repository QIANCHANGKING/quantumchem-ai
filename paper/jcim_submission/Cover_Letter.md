Department of Physics  
Capital Normal University  
Beijing 100048, China  
November 24, 2026

Prof. Kenneth M. Merz, Jr.  
Editor-in-Chief  
*Journal of Chemical Information and Modeling*  
American Chemical Society

Dear Prof. Merz,

Please find enclosed our Article manuscript entitled **"QuantumChem AI: A Constitutionally Governed, Rule-Driven, and LLM-Assisted Automation Platform for All-Element Atomic Cluster Quantum Chemistry"** for consideration for publication in the *Journal of Chemical Information and Modeling*.

Atomic cluster quantum chemistry across the periodic table requires tightly coupled orchestration of global structural search, permutation-invariant isomer deduplication, mixed basis/ECP assignment, open-shell spin-multiplicity scanning, fault-tolerant HPC execution, wavefunction analysis, and publication-grade visualization. Existing workflows either hardcode specific elements or expose large language model (LLM) agents to silent physical errors and numerical hallucinations.

In this work, we introduce **QuantumChem AI**, an open-source (MIT-licensed) automation platform built around an eight-article **Design Constitution (C1–C8)** enforced at runtime and in continuous integration. Key innovations of direct relevance to the JCIM readership include:

1. **Zero-Hardcoding Periodic-Table Rule Engine:** All functional, dispersion, Basis Set Exchange (`GenECP`), electron-parity, and adaptive spin-multiplicity rules reside in traceable YAML specifications, verified by Python AST static analysis to contain zero element-symbol branches across the entire source tree.
2. **Tri-Axial Inertia Kabsch Deduplication & Symmetry Enumeration:** A three-stage fingerprint, tri-axial principal-inertia Hungarian/Kabsch alignment, and fallback permutation matcher resolves arbitrary 3D rotations and atom-index permutations to $10^{-15}$ Angstrom precision in under 8 ms, paired with `PointGroupAnalyzer` dopant enumeration.
3. **Resilient Shared-HPC Orchestration:** NUMA-aware load throttling with elastic core scaling (`4` to `10–16` cores), SSH auto-reconnect with exit-poll race protection, three-section `--Link1--` (`opt` -> `stable=opt` -> `freq`), and lossless 4f SCF escalation/tail-preserving recovery.
4. **End-to-End Experimental Validation & Scientific Discovery:** Verified against 10 real Gaussian 16 golden benchmarks, real Multiwfn 3.8(dev) wavefunction analysis of `Al12Cu`, and an autonomous 9-project, 230-job (221 Gaussian 16 runs, 1,399.78 CPU core-hours, 100% convergence with 7 automated 4f repairs) production study of heavy lanthanide $\mathrm{Ln@Au_5}$ ($\mathrm{Ln} = \mathrm{Gd}$–$\mathrm{Lu}$), revealing a trivalent $8\mathrm{e}^-$ superatom HOMO–LUMO gap rigidity plateau ($2.524$–$2.812$ eV), localized $4f$ spin decoupling, and divalent $\mathrm{Yb^{2+}}$ spin delocalization.
5. **Anti-Hallucination LLM Collaboration:** A `pydantic-ai` planning/interpretation layer protected by deterministic `build_plan()` dry-run validation and unit-conversion-aware numerical grounding, achieving **50/50 (100%)** (Chinese) and **50/50 (100%)** (English) accuracy across a live 50+50 bilingual scientific instruction benchmark.

We confirm that this manuscript is original, has not been published previously, and is not under consideration elsewhere. The author declares no competing financial interests. All source code, 115+ offline tests, golden datasets, Multiwfn logs, `Ln@Au5` production summaries, and bilingual LLM evaluation suites are openly available under the MIT license at `https://github.com/QIANCHANGKING/quantumchem-ai` and archived at `10.5281/zenodo.24501860`.

Thank you for your time and consideration.

Sincerely,

**Changtian Qian**  
Department of Physics, Capital Normal University, Beijing 100048, China  
Email: `qianchangdtw@gmail.com` | ORCID: `0009-0005-2464-3814`

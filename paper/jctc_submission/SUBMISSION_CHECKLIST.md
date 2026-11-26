# ACS JCTC Manuscript Transfer & Submission Checklist

Follow these steps before completing the manuscript transfer from *Journal of Chemical Information and Modeling* (`ci-2026-04436c`, Executive Editor Prof. Thereza A. Soares, 25-Nov-2026) to *Journal of Chemical Theory and Computation* (JCTC) in ACS Paragon Plus (`https://acsparagonplus.acs.org/`):

---

## Pre-Transfer Author & Funding Verification

1. **Sole Author Verification:** Confirm author metadata and corresponding-author email in ACS Paragon Plus match:
   - `Changtian Qian` (Sole & Corresponding Author, ORCID: `0009-0005-2464-3814`, `qianchangdtw@gmail.com`, Department of Physics, Capital Normal University, Beijing 100048, China)
2. **Funding & Grant Status:** None (no external grant funding received).

---

## Phase 1: Pre-Transfer Privacy & Codebase Verification

1. Verify `git status` shows NO tracked secrets, databases, scratch files, or local configuration:
   - `config/settings.toml`, `*.pem`, `id_rsa*`, `.env`, `projects/`, `*.sqlite`, `*.fchk`, `*.cube`, and `paper/jctc_upload_ready/` remain excluded by `.gitignore`.
   - `paper/jcim_submission/` remains untouched as the archival record of `ci-2026-04436c`.
   - `LICENSE` (MIT) and `README_EN.md` are present at repository root.
2. Run the full offline codebase verification suite from repository root:
   ```powershell
   $OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
   $env:PYTHONUTF8 = '1'
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src
   uv run pytest
   ```
   Confirm zero errors across all four commands (115+ offline/E2E tests passing).

---

## Phase 2: Repository & Archival Identifiers (Active)

1. Public repository: `https://github.com/QIANCHANGKING/quantumchem-ai` (`main` branch, tag `v0.1.0`).
2. Permanent Zenodo archival DOI: `10.5281/zenodo.24501860` (concept DOI `10.5281/zenodo.24501859`).

---

## Phase 3: JCTC Upload Bundle Verification (`paper/jctc_submission/` & `paper/jctc_upload_ready/`)

Upload the verified deliverables prepared in `paper/jctc_upload_ready/` (sourced from `paper/jctc_submission/`):

- [ ] **Manuscript PDF:** `Manuscript_JCTC.pdf` (`paper/jctc_submission/manuscript.pdf`, compiled from `manuscript.tex` + `references.bib` using `achemso` `journal=jctcce,manuscript=article`, zero undefined references, zero overfull boxes).
- [ ] **LaTeX Source & Figure Bundle:** `JCTC_LaTeX_Source_Bundle.zip` (`manuscript.tex`, `references.bib`, `figures/fig1.pdf`–`figures/fig7.pdf`, `figures/TOC_graphic.pdf`).
- [ ] **Table of Contents (TOC) Graphic:** `TOC_Graphic_JCTC.tif` (600 dpi, $\le 3.25\text{ in} \times 1.75\text{ in}$, RGB, borderless).
- [ ] **Supporting Information for Publication:** `Supporting_Information_JCTC.pdf` (`paper/jctc_submission/Supporting_Information.pdf`, matching 4-author block and Sections S1–S4).
- [ ] **Transfer Cover Letter:** `Cover_Letter_JCTC.pdf` (`paper/jctc_submission/Cover_Letter.pdf`, addressed to Editor-in-Chief Prof. Laura Gagliardi, referencing ACS transfer from `ci-2026-04436c`, summarizing all JCTC revisions and 4-author signatures).
- [ ] **Suggested Reviewers:** Enter the 5 verified zero-COI experts listed in `Suggested_Reviewers_JCTC.md` (`paper/jctc_submission/Suggested_Reviewers.md`).
- [ ] **Data and Software Availability Check:** Confirm `Data and Software Availability` in `Manuscript_JCTC.pdf` lists the MIT license, Python 3.12 runtime, GitHub URL, Zenodo DOI, and third-party software acquisition URLs (Gaussian 16, Multiwfn 3.8(dev), Origin 2024b, VMD, ABCluster/GFN2-xTB).

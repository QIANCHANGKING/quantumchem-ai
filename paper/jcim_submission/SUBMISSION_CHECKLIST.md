# ACS JCIM Submission & GitHub / Zenodo Release Checklist

Follow these steps before uploading the final submission package to ACS Paragon Plus (`https://acsparagonplus.acs.org/`):

---

## Phase 1: Pre-Push Privacy & Cleanliness Audit

1. Verify `git status` shows NO tracked secrets, databases, scratch files, or local configuration:
   - `config/settings.toml`, `*.pem`, `id_rsa*`, `.env`, `projects/`, `*.sqlite`, `*.fchk`, `*.cube` remain excluded by `.gitignore`.
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

## Phase 2: Push to GitHub & Mint Permanent Zenodo Archival DOI (Completed)

1. Public repository pushed: `https://github.com/QIANCHANGKING/quantumchem-ai` (`main` branch, tag `v0.1.0`).
2. GitHub–Zenodo webhook integration enabled and release published (`https://github.com/QIANCHANGKING/quantumchem-ai/releases/tag/v0.1.0`).
3. Permanent Zenodo archival DOI minted and populated:
   - Version `v0.1.0` DOI: `10.5281/zenodo.24501860` (`https://zenodo.org/records/24501860`)
   - Concept DOI (all versions): `10.5281/zenodo.24501859`

---

## Phase 3: Author Metadata & PDF Recompilation (Completed)

All URLs, archival identifiers, and corresponding-author metadata have been populated with zero remaining placeholders across all deliverables:

- **GitHub Repository:** `https://github.com/QIANCHANGKING/quantumchem-ai`
- **Zenodo Archival DOI:** `10.5281/zenodo.24501860` (concept DOI `10.5281/zenodo.24501859`)
- **Corresponding Author Email:** `qianchangdtw@gmail.com`
- **Author ORCID:** `0009-0005-2464-3814` (`https://orcid.org/0009-0005-2464-3814`)
- **Funding Note:** Removed unused grant placeholder cleanly from `manuscript.tex` Acknowledgments.

Compiled outputs refreshed across `paper/jcim_submission/` and `paper/jcim_upload_ready/`.

---

## Phase 4: ACS Paragon Plus Submission Bundle Verification

Upload the following verified deliverables from `paper/jcim_submission/`:

- [ ] **Manuscript File (`Manuscript PDF`):** `paper/jcim_submission/manuscript.pdf` (compiled from `manuscript.tex` + `references.bib` using `achemso` `journal=jcisd8,manuscript=article`).
- [ ] **LaTeX Source & Figure Bundle (for ACS production):** `manuscript.tex`, `references.bib`, and `figures/fig1_architecture.pdf`–`figures/fig7_web_workbench.pdf` + `figures/TOC_graphic.pdf`.
- [ ] **Table of Contents (TOC) Graphic:** `paper/jcim_submission/figures/TOC_graphic.png` (600 dpi, exact `3.25 in x 1.75 in`, borderless) and `TOC_graphic.pdf`.
- [ ] **Supporting Information for Publication:** `paper/jcim_submission/Supporting_Information.pdf`.
- [ ] **Cover Letter:** `paper/jcim_submission/Cover_Letter.pdf` (strictly 1 page, addressed to Editor-in-Chief Prof. Kenneth M. Merz, Jr.).
- [ ] **Suggested Reviewers:** Enter the 5 scholars listed in `paper/jcim_submission/Suggested_Reviewers.md`.
- [ ] **Data and Software Availability Check:** Confirm `Data and Software Availability` section in `manuscript.pdf` lists exact MIT license, OS/Python 3.12 runtime, GitHub URL, Zenodo DOI, and third-party software acquisition URLs (Gaussian 16, Multiwfn 3.8(dev), Origin 2024b, VMD, ABCluster/GFN2-xTB).

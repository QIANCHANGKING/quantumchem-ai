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

## Phase 3: Replace Remaining Author Placeholders & Recompile Final PDFs

Both `https://github.com/QIANCHANGKING/quantumchem-ai` and `10.5281/zenodo.24501860` are populated. Replace only the three remaining author-specific placeholders across `paper/jcim_submission/manuscript.tex`, `paper/jcim_submission/build_jcim_docs.py`, `paper/jcim_submission/Cover_Letter.md`, and `paper/jcim_submission/Suggested_Reviewers.md`:

| Placeholder | Replace With | Locations |
| :--- | :--- | :--- |
| `<CORRESPONDING_EMAIL>` | Author institutional/contact email | `manuscript.tex`, `Cover_Letter.md`, `Suggested_Reviewers.md`, `build_jcim_docs.py` |
| `<ORCID_ID>` | `0000-000X-XXXX-XXXX` | `manuscript.tex`, `Cover_Letter.md`, `build_jcim_docs.py` |
| `<FUNDING_GRANT_NUMBER>` | Grant agency & number (or remove line if unfunded) | `manuscript.tex` (Acknowledgments) |

Then re-run compilation:
1. Re-run `tectonic manuscript.tex` inside `paper/jcim_submission/` to update `manuscript.pdf`.
2. Re-run `.venv\Scripts\python.exe paper\jcim_submission\build_jcim_docs.py` to update `Supporting_Information.pdf` and `Cover_Letter.pdf`.

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

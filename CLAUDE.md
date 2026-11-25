# CMC Cytogenetics report tool

Standalone tool (split out of `../cmc_report_automation__tool` on 2026-11-23) that fills
the CMC Vellore Department of Cytogenetics WES & Mito report. See README.md for usage.

Layout: `frontend/` (the page: index.html, css/, js/), `backend/` (Flask server +
`core/` report logic), `database/` (OMIM tables, git-ignored), `assets/` (the Word
template), `samples/` (patient test files, git-ignored).

- One UI only: the Flask web page (`frontend/`). The exe (`build.spec`, console=True)
  runs the same server and opens the browser, so there is no separate desktop UI to
  keep in sync. Bundled folders are found with `backend.core.os_utils.resource_path`.
- `backend/core/variants.py` and `backend/core/os_utils.py` are copies from the main
  tool; a fix to the Excel reading may be needed in both projects.
- The renderer (`backend/core/renderer.py`) finds template parts by their text, not
  position; keep the headings listed in README "Editing the template".
- Patient files (.docx/.pdf/.xlsx, drafts; `samples/`) contain patient data: never
  commit them (see .gitignore). The OMIM files are licensed: never commit them either.
- Sign-in (`backend/auth.py`): every page and `/api/` call needs a user. Accounts and the
  cookie key are in the data folder (`instance/` or `cyto_data/` next to the exe): never
  commit or bundle them. Tests use a temp folder via `tests/helpers.py`.
- Verify output by rendering to PDF (`backend.core.pdf.docx_to_pdf`) and looking at the
  pages, not just the docx text.

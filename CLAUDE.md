# CMC Cytogenetics report tool

Standalone tool (split out of `../cmc_report_automation__tool` on 2026-11-23) that fills
the CMC Vellore Department of Cytogenetics WES & Mito report. See README.md for usage.

- One UI only: the Flask web page (`app/web/templates/index.html`). The exe
  (`build.spec`, console=True) runs the same server and opens the browser, so there is
  no separate desktop UI to keep in sync.
- `app/core/variants.py` and `app/core/os_utils.py` are copies from the main tool; a
  fix to the Excel reading may be needed in both projects.
- The renderer (`app/core/renderer.py`) finds template parts by their text, not
  position; keep the headings listed in README "Editing the template".
- Patient files (.docx/.pdf/.xlsx, drafts) contain patient data: never commit them
  (see .gitignore).
- Verify output by rendering to PDF (`app.core.pdf.docx_to_pdf`) and looking at the
  pages, not just the docx text.

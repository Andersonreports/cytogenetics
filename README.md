# CMC Cytogenetics report tool

Makes the **NGS-WES (Whole Exome and Mitochondrial Gene Sequencing) report** of the
Department of Cytogenetics, Christian Medical College, Vellore, as `.docx` / `.pdf`,
with a live preview of the real output. Anderson does the wet lab; CMC interprets and
signs the report.

It is a small web app: one form in the browser, served from this computer
(or from one office PC to the LAN with `--lan`). The packaged `.exe` runs the same
thing for people off the office network.

## Run

```bat
pip install -r requirements.txt
run.bat              :: opens http://127.0.0.1:5200 in the browser
run.bat --lan        :: also reachable from other computers on the network
```

PDF export and the preview need **Microsoft Word** (used through COM, a hidden
private instance) or **LibreOffice**.

## Using it

The form is in three steps (tabs at the top, as in the CMC report automation tool):
**1 Patient & sample** (items 1-2 below), **2 Variants** (item 3) and **3 Result text**
(item 4). Each tab shows how far it is filled in; click a tab to move to it.

1. **Patient & sample** - the NAME / HOSP NO table as printed on the report
   (Name, Hosp No, Age, Lab No, Sex, Sample, Referred by, Date of receipt, Unit,
   Date of report). The two dates can be typed (dd/mm/yyyy) or picked with the calendar
   button in the box.
2. **Indication**.
3. **Primary finding - variants** - drop the VarSeq Excel, or *+ Add variant* to
   type one in. The Lab No is taken from the Excel's file name when it has one
   ("WES 02.2026 ....xlsx", "WES_02-26.xlsx" -> "WES 02/26"; a different Lab No already
   typed is replaced only after asking). Either the curated *listed-variants* sheet (header row with GENE and
   VARIANT columns) or the full VarSeq table export ("Complex Variants ... for
   <sample>": column-group row, column-name row, one variant per row). From the full
   export the table is filled for the MANE transcript: gene full name, HGNC, Exon n/N,
   consequence, g./c./p., zygosity, OMIM diseases each with its own inheritance, and
   the ACMG classification.
   After the Excel is read, the variants are listed on the left as "GENE c.change"
   (*Search variants* filters the list, *Select all* ticks the ones shown, the arrow hides
   the list) and the selected one's values are shown, editable, on the right.
   Tick the variants to report and click one to edit it: gene full name / HGNC
   (optional), transcript, c./p. change, genomic position, location, consequence,
   zygosity, ACMG classification, disease (`;` between several), inheritance codes,
   the gene / disease description and the variant evidence.
   Each ticked variant becomes one row of *Table detailing primary finding* and one
   block of *Description of primary finding*. With none ticked, the report has no
   primary-finding line, table or description. The headings say "findings" when more
   than one variant is in the table.
   In the variant editor, *in* puts a variant in the **Primary**, **Secondary** or
   **Incidental finding** block (VarSeq's secondary findings start as Secondary). A
   Secondary / Incidental block comes after the primary description with its own
   Summary (box under *Result text*; blank = a sentence per variant), table and footnote,
   and a description only if one of its variants has description text. With only
   Secondary / Incidental variants ticked, "Primary finding:" stays with the
   no-variant summary.
   **Type of variant** (top of the variant editor) picks how it is reported, as in the
   lab's reports:
   * *Sequence variant* (default): the table above.
   * *Copy number variant*: its own table (Variant | Zygosity | Size | Disease |
     Inheritance | ACMG/ClinGen classification) and description after the block's
     sequence variants, headed "(CNV)" (and those "(SNV)" when a block has both). A
     *Genes in the involved segment* list adds the "Table showing all genes in the
     involved segment" (Region | Gain/Loss | Size | genes) above the signature.
   * *Mitochondrial variant* (chrM rows of the Excel start as this): the
     "Mitochondrial genome analysis:" line becomes a block with its Summary (the
     *Mitochondrial genome analysis* box, blank = built from the variant), the table
     (Gene | NC_012920.1(gene):m. | DNA source | Disease | Heteroplasmy (level %) |
     classification) and the description; the ACMG mtDNA reference (McCormick 2020) is
     added to the References.
   Each variant's **Description** is one text box, printed as typed: Enter starts a new
   paragraph, **B** / *I* (or Ctrl+B / Ctrl+I) make the selected text bold / italic
   (the buttons stay in view while you scroll). It starts with text
   built from the variant's own values (Excel / OMIM; `backend/core/narrative.py`): the
   bold "Variant NM_...:c... / NP_...:p... in GENE gene" line (a box that does not start
   with such a line gets the built one in the report), the gene's function and its OMIM disease, the
   variant observed (type, position, protein change), its gnomAD frequency and ClinVar
   classification, then the bold "Based on ACMG criteria, this variant is classified as
   ..." sentence. It follows the variant until you edit it; edited text (even an emptied
   box) is printed as it is, and *Rebuild* brings the built text back.
4. **Result text** - the Summary, the Secondary / Incidental finding Summaries (shown
   when such a variant is ticked) and Mitochondrial genome analysis are filled in with
   the text built from the ticked variants, as the report prints it (e.g. "... shows
   the following pathogenic variant in the DPYD gene that is associated with autosomal
   recessive dihydropyrimidine dehydrogenase deficiency (see table and description
   below)", plus the carrier-state note for one heterozygous variant of a recessive
   condition; with no primary variant: "Whole exome and mitochondrial sequencing did
   not detect any pathogenic / likely pathogenic variants related to the described
   phenotype. A genetic cause ... has not been identified."). The Incidental finding
   Summary says the finding is unlikely to explain the phenotype (with the carrier and
   family-screening sentences for a heterozygous variant of a recessive condition); the
   Secondary finding Summary says "A pathogenic variant in the G6PD gene was identified
   (see table below) in this sample. Pathogenic mutations in this gene cause ... However,
   this variant is being reported to facilitate appropriate management ...". They follow the variants until you edit them; edited text is kept, and
   *Rebuild from variants* brings the built text back (so does emptying the box).
   Then Conclusion (bold), Recommendations (blank = section left out) and Signed by
   (printed right-aligned as in the lab's reports; blank = "Dr. ………" dotted line to sign by hand).
5. **Export DOCX / Export PDF** - saved to the browser's Downloads folder as
   `<Name>_WES_&_Mito_Report_<dd_mm_yyyy>`.

The form is kept in the browser between visits; *Save draft* / *Load draft* move a
report as a JSON file; *Clear* (top right) clears it for a new report.

Limitations, Disclaimers, Test methodology and References are fixed template text.

## Project layout

```
frontend/    the web page the user works in
backend/     Python: the Flask server and the report logic
database/    data tables the backend reads (OMIM; not in git)
assets/      the Word report template
samples/     local patient files for testing (not in git)
tests/
```

| Path | Purpose |
|---|---|
| `frontend/index.html` | the form page (layout) |
| `frontend/css/style.css` | its styles |
| `frontend/js/app.js` | its behaviour: variants list / editor, preview, export, drafts |
| `backend/main.py` | entry point (`python -m backend.main`): starts the server, opens the browser |
| `backend/server.py` | Flask routes: page, init, variants upload, preview, export; serves `frontend/` |
| `backend/core/renderer.py` | fills the Word template from a `ReportData` |
| `backend/core/narrative.py` | the built text of a variant's Description box |
| `backend/core/models.py` | `ReportData`, `PatientInfo` |
| `backend/core/variants.py` | reads the VarSeq Excel; variant wording helpers (shared code with the CMC report automation tool) |
| `backend/core/pdf.py` | DOCX -> PDF (Word / LibreOffice), PDF -> preview images |
| `backend/core/docx_utils.py` | small Word XML helpers |
| `backend/core/os_utils.py` | paths to the bundled folders (source and exe), LibreOffice lookup |
| `database/omim_*.txt` | OMIM gene / phenotype tables. Licensed, so not in git: see `database/README.md`. Without them the OMIM numbers / diseases are not suggested. |
| `assets/cmc_cytogenetics.docx` | the report template |
| `samples/` | VarSeq Excel files and finished reports used for testing. Patient data: git-ignored, never commit. |
| `tests/test_render.py` | smoke tests (`python -m unittest`) |

## Editing the template

`assets/cmc_cytogenetics.docx` can be edited in Word. The renderer finds
its parts by their text, so keep: the table whose first cell is `NAME`, the
`INDICATION:` box, the headings `Summary:`, `REFERENCES`, `Primary finding:`,
`Table detailing primary finding:`, `Description of primary finding:`,
`Recommendations`, the line starting `Mitochondrial genome analysis`, the table
whose first cell is `Gene` (header row + one sample row, used as the row format),
its footnote starting `* AR=` and the signatory line starting `Dr.`.

## Build the exe

```bat
pip install -r requirements.txt -r requirements-build.txt
build.bat            :: -> dist\CMCCytogeneticsReport.exe
```

The exe opens a console window showing the address; closing it stops the tool.

## Tests

```bat
python -m unittest discover -s tests -v
```

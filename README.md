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

1. **Patient & sample** - the NAME / HOSP NO table as printed on the report
   (Name, Hosp No, Age, Lab No, Sex, Sample, Referred by, Date of receipt, Unit,
   Date of report).
2. **Indication**.
3. **Primary finding - variants** - drop the VarSeq Excel, or *+ Add variant* to
   type one in. Either the curated *listed-variants* sheet (header row with GENE and
   VARIANT columns) or the full VarSeq table export ("Complex Variants ... for
   <sample>": column-group row, column-name row, one variant per row). From the full
   export the table is filled for the MANE transcript: gene full name, HGNC, Exon n/N,
   consequence, g./c./p., zygosity, OMIM diseases each with its own inheritance, and
   the ACMG classification.
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
4. **Result text** - Summary (blank = built from the ticked variants, or a
   no-variant sentence), Conclusion (bold), Mitochondrial genome analysis (blank =
   "No variant that warrants reporting was identified."), Recommendations (blank =
   section left out) and Signed by (blank = "Dr." left to fill).
5. **Export DOCX / Export PDF** - saved to the browser's Downloads folder as
   `<Name>_WES_&_Mito_Report_<dd_mm_yyyy>`.

The form is kept in the browser between visits; *Save draft* / *Load draft* move a
report as a JSON file; *New report* clears it.

Limitations, Disclaimers, Test methodology and References are fixed template text.

## Project layout

| Path | Purpose |
|---|---|
| `app/main.py` | entry point: starts the server, opens the browser |
| `app/web/server.py` | Flask routes: init, variants upload, preview, export |
| `app/web/templates/index.html` | the whole UI (plain HTML/CSS/JS) |
| `app/core/renderer.py` | fills the Word template from a `ReportData` |
| `app/core/models.py` | `ReportData`, `PatientInfo` |
| `app/core/variants.py` | reads the VarSeq Excel; variant wording helpers (shared code with the CMC report automation tool) |
| `app/core/pdf.py` | DOCX -> PDF (Word / LibreOffice), PDF -> preview images |
| `app/core/docx_utils.py` | small Word XML helpers |
| `app/templates/cmc_cytogenetics.docx` | the report template |
| `app/data/omim_*.txt` | OMIM gene / phenotype tables (`genemap2.txt`, `mim2gene.txt` from omim.org, renamed). Licensed, so not in git: copy them in before running or building. Without them the OMIM numbers / diseases are not suggested. |
| `tests/test_render.py` | smoke tests (`python -m unittest`) |

## Editing the template

`app/templates/cmc_cytogenetics.docx` can be edited in Word. The renderer finds
its parts by their text, so keep: the table whose first cell is `NAME`, the
`INDICATION:` box, the headings `Summary:`, `Primary finding:`,
`Table detailing primary finding:`, `Description of primary finding:`,
`Recommendations`, the line starting `Mitochondrial genome analysis`, the table
whose first cell is `Gene` (header row + one sample row, used as the row format),
its footnote starting `* AR=` and the `Dr.` signatory line.

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

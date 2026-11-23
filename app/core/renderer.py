"""Fill the CMC Department of Cytogenetics WES & Mito report (app/templates/cmc_cytogenetics.docx).

What is filled:
  * the NAME / HOSP NO label table and the INDICATION box, from the form;
  * the Summary (the form's text, else a sentence built from the ticked variants);
  * "Table detailing primary finding": one row per ticked variant, and its footnote
    naming the inheritance codes used;
  * "Description of primary finding": per variant a bold "Variant <c.> / <p.> in GENE
    gene" line, then its OMIM phenotype and evidence text, then the form's bold
    conclusion;
  * variants reported as Secondary / Incidental findings: a "Secondary finding:" and /
    or "Incidental finding:" block before the Mitochondrial line, each with its own
    Summary, table, footnote and (when there is text) Description, built from copies
    of the primary-finding parts;
  * the Mitochondrial genome analysis line, the Recommendations and the signatory.
With no primary variant ticked the table and the Description are left out, and the
"Primary finding:" line too unless a Secondary / Incidental block follows. Limitations, Disclaimers, Methodology and References stay exactly as in the
template. Elements are found by their text, so the template can be edited in Word as
long as those headings stay.
"""
from __future__ import annotations

import copy
import os
import re
from datetime import datetime

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from . import variants as vr
from .docx_utils import TemplateError, runs, set_para_tail, set_text, text
from .models import ReportData
from .os_utils import resource_path

TEMPLATE = ("app", "templates", "cmc_cytogenetics.docx")
FILE_SUFFIX = "WES_&_Mito_Report"

# Label table: the label as printed -> PatientInfo field.
LABELS = {
    "NAME": "name", "HOSP NO": "hosp_no", "AGE": "age", "LAB NO": "lab_no",
    "SEX": "sex", "SAMPLE": "sample", "REFERRED BY": "referred_by",
    "DATE OF RECEIPT": "received_date", "UNIT": "unit", "DATE OF REPORT": "report_date",
}

MITO_DEFAULT = "No variant that warrants reporting was identified."
NO_VARIANT_SUMMARY = ("Whole exome analysis in this sample did not show any pathogenic or likely "
                      "pathogenic variant that could explain the indication for testing.")

_CODES = {"AR": "autosomal recessive", "AD": "autosomal dominant",
          "XLR": "X-linked recessive", "XLD": "X-linked dominant", "XL": "X-linked",
          "YL": "Y-linked", "MT": "mitochondrial"}

_HEADINGS = ("Result:", "Primary finding:", "Secondary finding:", "Incidental finding:",
             "Whole exome sequencing:", "Summary:", "Table detailing", "Description of",
             "Recommendations", "LIMITATIONS OF THE TEST", "DISCLAIMERS",
             "TEST METHODOLOGY", "REFERENCES")

_AFTER_VERT_ALIGN = {qn(t) for t in ("w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout",
                                     "w:specVanish", "w:oMath")}


# ---------------------------------------------------------------------------
# File name
# ---------------------------------------------------------------------------

def file_name_part(value: str) -> str:
    """'Baby. Arun K' -> 'Baby_Arun_K'."""
    value = re.sub(r"\s*-\s*", "-", value.strip())
    return re.sub(r"[^A-Za-z0-9-]+", "_", value).strip("_")


def file_stem(data: ReportData) -> str:
    """<Name>_WES_&_Mito_Report_<dd_mm_yyyy>."""
    day = data.patient.report_date or datetime.now().strftime("%d/%m/%Y")
    return "_".join(filter(None, (file_name_part(data.patient.name) or "report",
                                  FILE_SUFFIX, day.replace("/", "_"))))


# ---------------------------------------------------------------------------
# Paragraph helpers
# ---------------------------------------------------------------------------

def _body_paras(doc):
    return list(doc.element.body.iterchildren(qn("w:p")))


def _para(doc, prefix: str, what: str):
    for p in _body_paras(doc):
        if text(p).strip().lower().startswith(prefix.lower()):
            return p
    raise TemplateError(f"Template is missing: {what}")


def _table(doc, first_cell: str, what: str):
    for t in doc.tables:
        if t.rows and t.rows[0].cells[0].text.strip().upper().startswith(first_cell.upper()):
            return t
    raise TemplateError(f"Template is missing: {what}")


def _remove(el) -> None:
    el.getparent().remove(el)


def _paragraphs(value: str) -> list[str]:
    """Blank lines start a new paragraph; a single line break (pasted, pre-wrapped
    text) becomes a space."""
    parts = [" ".join(p.split()) for p in re.split(r"\n\s*\n", (value or "").strip())]
    return [p for p in parts if p]


def _base_rpr(model):
    """A run format from the model paragraph (its first run, else its paragraph mark),
    without bold / italic / underline / superscript, which each part sets itself."""
    rs = runs(model)
    src = rs[0].find(qn("w:rPr")) if rs else None
    if src is None:
        ppr = model.find(qn("w:pPr"))
        src = ppr.find(qn("w:rPr")) if ppr is not None else None
    rpr = copy.deepcopy(src) if src is not None else OxmlElement("w:rPr")
    for tag in ("w:b", "w:bCs", "w:i", "w:iCs", "w:u", "w:vertAlign"):
        for el in rpr.findall(qn(tag)):
            rpr.remove(el)
    return rpr


def _run(rpr, value: str, b=False, i=False, sup=False):
    r = OxmlElement("w:r")
    rpr = copy.deepcopy(rpr)
    # CT_RPr order: rStyle, rFonts, b, bCs, i, iCs, ... vertAlign, ..., lang
    anchor = rpr.find(qn("w:rFonts"))
    for tag, on in reversed([("w:b", b), ("w:bCs", b), ("w:i", i), ("w:iCs", i)]):
        if on:
            el = OxmlElement(tag)
            if anchor is not None:
                anchor.addnext(el)
            else:
                rpr.insert(0, el)
    if sup:
        va = OxmlElement("w:vertAlign")
        va.set(qn("w:val"), "superscript")
        later = next((el for el in rpr if el.tag in _AFTER_VERT_ALIGN), None)
        if later is not None:
            later.addprevious(va)
        else:
            rpr.append(va)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = value
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    return r


def _new_para(model, parts, rpr=None):
    """A copy of `model` (its paragraph format) holding `parts`: (text, b, i, sup)."""
    p = copy.deepcopy(model)
    rpr = rpr if rpr is not None else _base_rpr(model)
    for child in list(p):
        if child.tag != qn("w:pPr"):
            p.remove(child)
    for value, b, i, sup in parts:
        if value:
            p.append(_run(rpr, value, b, i, sup))
    return p


def _with_genes(value: str, genes: list[str], bold: bool = False) -> list[tuple]:
    """`value` as parts with every gene symbol in italics, as the lab writes them."""
    genes = sorted({g for g in genes if g}, key=len, reverse=True)
    if not genes:
        return [(value, bold, False, False)]
    pattern = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(map(re.escape, genes)) + r")(?![A-Za-z0-9])")
    out, pos = [], 0
    for m in pattern.finditer(value):
        out.append((value[pos:m.start()], bold, False, False))
        out.append((m.group(1), bold, True, False))
        pos = m.end()
    out.append((value[pos:], bold, False, False))
    return [p for p in out if p[0]]


def _keep_next(p) -> None:
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        p.insert(0, ppr)
    if ppr.find(qn("w:keepNext")) is None:
        el = OxmlElement("w:keepNext")
        style = ppr.find(qn("w:pStyle"))
        if style is not None:
            style.addnext(el)
        else:
            ppr.insert(0, el)


# ---------------------------------------------------------------------------
# Variant wording
# ---------------------------------------------------------------------------

def _codes(v: dict) -> list[str]:
    return [c.strip().upper() for c in re.split(r"[,/]", v.get("inheritance", "")) if c.strip()]


def _genomic(v: dict) -> str:
    """'NC_000001.11:g.97450058C>T': the Genomic position box (or the built one)
    without its 'Chr1:' lead and bracketed transcript."""
    pos, _ = vr.genomic_position(v)
    return re.sub(r"^chr[0-9XYMT]+:\s*", "", pos, flags=re.I)


def _cdna(v: dict) -> str:
    nm, c = v.get("nm_id", "").strip(), v.get("variant", "").strip()
    return f"{nm}:{c}" if nm and c else (c or nm)


def _consequence(v: dict) -> str:
    if v.get("consequence", "").strip():
        return v["consequence"].strip()
    so = vr.sequence_ontology(v)
    return "" if so == "-" else f"{so} Variant"


def _diseases(v: dict) -> list[str]:
    """'Dihydropyrimidine dehydrogenase deficiency (AR)', one per disease typed."""
    codes = "/".join(dict.fromkeys(_codes(v)))
    names = [p.strip() for p in v.get("disease", "").split(";") if p.strip()]
    out = []
    for n in names:     # the disease's own code when its OMIM number gives one
        c = vr.disease_inheritance(v, n) or codes
        out.append(f"{n} ({c})" if c else n)
    return out or ["-"]


def summary_default(chosen: list[dict]) -> str:
    """The Summary when the form leaves it blank."""
    if not chosen:
        return NO_VARIANT_SUMMARY

    def joined(items):
        return (", ".join(items[:-1]) + " and " + items[-1]) if len(items) > 1 else "".join(items)

    genes = list(dict.fromkeys(v.get("gene", "").strip() for v in chosen if v.get("gene")))
    counts: dict[str, int] = {}
    for v in chosen:
        label = vr.classification(v).strip().lower()
        counts[label] = counts.get(label, 0) + 1
    kinds = []
    for label, n in counts.items():
        if "uncertain" in label:
            kinds.append("variants of uncertain significance" if n > 1 else "variant of uncertain significance")
        else:
            kinds.append(f"{label} variant{'s' if n > 1 else ''}")
    return (f"Whole exome analysis in this sample shows the following {joined(kinds)} in the "
            f"{joined(genes)} gene{'s' if len(genes) > 1 else ''} (see table and description below).")


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _fill_labels(doc, data: ReportData) -> None:
    table = _table(doc, "NAME", "NAME / HOSP NO table")
    for tr in table._tbl.findall(qn("w:tr")):
        tcs = tr.findall(qn("w:tc"))
        for k in range(0, len(tcs) - 2, 3):        # label | : | value, twice per row
            label = text(tcs[k]).strip().rstrip(":").strip().upper()
            attr = LABELS.get(label)
            if attr:
                set_text(tcs[k + 2].find(qn("w:p")), (getattr(data.patient, attr, "") or "").strip())


def _fill_indication(doc, data: ReportData) -> None:
    table = _table(doc, "INDICATION", "INDICATION box")
    tc = table._tbl.findall(qn("w:tr"))[0].findall(qn("w:tc"))[-1]
    paras = tc.findall(qn("w:p"))
    for p in paras[1:]:
        tc.remove(p)
    texts = _paragraphs(data.indication) or [""]
    set_text(paras[0], texts[0])
    anchor = paras[0]
    for value in texts[1:]:
        extra = copy.deepcopy(paras[0])
        set_text(extra, value)
        anchor.addnext(extra)
        anchor = extra


def _between(head, stop) -> list:
    out, el = [], head.getnext()
    while el is not None and el is not stop:
        out.append(el)
        el = el.getnext()
    return out


def _fill_summary(doc, value: str, genes: list[str]) -> None:
    head = _para(doc, "Summary:", "'Summary:' heading")
    stop = _para(doc, "Table detailing primary finding", "'Table detailing primary finding' heading")
    _fill_summary_at(head, stop, value, genes)


def _fill_summary_at(head, stop, value: str, genes: list[str]) -> None:
    old = _between(head, stop)
    model = next((p for p in old if p.tag == qn("w:p") and text(p).strip()), None)
    blank = next((p for p in old if p.tag == qn("w:p") and not text(p).strip()), None)
    if model is None:
        raise TemplateError("Template is missing the Summary paragraph")
    anchor = head
    for part in _paragraphs(value):
        p = _new_para(model, _with_genes(part, genes))
        anchor.addnext(p)
        anchor = p
    if blank is not None:
        anchor.addnext(copy.deepcopy(blank))
    for el in old:
        _remove(el)


def _cell_paras(tc, lines: list[list[tuple]]) -> None:
    """Rewrite a cell as `lines` (each a list of (text, b, i, sup) parts), keeping the
    format of its first paragraph; an empty line is an empty paragraph."""
    paras = tc.findall(qn("w:p"))
    model = paras[0]
    rpr = _base_rpr(model)
    for p in paras:
        tc.remove(p)
    for parts in lines or [[]]:
        tc.append(_new_para(model, parts, rpr))


def _plain(value: str) -> list[tuple]:
    return [(value, False, False, False)]


def _fill_table(table, chosen: list[dict]) -> None:
    """Rewrite the findings table (a w:tbl: header row + one model row) with one row
    per variant."""
    rows = table.findall(qn("w:tr"))
    proto = rows[1]
    for tr in rows[1:]:
        table.remove(tr)
    for v in chosen:
        tr = copy.deepcopy(proto)
        trpr = tr.find(qn("w:trPr"))
        if trpr is None:
            trpr = OxmlElement("w:trPr")
            tr.insert(0, trpr)
        for h in trpr.findall(qn("w:trHeight")):    # sized by its text, never split
            trpr.remove(h)
        trpr.append(OxmlElement("w:cantSplit"))
        tcs = tr.findall(qn("w:tc"))
        for tc in tcs:
            tcpr = tc.find(qn("w:tcPr"))
            if tcpr is not None:
                for m in tcpr.findall(qn("w:vMerge")):
                    tcpr.remove(m)
        gene = v.get("gene", "").strip()
        name = v.get("gene_name", "").strip()
        hgnc = v.get("hgnc", "").strip()
        protein = v.get("protein", "").strip()
        consequence = _consequence(v)
        gene_cell = [[(gene or "-", True, True, False)]]
        if name:
            gene_cell += [[], [(f"({name.strip('()')})", True, False, False)]]
        if hgnc:
            gene_cell += [[], _plain(hgnc if hgnc.upper().startswith("HGNC") else f"HGNC: {hgnc}")]
        ids = [_plain(_genomic(v)), [], [("#", False, False, True), (_cdna(v), False, False, False)]]
        if protein:
            ids += [[], [("#", False, False, True), (protein, False, False, False)]]
        cells = [
            gene_cell,
            [_plain(vr.region(v))] + ([[], _plain(consequence)] if consequence else []),
            ids,
            [_plain(vr.allele_status(v))],
            sum(([_plain(d), []] for d in _diseases(v)), [])[:-1],
            [_plain(vr.classification(v))] + ([[], _plain(f"({_criteria(v)})")] if _criteria(v) else []),
        ]
        for tc, lines in zip(tcs, cells):
            _cell_paras(tc, lines)
        table.append(tr)
    # Keep the header row (and every row but the last) on the page of the next row,
    # so a table never starts with its header alone at the foot of a page.
    for tr in table.findall(qn("w:tr"))[:-1]:
        for p in tr.iter(qn("w:p")):
            _keep_next(p)


def _criteria(v: dict) -> str:
    """ACMG attributes for the classification cell: 'PM2,PVS1 Strong' -> 'PM2, PVS1 Strong'
    (printed in brackets under the classification)."""
    raw = v.get("criteria", "").strip().strip("()[]").strip()
    return ", ".join(p.strip() for p in raw.split(",") if p.strip())


def _plural_headings(paras: list, count: int) -> None:
    """'Table detailing / Description of ... finding' -> '... findings' when the block
    has more than one variant; singular (as in the template) for one."""
    if count < 2:
        return
    for p in paras:
        for t in p.iter(qn("w:t")):
            if t.text and "finding" in t.text and "findings" not in t.text:
                t.text = t.text.replace("finding", "findings", 1)
                break


def _swap_word(p, old: str, new: str) -> None:
    """'primary' -> 'secondary' in a heading, keeping the capital ('Primary' -> 'Secondary')."""
    for t in p.iter(qn("w:t")):
        if t.text:
            t.text = t.text.replace(old, new).replace(old.capitalize(), new.capitalize())


def _fill_footnote(p, chosen: list[dict]) -> None:
    codes = list(dict.fromkeys(c for v in chosen for c in _codes(v) if c in _CODES))
    note = ", ".join(f"{c}= {_CODES[c]}" for c in codes)
    set_text(p, f"* {note}, #-pertain to MANE select transcript" if note
             else "#-pertain to MANE select transcript")


def _fill_description(head, stop, chosen: list[dict], conclusion: str, genes: list[str]) -> None:
    """The paragraphs between `head` (a 'Description of ...' heading) and `stop` become
    each variant's title line and text, then the bold conclusion."""
    old = _between(head, stop)
    filled = [p for p in old if p.tag == qn("w:p") and text(p).strip()]
    if len(filled) < 2:
        raise TemplateError("Template is missing the variant description paragraphs")
    title_model, body_model = filled[0], filled[1]
    anchor = head
    for v in chosen:
        gene = v.get("gene", "").strip()
        ident = _cdna(v) + (f" / {v['protein'].strip()}" if v.get("protein", "").strip() else "")
        title = _new_para(title_model, [("Variant ", True, False, False), (ident, True, False, False),
                                        (" in ", True, False, False), (gene, True, True, False),
                                        (" gene", True, False, False)])
        _keep_next(title)
        anchor.addnext(title)
        anchor = title
        for key in ("omim_phenotype", "evidence"):
            for part in _paragraphs(v.get(key, "")):
                p = _new_para(body_model, _with_genes(part, genes))
                anchor.addnext(p)
                anchor = p
    for part in _paragraphs(conclusion):
        p = _new_para(body_model, _with_genes(part, genes, bold=True))
        anchor.addnext(p)
        anchor = p
    for el in old:
        _remove(el)


def _drop_findings(doc, conclusion: str, keep_heading: bool = False) -> None:
    """No primary variant ticked: no table or Description, only the conclusion (if any)
    before the Mitochondrial line. The 'Primary finding:' line is dropped too, unless a
    Secondary / Incidental block follows (`keep_heading`), as the lab's reports keep it."""
    if not keep_heading:
        _remove(_para(doc, "Primary finding:", "'Primary finding:' heading"))
    start = _para(doc, "Table detailing primary finding", "'Table detailing primary finding' heading")
    stop = _para(doc, "Mitochondrial genome analysis", "'Mitochondrial genome analysis' line")
    model = copy.deepcopy(stop)
    for el in [start] + _between(start, stop):
        _remove(el)
    for part in _paragraphs(conclusion):
        stop.addprevious(_new_para(model, [(part, True, False, False)]))


# The extra finding blocks, in report order: (variant "finding" value, heading word).
EXTRA_BLOCKS = (("secondary", "secondary"), ("incidental", "incidental"))


def _finding(v: dict) -> str:
    """Which block a ticked variant is reported in: 'primary', 'secondary' or 'incidental'."""
    f = (v.get("finding") or "").strip().lower()
    return f if f in dict(EXTRA_BLOCKS) else "primary"


def block_summary_default(chosen: list[dict]) -> str:
    """Summary of a Secondary / Incidental block when the form leaves it blank: one
    sentence per variant, as the lab writes them ('A pathogenic variant was identified
    in the HBB gene in a heterozygous state')."""
    out = []
    for v in chosen:
        label = vr.classification(v).strip()
        kind = ("variant of uncertain significance" if "uncertain" in label.lower()
                else f"{label.lower()} variant" if label else "variant")
        state = vr.allele_status(v).strip().lower()
        state = f" in a {state} state" if state and state != "-" else ""
        out.append(f"A {kind} was identified in the {v.get('gene', '').strip()} gene{state}")
    return ". ".join(out) + " (see table below)." if out else ""


class _Block:
    """Copies of the template's primary-finding parts, taken before anything is filled,
    to build the Secondary / Incidental blocks with the same formatting."""

    def __init__(self, doc):
        self.heading = copy.deepcopy(_para(doc, "Primary finding:", "'Primary finding:' heading"))
        head = _para(doc, "Summary:", "'Summary:' heading")
        self.summary_head = copy.deepcopy(head)
        table_head = _para(doc, "Table detailing primary finding", "'Table detailing primary finding' heading")
        between = [p for p in _between(head, table_head) if p.tag == qn("w:p")]
        model = next((p for p in between if text(p).strip()), None)
        if model is None:
            raise TemplateError("Template is missing the Summary paragraph")
        self.summary_model = copy.deepcopy(model)
        blank = next((p for p in between if not text(p).strip()), None)
        self.blank = copy.deepcopy(blank) if blank is not None else None
        mito = _para(doc, "Mitochondrial genome analysis", "'Mitochondrial genome analysis' line")
        self.region = [copy.deepcopy(el) for el in [table_head] + _between(table_head, mito)]


def _add_block(doc, blk: _Block, word: str, chosen: list[dict], summary: str, genes: list[str]) -> None:
    """A '<Word> finding:' block (Summary, table, footnote, description) before the
    Mitochondrial line. The description part is left out when none of its variants has
    description text (the lab often gives only the table)."""
    mito = _para(doc, "Mitochondrial genome analysis", "'Mitochondrial genome analysis' line")
    heading = copy.deepcopy(blk.heading)
    _swap_word(heading, "primary", word)
    els = [copy.deepcopy(blk.blank)] if blk.blank is not None else []    # gap above the block
    els += [heading, copy.deepcopy(blk.summary_head)]
    els += [_new_para(blk.summary_model, _with_genes(part, genes)) for part in _paragraphs(summary)]
    if blk.blank is not None:
        els.append(copy.deepcopy(blk.blank))
    region = [copy.deepcopy(el) for el in blk.region]
    for el in region:
        if el.tag == qn("w:p"):
            _swap_word(el, "primary", word)
    for el in els + region:
        mito.addprevious(el)
    table_head = region[0]
    table = next(el for el in region if el.tag == qn("w:tbl"))
    foot = next((el for el in region if el.tag == qn("w:p") and text(el).strip().startswith("* AR=")), None)
    desc = next((el for el in region if el.tag == qn("w:p")
                 and text(el).strip().lower().startswith("description of")), None)
    if desc is None:
        raise TemplateError("Template is missing: 'Description of primary finding' heading")
    _fill_table(table, chosen)
    if foot is not None:
        _fill_footnote(foot, chosen)
    if any(v.get(k, "").strip() for v in chosen for k in ("omim_phenotype", "evidence")):
        _fill_description(desc, mito, chosen, "", genes)
        _plural_headings([table_head, desc], len(chosen))
    else:
        for el in [desc] + _between(desc, mito):
            _remove(el)
        _plural_headings([table_head], len(chosen))


def _fill_recommendations(doc, value: str) -> None:
    head = _para(doc, "Recommendations", "'Recommendations' heading")
    stop = _para(doc, "Dr.", "signatory line ('Dr.')")
    old = [el for el in _between(head, stop) if el.tag == qn("w:p") and text(el).strip()]
    parts = _paragraphs(value)
    if not parts:
        for el in old:
            _remove(el)
        _remove(head)
        return
    model = old[0] if old else head
    anchor = head
    for part in parts:
        p = _new_para(model, _plain(part))
        anchor.addnext(p)
        anchor = p
    for el in old:
        _remove(el)


def _fill_signatory(doc, value: str) -> None:
    lines = [ln.strip() for ln in (value or "").strip().splitlines() if ln.strip()]
    if not lines:
        return
    if not re.match(r"dr\.?\s", lines[0], re.I):
        lines[0] = f"Dr. {lines[0]}"
    set_text(_para(doc, "Dr.", "signatory line ('Dr.')"), "\n".join(lines))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def template_path() -> str:
    return resource_path(*TEMPLATE)


def render_report(data: ReportData):
    """The filled template as a python-docx Document."""
    path = template_path()
    if not os.path.exists(path):
        raise TemplateError(f"Template file not found: {path}")
    doc = Document(path)
    ticked = [v for v in data.variants if v.get("selected")]
    chosen = [v for v in ticked if _finding(v) == "primary"]
    extra = [(word, [v for v in ticked if _finding(v) == key]) for key, word in EXTRA_BLOCKS]
    extra = [(word, vs) for word, vs in extra if vs]
    genes = [v.get("gene", "").strip() for v in ticked]
    blk = _Block(doc)                   # before the primary parts are filled
    _fill_labels(doc, data)
    _fill_indication(doc, data)
    _fill_summary(doc, data.summary.strip() or summary_default(chosen), genes)
    if chosen:
        _fill_table(_table(doc, "Gene", "primary finding table")._tbl, chosen)
        _fill_footnote(_para(doc, "* AR=", "the table's footnote"), chosen)
        desc = _para(doc, "Description of primary finding", "'Description of primary finding' heading")
        _fill_description(desc, _para(doc, "Mitochondrial genome analysis", "'Mitochondrial genome analysis' line"),
                          chosen, data.conclusion, genes)
        _plural_headings([_para(doc, "Table detailing primary finding", "table heading"), desc], len(chosen))
    else:
        _drop_findings(doc, data.conclusion, keep_heading=bool(extra))
    for word, vs in extra:
        summary = getattr(data, f"{word}_summary", "").strip() or block_summary_default(vs)
        _add_block(doc, blk, word, vs, summary, genes)
    set_para_tail(_para(doc, "Mitochondrial genome analysis", "'Mitochondrial genome analysis' line"),
                  " ".join(data.mito.split()) or MITO_DEFAULT)
    _fill_recommendations(doc, data.recommendations)
    _fill_signatory(doc, data.signatory)
    for p in _body_paras(doc):
        if text(p).strip().startswith(_HEADINGS):
            _keep_next(p)
    for tbl in doc.element.body.iterchildren(qn("w:tbl")):     # heading + gap stay with the table
        prev = tbl.getprevious()
        if prev is not None and prev.tag == qn("w:p") and not text(prev).strip():
            _keep_next(prev)
    return doc


def render_docx(data: ReportData, out_path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    render_report(data).save(out_path)
    return out_path

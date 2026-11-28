"""Fill the CMC Department of Cytogenetics WES & Mito report (assets/cmc_cytogenetics.docx).

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
  * copy number variants (variant "kind" 'cnv'): their own table (Variant | Zygosity |
    Size | Disease | Inheritance | ACMG/ClinGen classification) and description after
    the sequence variants of the same block, headed '(CNV)' (and those '(SNV)' when a
    block has both); a CNV's gene list gives the 'Table showing all genes in the
    involved segment' above the signatory;
  * mitochondrial variants (kind 'mito'): the Mitochondrial genome analysis line
    becomes a block with its Summary, the mitochondrial variant table and description,
    and the ACMG mtDNA reference is added to the References;
  * each variant's bold statement ('Based on ACMG criteria ...') after its description;
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

from . import narrative
from . import variants as vr
from .docx_utils import TemplateError, runs, set_para_tail, set_text, text
from .models import ReportData
from .os_utils import resource_path

TEMPLATE = ("assets", "cmc_cytogenetics.docx")
FILE_SUFFIX = "WES_&_Mito_Report"

# Label table: the label as printed -> PatientInfo field.
LABELS = {
    "NAME": "name", "HOSP NO": "hosp_no", "AGE": "age", "LAB NO": "lab_no",
    "SEX": "sex", "SAMPLE": "sample", "REFERRED BY": "referred_by",
    "DATE OF RECEIPT": "received_date", "UNIT": "unit", "DATE OF REPORT": "report_date",
}

MITO_DEFAULT = "No variant that warrants reporting was identified."
NO_VARIANT_SUMMARY = ("Whole exome and mitochondrial sequencing did not detect any pathogenic / likely "
                      "pathogenic variants related to the described phenotype. A genetic cause for the "
                      "patient’s clinical condition has not been identified.")

_CODES = {"AR": "autosomal recessive", "AD": "autosomal dominant",
          "XLR": "X-linked recessive", "XLD": "X-linked dominant", "XL": "X-linked",
          "YL": "Y-linked", "MT": "mitochondrial"}

_HEADINGS = ("Result:", "Primary finding:", "Secondary finding:", "Incidental finding:",
             "Whole exome sequencing:", "Whole exome analysis:", "Summary:", "Table detailing",
             "Table showing", "Description of", "Recommendations", "LIMITATIONS OF THE TEST",
             "DISCLAIMERS", "TEST METHODOLOGY", "REFERENCES")

# Reference added when a mitochondrial variant is reported (as in the lab's reports).
MITO_REFERENCE = (
    "McCormick EM, Lott MT, Dulik MC, Shen L, Attimonelli M, Vitale O, Karaa A, Bai R, "
    "Pineda-Alvarez DE, Singh LN, Stanley CM, Wong S, Bhardwaj A, Merkurjev D, MaoR, Sondheimer N, "
    "Zhang S, Procaccio V, Wallace DC, Gai X, Falk MJ. Specifications of the ACMG/AMP standards and "
    "guidelines for mitochondrial DNA variant interpretation. Hum Mutat. 2020 Dec;41(12):2028-2057. "
    "doi: 10.1002/humu.24107. Epub 2020 Nov 10. PMID: 32906214; PMCID:PMC7717623.")
MITO_ACCESSION = "NC_012920.1"

# Column headings and relative widths (scaled to the template table's width) of the tables
# the template has no copy of, as the lab's reports print them.
CNV_COLUMNS = (("Variant", 2600), ("Zygosity", 1400), ("Size", 950), ("Disease", 2187),
               ("Inheritance", 1300), ("ACMG/ClinGen classification", 1850))
MITO_COLUMNS = (("Gene", 1650), ("Variant identifiers", 2350), ("DNA source", 1000),
                ("Disease (Inheritance)", 1787), ("Allele state", 1400),
                ("ACMG classification (attributes)", 2100))
SEGMENT_COLUMNS = (("Region", 2900), ("Type", 1000), ("Size", 1100), ("List of genes", 5287))
SEGMENT_HEADING = "Table showing all genes in the involved segment:"

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
    return _plain_rpr(src)


def _plain_rpr(src):
    """A copy of run format `src` without bold / italic / underline / superscript."""
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
    # U+2011 (non-breaking hyphen) becomes Word's own w:noBreakHyphen, which every
    # font shows as a hyphen; the line never breaks there.
    for n, piece in enumerate(value.split(NB_HYPHEN)):
        if n:
            r.append(OxmlElement("w:noBreakHyphen"))
        if piece:
            t = OxmlElement("w:t")
            t.text = piece
            t.set(qn("xml:space"), "preserve")
            r.append(t)
    return r


NB_HYPHEN = "‑"


def _no_break_linked(text: str) -> str:
    """'X-linked' / 'Y-linked' kept on one line."""
    return re.sub(r"\b([XY])-(linked)", rf"\1{NB_HYPHEN}\2", text, flags=re.I)


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


def kind(v: dict) -> str:
    """'snv' (a sequence variant: the default), 'cnv' (copy number variant) or 'mito'
    (mitochondrial genome variant). The form's pick, else chrM in the Excel's position."""
    k = (v.get("kind") or "").strip().lower()
    if k in ("cnv", "mito"):
        return k
    chrom = v.get("chrom_pos", "").partition(":")[0].strip().upper()
    return "mito" if chrom in ("CHRM", "CHRMT", "M", "MT") else "snv"


def _joined(items):
    return (", ".join(items[:-1]) + " and " + items[-1]) if len(items) > 1 else "".join(items)


def _kinds_text(chosen: list[dict], noun: str = "variant") -> str:
    """'pathogenic variant', 'likely pathogenic and pathogenic variants' ..."""
    counts: dict[str, int] = {}
    for v in chosen:
        label = vr.classification(v).strip().lower()
        counts[label] = counts.get(label, 0) + 1
    kinds = []
    for label, n in counts.items():
        if "uncertain" in label:
            kinds.append(f"{noun}s of uncertain significance" if n > 1 else f"{noun} of uncertain significance")
        else:
            kinds.append(f"{label} {noun}{'s' if n > 1 else ''}".strip())
    return _joined(kinds)


def _vus_only_summary(snv: list[dict]) -> str:
    """The lab's wording when the only findings are variants of uncertain significance:
    'No pathogenic or likely pathogenic variants ... However, a variant of uncertain
    significance was identified in the GENE gene ...'."""
    genes = list(dict.fromkeys(v.get("gene", "").strip() for v in snv if v.get("gene")))
    many = len(snv) > 1 or len(genes) > 1
    lead = "variants of uncertain significance were" if many else "a variant of uncertain significance was"
    text = ("No pathogenic or likely pathogenic variants related to the patient's phenotype were "
            f"evident on whole exome analysis. However, {lead} identified in the {_joined(genes)} "
            f"gene{'s' if len(genes) > 1 else ''} in this sample (see table and description below).")
    if len(genes) == 1:
        diseases = list(dict.fromkeys(d.strip() for v in snv for d in v.get("disease", "").split(";")
                                      if d.strip() and d.strip() != "-"))
        if diseases:
            codes = list(dict.fromkeys(c for v in snv for c in _codes(v) if c in _CODES))
            mode = f"{_CODES[codes[0]]} " if len(codes) == 1 and len(diseases) == 1 else ""
            text += (f" The {genes[0]} gene is associated with "
                     f"{_no_break_linked(mode)}{_joined([_disease_text(d) for d in diseases])}.")
    return text


def _class_phrase(v: dict) -> str:
    """'a pathogenic variant', 'a likely pathogenic variant', 'a variant of uncertain
    significance'."""
    label = vr.classification(v).strip().lower()
    if "uncertain" in label:
        return "a variant of uncertain significance"
    return f"a {label} variant" if label else "a variant"


def _assoc_clause(diseases: list[str], codes: list[str]) -> str:
    """', associated with autosomal recessive <disease>' for a summary sentence."""
    if not diseases:
        return ""
    mode = f"{_CODES[codes[0]]} " if len(codes) == 1 and len(diseases) == 1 else ""
    if mode and any(mode.strip() in d.lower() for d in diseases):   # name already says it
        mode = ""
    return f", associated with {_no_break_linked(mode)}{_joined([_disease_text(d) for d in diseases])}"


def _multi_snv_summary(snv: list[dict]) -> str:
    """One sentence per reported variant (WES 12 / 60 / 88 style), grouping two variants
    of the same gene as 'Two variants were identified in the GENE gene ...'. Sentences are
    joined with 'In addition,'; the clinical interpretation is left for the user to add."""
    groups: dict[str, list[dict]] = {}
    for v in snv:
        groups.setdefault(v.get("gene", "").strip(), []).append(v)
    sentences = []
    for i, (gene, vs) in enumerate(groups.items()):
        diseases = list(dict.fromkeys(d.strip() for v in vs for d in v.get("disease", "").split(";")
                                      if d.strip() and d.strip() != "-"))
        codes = list(dict.fromkeys(c for v in vs for c in _codes(v) if c in _CODES))
        assoc = _assoc_clause(diseases, codes)
        if len(vs) == 1:
            body = f"{_class_phrase(vs[0])} was identified in the {gene} gene{assoc}"
        else:
            n = {2: "Two", 3: "Three", 4: "Four"}.get(len(vs), str(len(vs)))
            body = f"{n.lower()} variants were identified in the {gene} gene{assoc}"
        sentences.append(("In addition, " + body if i else body[:1].upper() + body[1:]) + ".")
    return (" ".join(sentences)
            + " Further details about these variants are provided in the table and descriptions below.")


def summary_default(chosen: list[dict]) -> str:
    """The Summary when the form leaves it blank."""
    if not chosen:
        return NO_VARIANT_SUMMARY
    snv = [v for v in chosen if kind(v) != "cnv"]
    cnv = [v for v in chosen if kind(v) == "cnv"]
    if snv and not cnv:
        if len(snv) > 1:                        # 2+ variants: one sentence each
            return _multi_snv_summary(snv)
        if "uncertain" in vr.classification(snv[0]).strip().lower():
            return _vus_only_summary(snv)
    out = []
    if snv:
        genes = list(dict.fromkeys(v.get("gene", "").strip() for v in snv if v.get("gene")))
        out.append(f"Whole exome analysis in this sample shows the following {_kinds_text(snv)} in the "
                   f"{_joined(genes)} gene{'s' if len(genes) > 1 else ''}"
                   + (_association(snv) if len(genes) == 1 else ""))
    if cnv:
        genes = list(dict.fromkeys(v.get("gene", "").strip() for v in cnv if v.get("gene")))
        over = f" overlapping the {_joined(genes)} gene{'s' if len(genes) > 1 else ''}" if genes else ""
        lead = "Furthermore, s" if snv else "S"
        out.append(f"{lead}equencing data was indicative of the following "
                   f"{_kinds_text(cnv, 'copy number variant')} (CNV){over}")
    text = ". ".join(out) + " (see table and description below)."
    return text + _carrier_note(snv if not cnv else [])


def _disease_text(name: str) -> str:
    """'Dihydropyrimidine dehydrogenase deficiency' -> 'dihydropyrimidine dehydrogenase
    deficiency' (mid-sentence), leaving acronyms ('CHD2-related ...') as they are."""
    name = name.strip()
    return name if name[:2].isupper() else name[:1].lower() + name[1:]


def _association(snv: list[dict]) -> str:
    """' that is associated with autosomal recessive dihydropyrimidine dehydrogenase
    deficiency', from the variants' Disease and Inheritance boxes (one gene)."""
    diseases = list(dict.fromkeys(d.strip() for v in snv for d in v.get("disease", "").split(";")
                                  if d.strip() and d.strip() != "-"))
    if not diseases:
        return ""
    codes = list(dict.fromkeys(c for v in snv for c in _codes(v) if c in _CODES))
    mode = f"{_CODES[codes[0]]} " if len(codes) == 1 and len(diseases) == 1 else ""
    return f" that is associated with {_no_break_linked(mode)}{_joined([_disease_text(d) for d in diseases])}"


def _carrier_note(snv: list[dict]) -> str:
    """One heterozygous (likely) pathogenic variant for a recessive-only condition: the
    lab's carrier-state sentences."""
    if len(snv) != 1:
        return ""
    v = snv[0]
    label = vr.classification(v).strip().lower()
    if _codes(v) != ["AR"] or vr.allele_status(v).lower() != "heterozygous" or \
            label not in ("pathogenic", "likely pathogenic"):
        return ""
    return (" Note that causation of disease with respect to this condition requires bi-allelic disease "
            f"causing variants. The presence of only one {label} variant as seen in this patient "
            "represents a carrier state.")


def mito_summary_default(chosen: list[dict]) -> str:
    """Summary of the Mitochondrial genome analysis block when the form leaves it blank."""
    out = []
    for v in chosen:
        level = v.get("heteroplasmy", "").strip().rstrip("%").strip()
        at = f" at a heteroplasmy level of {level}%" if level else ""
        label = _kinds_text([v])
        out.append(f"A{'n' if label[:1] in 'aeiou' else ''} {label} was identified in the "
                   f"mitochondrial gene {v.get('gene', '').strip()}{at}")
    return ". ".join(out) + " (see table and description below)."


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
        p = _new_para(model, _rich(part, genes))
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
        protein = v.get("protein", "").strip()
        consequence = _consequence(v)
        gene_cell = _gene_cell(v)
        ids = [_plain(_genomic(v)), [], [("#", False, False, True), (_cdna(v), False, False, False)]]
        if protein:
            ids += [[], [("#", False, False, True), (protein, False, False, False)]]
        cells = [
            gene_cell,
            [_plain(vr.region(v))] + ([[], _plain(consequence)] if consequence else []),
            ids,
            [_plain(vr.allele_status(v))],
            sum(([_plain(_no_break_linked(d)), []] for d in _diseases(v)), [])[:-1],
            _class_lines(v),
        ]
        for tc, lines in zip(tcs, cells):
            _cell_paras(tc, lines)
        table.append(tr)
    # Keep the header row on the page of the first variant row, so a table never starts
    # with its header alone at the foot of a page. (Only the header: keeping every row
    # together would push a tall table whole onto the next page.)
    for p in table.findall(qn("w:tr"))[0].iter(qn("w:p")):
        _keep_next(p)


def _criteria(v: dict) -> str:
    """ACMG attributes for the classification cell: 'PM2,PVS1 Strong' -> 'PM2, PVS1 Strong'
    (printed in brackets under the classification)."""
    raw = v.get("criteria", "").strip().strip("()[]").strip()
    return ", ".join(p.strip() for p in raw.split(",") if p.strip())


def _set_width(tc, width: int) -> None:
    tcpr = tc.find(qn("w:tcPr"))
    if tcpr is None:
        tcpr = OxmlElement("w:tcPr")
        tc.insert(0, tcpr)
    for tag in ("w:vMerge", "w:gridSpan", "w:hMerge"):
        for el in tcpr.findall(qn(tag)):
            tcpr.remove(el)
    w = tcpr.find(qn("w:tcW"))
    if w is None:
        w = OxmlElement("w:tcW")
        tcpr.insert(0, w)
    w.set(qn("w:w"), str(width))
    w.set(qn("w:type"), "dxa")


def _make_table(proto, columns, rows: list[list[list[list[tuple]]]]):
    """A new table in the format of `proto` (the findings table: header row + body row)
    with `columns` ((heading, width), ...) and one row per item of `rows` (each a list of
    cells, each a list of lines of (text, b, i, sup) parts)."""
    tbl = copy.deepcopy(proto)
    # Column widths are given for a 10287-wide table: scaled to the template table's own
    # width (the text width), so every table lines up with the text margins.
    tblw = tbl.find(qn("w:tblPr") + "/" + qn("w:tblW"))
    total = int(tblw.get(qn("w:w"))) if tblw is not None and (tblw.get(qn("w:w")) or "").isdigit() else 0
    given = sum(w for _, w in columns)
    if total and given != total:
        widths = [w * total // given for _, w in columns]
        widths[-1] += total - sum(widths)
        columns = tuple((h, w) for (h, _), w in zip(columns, widths))
    grid = tbl.find(qn("w:tblGrid"))
    for col in list(grid):
        grid.remove(col)
    for _, width in columns:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    trs = tbl.findall(qn("w:tr"))
    for tr in trs:
        tbl.remove(tr)

    def row(model_tr, cells):
        tr = copy.deepcopy(model_tr)
        model_tc = tr.findall(qn("w:tc"))[0]
        for tc in tr.findall(qn("w:tc")):
            tr.remove(tc)
        for (_, width), lines in zip(columns, cells):
            tc = copy.deepcopy(model_tc)
            _set_width(tc, width)
            _cell_paras(tc, lines)
            tr.append(tc)
        return tr

    head = row(trs[0], [[[(h, True, False, False)]] for h, _ in columns])
    tbl.append(head)
    for p in head.iter(qn("w:p")):
        _keep_next(p)
    for cells in rows:
        tr = row(trs[1], cells)
        trpr = tr.find(qn("w:trPr"))
        if trpr is None:
            trpr = OxmlElement("w:trPr")
            tr.insert(0, trpr)
        for h in trpr.findall(qn("w:trHeight")):
            trpr.remove(h)
        if trpr.find(qn("w:cantSplit")) is None:
            trpr.append(OxmlElement("w:cantSplit"))
        tbl.append(tr)
    return tbl


def _inheritance_lines(v: dict) -> list[list[tuple]]:
    """Inheritance written out ('XLR' -> 'X-linked recessive'), one pattern per line."""
    out = []
    for c in re.split(r"[,/;]", v.get("inheritance", "")):
        c = c.strip()
        if c:
            full = _CODES.get(c.upper(), c)
            out.append(_plain(_no_break_linked(full[:1].upper() + full[1:])))
    return out or [_plain("-")]


def _class_lines(v: dict, brackets: str = "()") -> list[list[tuple]]:
    crit = _criteria(v)
    return [_plain(vr.classification(v) or "-")] + (
        [[], _plain(f"{brackets[0]}{crit}{brackets[1]}")] if crit else [])


def _gene_cell(v: dict) -> list[list[tuple]]:
    gene, name, hgnc = (v.get(k, "").strip() for k in ("gene", "gene_name", "hgnc"))
    cell = [[(gene or "-", True, True, False)]]
    if name:
        cell += [[], [(f"({name.strip('()')})", True, False, False)]]
    if hgnc:
        cell += [[], _plain(hgnc if hgnc.upper().startswith("HGNC") else f"HGNC: {hgnc}")]
    return cell


# ---------------------------------------------------------------------------
# Copy number variants: the table shows the genomic HGVS
# 'NC_000023.11:g.(?_31874949)_(31968677_?)del', built from Chromosome / Start / End and
# Loss / Gain unless typed in the HGVS box. A c. value is never shown for a CNV.
def _cnv_chrom(v: dict) -> str:
    c = str(v.get("cnv_chrom", "")).strip() or v.get("chrom_pos", "").partition(":")[0].strip()
    c = re.sub(r"^chr", "", c, flags=re.I).upper()
    return {"23": "X", "24": "Y"}.get(c, c)


def _cnv_int(v: dict, key: str) -> int | None:
    t = re.sub(r"[,\s]", "", str(v.get(key, "")))
    return int(t) if t.isdigit() else None


def cnv_change(v: dict) -> str:
    """'Loss', 'Gain' or '' (from the Loss / Gain box, else del / dup in the HGVS)."""
    t = v.get("cnv_type", "").strip().lower()
    if t.startswith(("loss", "del")):
        return "Loss"
    if t.startswith(("gain", "dup")):
        return "Gain"
    h = (v.get("cnv_hgvs", "") or "").strip()
    return "Loss" if re.search(r"del", h) else "Gain" if re.search(r"dup|\[\d\]", h) else ""


def cnv_hgvs(v: dict) -> str:
    own = (v.get("cnv_hgvs", "") or "").strip()
    if own:
        return own
    old = v.get("variant", "").strip()          # drafts from before: HGVS typed in 'variant'
    if re.match(r"(NC_|chr|g\.)", old, re.I):
        return old
    nc = vr.NC_GRCH38.get(_cnv_chrom(v), "")
    start, end, change = _cnv_int(v, "cnv_start"), _cnv_int(v, "cnv_end"), cnv_change(v)
    if not (nc and start and end and change):
        return ""
    return f"{nc}:g.(?_{start})_({end}_?){'del' if change == 'Loss' else 'dup'}"


def cnv_size(v: dict) -> str:
    """The Size box, else End - Start + 1 in kb / Mb ('93.73 kb')."""
    own = v.get("size", "").strip()
    if own:
        return own
    start, end = _cnv_int(v, "cnv_start"), _cnv_int(v, "cnv_end")
    if not (start and end and end >= start):
        return ""
    n = end - start + 1
    return f"{n / 1e6:.2f} Mb" if n >= 1e6 else f"{n / 1e3:.2f} kb" if n >= 1000 else f"{n} bp"


def _cnv_rows(chosen: list[dict]) -> list:
    rows = []
    for v in chosen:
        diseases = [d.strip() for d in v.get("disease", "").split(";") if d.strip()] or ["-"]
        rows.append([
            [_plain(cnv_hgvs(v) or "-")],
            [_plain(vr.allele_status(v))],
            [_plain(cnv_size(v) or "-")],
            sum(([_plain(_no_break_linked(d)), []] for d in diseases), [])[:-1],
            _inheritance_lines(v),
            _class_lines(v),
        ])
    return rows


def _mito_variant(v: dict) -> str:
    """'m.4296G>A' (an 'm.' added to a bare '4296G>A')."""
    c = v.get("variant", "").strip()
    return c if not c or re.match(r"[mgc]\.", c) else f"m.{c}"


def _mito_ids(v: dict, with_gene: bool) -> str:
    """'NC_012920.1(MT-TI):m.4296G>A' (table) / 'NC_012920.1:m.4296G>A' (title)."""
    acc = v.get("nm_id", "").strip() or MITO_ACCESSION
    gene = v.get("gene", "").strip()
    return f"{acc}({gene}):{_mito_variant(v)}" if with_gene and gene else f"{acc}:{_mito_variant(v)}"


def _mito_rows(chosen: list[dict]) -> list:
    rows = []
    for v in chosen:
        level = v.get("heteroplasmy", "").strip().rstrip("%").strip()
        state = v.get("zygosity", "").strip() or ("Heteroplasmy" if level else "-")
        state_lines = [_plain(state)] + ([_plain(f"({level}%)")] if level else [])
        rows.append([
            _gene_cell(v),
            [_plain(_mito_ids(v, True))],
            [_plain(v.get("dna_source", "").strip() or "Blood")],
            sum(([_plain(_no_break_linked(d)), []] for d in _diseases(v)), [])[:-1],
            state_lines,
            _class_lines(v, "[]"),
        ])
    return rows


def _segment_rows(chosen: list[dict]) -> list:
    rows = []
    for v in chosen:
        hgvs = cnv_hgvs(v)
        typ = cnv_change(dict(v, cnv_hgvs=hgvs)) or "-"
        genes = ", ".join(g.strip() for g in re.split(r"[,;\n]+", v.get("segment_genes", "")) if g.strip())
        rows.append([[_plain(hgvs or "-")], [_plain(typ)], [_plain(cnv_size(v) or "-")],
                     [_plain(genes)]])
    return rows


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


def _description(v: dict) -> str:
    """The text under a variant's bold title line: the form's Description box, one
    paragraph per blank-line-separated block, **bold** where the user made it bold.
    Variants saved before the box was one (Description + Variant evidence + bold
    Classification statement) are joined the same way. The OMIM sentence older versions
    pre-filled ('... is caused by mutation in the X gene (OMIM*...)') is left out
    while unedited."""
    if "description" in v:
        return (v.get("description") or "").strip()
    phen = v.get("omim_phenotype", "").strip()
    if phen and phen == v.get("omim_phenotype_prefix", "").strip():
        phen = ""
    statement = v.get("statement", "").strip()
    return "\n\n".join(t for t in (phen, v.get("evidence", "").strip(),
                                   "\n\n".join(f"**{s}**" for s in _paragraphs(statement))) if t)


def _has_text(v: dict) -> bool:
    return bool(_description(v))


def _is_title_line(part: str) -> bool:
    """'**Variant NM_...:c... in GENE gene**': a wholly bold paragraph starting 'Variant'."""
    part = re.sub(r"</?i>", "", part.strip())
    return part.startswith("**Variant") and part.endswith("**") and part.count("**") == 2


def _rich(part: str, genes: list[str]) -> list[tuple]:
    """A paragraph with **bold** and <i>italic</i> spans as runs (gene symbols in
    italics as usual)."""
    out, bold, ital = [], False, False
    for tok in re.split(r"(\*\*|</?i>)", part):
        if tok == "**":
            bold = not bold
        elif tok == "<i>":
            ital = True
        elif tok == "</i>":
            ital = False
        elif tok:
            parts = _with_genes(tok, genes, bold=bold)
            out += [(t, b, True, s) for t, b, _, s in parts] if ital else parts
    return out


def _title(v: dict, many: bool):
    """The bold line over a variant's description: 'Variant NM_..:c.. / NP_..:p.. in GENE
    gene' ('Variant NC_012920.1:m.4296G>A in MT-TI gene' for a mitochondrial variant).
    A copy number variant gets 'Variant <HGVS>' only when its table has more than one;
    the lab's reports describe a single CNV without a title line."""
    gene = v.get("gene", "").strip()
    k = kind(v)
    if k == "cnv":
        if not many:
            return None
        return [("Variant ", True, False, False), (cnv_hgvs(v) or "-", True, False, False)]
    if k == "mito":
        ident = _mito_ids(v, False)
    else:
        ident = _cdna(v) + (f" / {v['protein'].strip()}" if v.get("protein", "").strip() else "")
    parts = [("Variant ", True, False, False), (ident, True, False, False)]
    if gene:
        parts += [(" in ", True, False, False), (gene, True, True, False), (" gene", True, False, False)]
    return parts


def _fill_description(head, stop, chosen: list[dict], conclusion: str, genes: list[str]) -> None:
    """The paragraphs between `head` (a 'Description of ...' heading) and `stop` become
    each variant's title line, text and bold classification statement, then the
    conclusion (bold where typed bold)."""
    old = _between(head, stop)
    filled = [p for p in old if p.tag == qn("w:p") and text(p).strip()]
    if len(filled) < 2:
        raise TemplateError("Template is missing the variant description paragraphs")
    title_model, body_model = filled[0], filled[1]
    anchor = head
    for v in chosen:
        paras = _paragraphs(_description(v))
        # The Description box starts with the bold 'Variant ... gene' line (the form
        # builds it there, editable); a box without one gets the built line.
        own_title = bool(paras) and _is_title_line(paras[0])
        parts = None if own_title else _title(v, len(chosen) > 1)
        if parts:
            title = _new_para(title_model, parts)
            _keep_next(title)
            anchor.addnext(title)
            anchor = title
        for k, part in enumerate(paras):
            is_title = own_title and k == 0
            p = _new_para(title_model if is_title else body_model, _rich(part, genes))
            if is_title:
                _keep_next(p)
            anchor.addnext(p)
            anchor = p
    for part in _paragraphs(conclusion):
        p = _new_para(body_model, _rich(part, genes))
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
        stop.addprevious(_new_para(model, _rich(part, [])))


# The extra finding blocks, in report order: (variant "finding" value, heading word).
EXTRA_BLOCKS = (("secondary", "secondary"), ("incidental", "incidental"))


def _finding(v: dict) -> str:
    """Which block a ticked variant is reported in: 'primary', 'secondary' or 'incidental'."""
    f = (v.get("finding") or "").strip().lower()
    return f if f in dict(EXTRA_BLOCKS) else "primary"


def block_summary_default(chosen: list[dict], block: str = "incidental") -> str:
    """Summary of a Secondary / Incidental block when the form leaves it blank, as the
    lab writes it: per variant, what was found and the disease it is associated with;
    for an incidental finding, that it is unlikely to explain the phenotype, and for one
    heterozygous (likely) pathogenic variant of a recessive condition, the carrier-state
    and family-screening sentences. One paragraph per variant."""
    if block == "secondary":
        return _secondary_summary(chosen)
    paras = []
    for v in chosen:
        label = vr.classification(v).strip()
        what = ("variant of uncertain significance" if "uncertain" in label.lower()
                else f"{label.lower()} variant" if label else "variant")
        state = vr.allele_status(v).strip().lower()
        state_text = f" in a {state} state" if state and state != "-" else ""
        gene = v.get("gene", "").strip()
        article = "An" if what[:1] in "aeiou" else "A"
        if kind(v) == "cnv":
            what = what.replace("variant", "copy number variant")
            where = f" overlapping the {gene} gene" if gene else ""
            text = f"{article} {what} was identified{where}{state_text}."
        else:
            text = f"{article} {what} was identified in the {gene} gene{state_text}."
        diseases = [d.strip() for d in v.get("disease", "").split(";") if d.strip() and d.strip() != "-"]
        codes = [c for c in _codes(v) if c in _CODES]
        if diseases:
            mode = ""
            if len(codes) == 1:
                words = _CODES[codes[0]]
                mode = f", {'a' if words.startswith('Y') else 'an'} {_no_break_linked(words)} condition"
            text += f" This variant is associated with {_joined(diseases)}{mode}."
        if block == "incidental":
            text += " This finding is unlikely to contribute to the patient’s clinical phenotype."
            if (codes == ["AR"] and state == "heterozygous"
                    and label.lower() in ("pathogenic", "likely pathogenic") and diseases):
                d = diseases[0]
                text += (" As the variant is present in the heterozygous state, the patient is considered a "
                         f"carrier of {_disease_text(d)} and is not, in usual circumstances, expected to "
                         f"manifest clinical features of {_disease_text(d)}. This variant is being reported "
                         "to facilitate appropriate carrier screening for family members and genetic "
                         "counselling.")
        paras.append(text)
    return "\n\n".join(paras)


def _secondary_summary(chosen: list[dict]) -> str:
    """Secondary finding Summary, as the lab writes it ('A pathogenic variant in the G6PD
    gene was identified (see table below) in this sample. Pathogenic mutations in this
    gene cause ... The contribution of this variant to the indication for testing ... is
    uncertain. However, ...'), one paragraph per variant, then the closing line."""
    paras = []
    for v in chosen:
        label = vr.classification(v).strip()
        what = ("variant of uncertain significance" if "uncertain" in label.lower()
                else f"{label.lower()} variant" if label else "variant")
        gene = v.get("gene", "").strip()
        if kind(v) == "cnv":
            what = what.replace("variant", "copy number variant")
            where = f" overlapping the {gene} gene" if gene else ""
        else:
            where = f" in the {gene} gene" if gene else ""
        article = "An" if what[:1] in "aeiou" else "A"
        text = f"{article} {what}{where} was identified (see table below) in this sample."
        diseases = [_disease_text(d) for d in v.get("disease", "").split(";") if d.strip() and d.strip() != "-"]
        if diseases:
            text += f" Pathogenic mutations in this gene cause {_joined(diseases)}."
        text += (" The contribution of this variant to the indication for testing in this patient is "
                 "uncertain. However, this variant is being reported to facilitate appropriate "
                 "management of the related condition.")
        paras.append(text)
    if paras:
        paras.append("Further details are provided in the table and description below.")
    return "\n\n".join(paras)


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


def _heading_suffix(p, suffix: str) -> None:
    """'Table detailing primary finding:' -> 'Table detailing primary finding (CNV):'."""
    for t in p.iter(qn("w:t")):
        if t.text and re.search(r"findings?", t.text):
            t.text = re.sub(r"(findings?)", rf"\1 {suffix}", t.text, count=1)
            return


def _add_part(before, blk: _Block, chosen: list[dict], k: str, genes: list[str],
              swap=("primary", "primary"), conclusion: str = "", suffix: str = "",
              always_describe: bool = False) -> None:
    """One table + description part (copies of the template's primary-finding table
    heading, table, footnote and description) before `before`: the template's table
    for sequence variants (k 'snv'), else a CNV or mitochondrial table in its format.
    The description is left out when none of the variants has text (the lab often
    gives only the table), unless `always_describe` or there is a conclusion."""
    region = [copy.deepcopy(el) for el in blk.region]
    for el in region:
        if el.tag == qn("w:p"):
            _swap_word(el, *swap)
        before.addprevious(el)
    table_head = region[0]
    table = next(el for el in region if el.tag == qn("w:tbl"))
    foot = next((el for el in region if el.tag == qn("w:p") and text(el).strip().startswith("* AR=")), None)
    desc = next((el for el in region if el.tag == qn("w:p")
                 and text(el).strip().lower().startswith("description of")), None)
    if desc is None:
        raise TemplateError("Template is missing: 'Description of primary finding' heading")
    if k == "snv":
        _fill_table(table, chosen)
        if foot is not None:
            _fill_footnote(foot, chosen)
    else:
        cols, rows = (CNV_COLUMNS, _cnv_rows(chosen)) if k == "cnv" else (MITO_COLUMNS, _mito_rows(chosen))
        table.addprevious(_make_table(table, cols, rows))
        _remove(table)
        if foot is not None:            # the CNV / mito tables spell the inheritance out
            _remove(foot)
    heads = [table_head]
    if always_describe or conclusion.strip() or any(_has_text(v) for v in chosen):
        _fill_description(desc, before, chosen, conclusion, genes)
        heads.append(desc)
    else:
        for el in [desc] + _between(desc, before):
            _remove(el)
    if k == "mito":
        if len(chosen) > 1:
            for h in heads:
                for t in h.iter(qn("w:t")):
                    if t.text and "variant" in t.text and "variants" not in t.text:
                        t.text = t.text.replace("variant", "variants", 1)
    else:
        _plural_headings(heads, len(chosen))
    if suffix:
        for h in heads:
            _heading_suffix(h, suffix)


def _add_findings(before, blk: _Block, chosen: list[dict], genes: list[str], word: str = "primary",
                  conclusion: str = "", always_describe: bool = False) -> None:
    """The sequence-variant part then the CNV part of a findings block; with both,
    their headings say '(SNV)' / '(CNV)'."""
    snv = [v for v in chosen if kind(v) != "cnv"]
    cnv = [v for v in chosen if kind(v) == "cnv"]
    if snv:
        _add_part(before, blk, snv, "snv", genes, ("primary", word), "" if cnv else conclusion,
                  "(SNV)" if cnv else "", always_describe)
    if cnv:
        _add_part(before, blk, cnv, "cnv", genes, ("primary", word), conclusion, "(CNV)", always_describe)


def _add_block(doc, blk: _Block, word: str, chosen: list[dict], summary: str, genes: list[str]) -> None:
    """A '<Word> finding:' block (Summary, then its sequence-variant and CNV tables and
    descriptions) before the Mitochondrial line."""
    mito = _para(doc, "Mitochondrial genome analysis", "'Mitochondrial genome analysis' line")
    heading = copy.deepcopy(blk.heading)
    _swap_word(heading, "primary", word)
    els = [copy.deepcopy(blk.blank)] if blk.blank is not None else []    # gap above the block
    els += [heading, copy.deepcopy(blk.summary_head)]
    els += [_new_para(blk.summary_model, _rich(part, genes)) for part in _paragraphs(summary)]
    if blk.blank is not None:
        els.append(copy.deepcopy(blk.blank))
    for el in els:
        mito.addprevious(el)
    _add_findings(mito, blk, chosen, genes, word)


def _add_mito(doc, blk: _Block, chosen: list[dict], summary: str, genes: list[str]) -> None:
    """Mitochondrial variants reported: the 'Mitochondrial genome analysis:' line becomes
    the heading of a block with its Summary, the mitochondrial variant table and the
    description, as in the lab's reports; the ACMG mtDNA reference is added."""
    m = _para(doc, "Mitochondrial genome analysis", "'Mitochondrial genome analysis' line")
    set_para_tail(m, "")
    stop = m.getnext()
    els = [copy.deepcopy(blk.summary_head)]
    els += [_new_para(blk.summary_model, _rich(part, genes)) for part in _paragraphs(summary)]
    if blk.blank is not None:
        els.append(copy.deepcopy(blk.blank))
    for el in els:
        stop.addprevious(el)
    _add_part(stop, blk, chosen, "mito", genes, ("primary finding", "mitochondrial variant"),
              always_describe=True)
    if blk.blank is not None:           # gap before Recommendations
        stop.addprevious(copy.deepcopy(blk.blank))
    head = _para(doc, "REFERENCES", "'REFERENCES' heading")
    refs = [el for el in _between(head, None) if el.tag == qn("w:p") and text(el).strip()]
    if refs and not any("mitochondrial DNA variant interpretation" in text(r) for r in refs):
        new = copy.deepcopy(refs[-1])
        set_text(new, MITO_REFERENCE)
        refs[-1].addnext(new)


def _add_segment_tables(doc, blk: _Block, cnvs: list[dict]) -> None:
    """'Table showing all genes in the involved segment' (Region | Type | Size | List of
    genes) for the CNVs that have a gene list, above the signatory as the lab prints it."""
    items = [v for v in cnvs if v.get("segment_genes", "").strip()]
    if not items:
        return
    dr = _para(doc, "Dr.", "signatory line ('Dr.')")
    head = copy.deepcopy(blk.region[0])
    set_text(head, SEGMENT_HEADING)
    proto = next(el for el in blk.region if el.tag == qn("w:tbl"))
    gap = [copy.deepcopy(blk.blank)] if blk.blank is not None else []
    els = [head] + gap + [_make_table(proto, SEGMENT_COLUMNS, _segment_rows(items))] + copy.deepcopy(gap)
    for el in els:
        dr.addprevious(el)


def _set_tail_rich(p, value: str) -> None:
    """set_para_tail with **bold** / <i>italic</i> spans in `value` kept as such."""
    set_para_tail(p, "")
    rs = runs(p)
    if len(rs) < 2 or text(rs[-1]):     # no plain tail run after the bold lead-in
        set_para_tail(p, re.sub(r"\*\*|</?i>", "", value))
        return
    tail = rs[-1]
    rpr = _plain_rpr(tail.find(qn("w:rPr")))
    anchor = tail
    for t, b, i, sup in _rich(value, []):
        r = _run(rpr, t, b, i, sup)
        anchor.addnext(r)
        anchor = r
    tail.getparent().remove(tail)


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
        p = _new_para(model, _rich(part, []))
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

def recommendations_default(chosen: list[dict]) -> str:
    """Suggested Recommendations from the ticked variants: the standard lines plus the
    finding-type lines the lab's reports use (VUS -> segregation/re-categorization,
    compound het -> phasing, mtDNA -> maternal testing, X-linked -> maternal screening).
    The disease-specific management advice is left for the user to add. The form does NOT
    auto-fill this; a button inserts it on request."""
    if not chosen:
        return ""
    lines = ["Clinical correlation is advised."]
    by_gene: dict[str, list[dict]] = {}
    for v in chosen:
        by_gene.setdefault(v.get("gene", "").strip(), []).append(v)
    for gene, vs in by_gene.items():
        if not gene:
            continue
        codes = {c for v in vs for c in _codes(v) if c in _CODES}
        snv = [v for v in vs if kind(v) not in ("cnv", "mito")]
        if len(snv) >= 2:
            lines.append(f"Determination of phasing through parental testing is advised to confirm "
                         f"whether the {gene} variants are on different alleles (in trans).")
        for v in vs:
            if kind(v) == "mito":
                ident = v.get("variant", "").strip() or "variant"
                lines.append(f"Maternal testing for the {ident} variant is recommended to assess its "
                             f"presence and heteroplasmy level.")
        if any("uncertain" in vr.classification(v).strip().lower() for v in snv):
            lines.append(f"Segregation analysis / parental testing for the {gene} variant may help to "
                         f"clarify its clinical significance and assist in re-categorization.")
        elif codes & {"XL", "XLR", "XLD"} and snv:
            lines.append(f"Maternal carrier screening for the {gene} variant is recommended to "
                         f"determine the recurrence risk.")
    lines.append("Genetic counselling is advised.")
    return "\n\n".join(dict.fromkeys(lines))    # de-duplicate, keep order (one per paragraph)


def default_texts(data: ReportData) -> dict:
    """The texts the report prints when the form leaves a box blank, from the ticked
    variants: the form shows them in its boxes, ready to edit."""
    ticked = [v for v in data.variants if v.get("selected")]
    mito = [v for v in ticked if kind(v) == "mito"]
    nuclear = [v for v in ticked if kind(v) != "mito"]
    out = {"summary": summary_default([v for v in nuclear if _finding(v) == "primary"]),
           "mito": mito_summary_default(mito) if mito else MITO_DEFAULT,
           "recommendations": recommendations_default(ticked)}
    for key, word in EXTRA_BLOCKS:
        out[f"{word}_summary"] = block_summary_default([v for v in nuclear if _finding(v) == key], key)
    # Per variant (same order): Description, Variant evidence, Classification statement.
    out["variants"] = [narrative.texts(v) for v in data.variants]
    return out


def template_path() -> str:
    return resource_path(*TEMPLATE)


def render_report(data: ReportData):
    """The filled template as a python-docx Document."""
    path = template_path()
    if not os.path.exists(path):
        raise TemplateError(f"Template file not found: {path}")
    doc = Document(path)
    ticked = [v for v in data.variants if v.get("selected")]
    mito = [v for v in ticked if kind(v) == "mito"]
    nuclear = [v for v in ticked if kind(v) != "mito"]
    chosen = [v for v in nuclear if _finding(v) == "primary"]
    extra = [(word, [v for v in nuclear if _finding(v) == key]) for key, word in EXTRA_BLOCKS]
    extra = [(word, vs) for word, vs in extra if vs]
    genes = [v.get("gene", "").strip() for v in ticked]
    blk = _Block(doc)                   # before the primary parts are filled
    _fill_labels(doc, data)
    _fill_indication(doc, data)
    # Printed as the form's Summary box holds it: blank until the user automates or types it.
    _fill_summary(doc, data.summary.strip(), genes)
    snv = [v for v in chosen if kind(v) == "snv"]
    cnv = [v for v in chosen if kind(v) == "cnv"]
    mito_line = lambda: _para(doc, "Mitochondrial genome analysis", "'Mitochondrial genome analysis' line")  # noqa: E731
    if snv:     # the template's own table and description, filled in place
        _fill_table(_table(doc, "Gene", "primary finding table")._tbl, snv)
        _fill_footnote(_para(doc, "* AR=", "the table's footnote"), snv)
        desc = _para(doc, "Description of primary finding", "'Description of primary finding' heading")
        _fill_description(desc, mito_line(), snv, "" if cnv else data.conclusion, genes)
        heads = [_para(doc, "Table detailing primary finding", "table heading"), desc]
        _plural_headings(heads, len(snv))
        if cnv:
            for h in heads:
                _heading_suffix(h, "(SNV)")
    else:
        _drop_findings(doc, "" if cnv else data.conclusion, keep_heading=bool(extra or cnv))
    if cnv:
        _add_part(mito_line(), blk, cnv, "cnv", genes, conclusion=data.conclusion, suffix="(CNV)",
                  always_describe=True)
    for word, vs in extra:
        summary = getattr(data, f"{word}_summary", "").strip() or block_summary_default(vs, word)
        _add_block(doc, blk, word, vs, summary, genes)
    if mito:
        _add_mito(doc, blk, mito, data.mito.strip() or mito_summary_default(mito), genes)
    else:
        _set_tail_rich(mito_line(), " ".join(data.mito.split()) or MITO_DEFAULT)
    _fill_recommendations(doc, data.recommendations)
    _add_segment_tables(doc, blk, [v for v in nuclear if kind(v) == "cnv"])
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

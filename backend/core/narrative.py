"""Starting text of a variant's Description, Variant evidence and Classification
statement, in the lab's wording, built only from the variant's own values (the VarSeq
Excel and the OMIM tables). The form shows it in the variant's boxes, where the user
edits it; nothing here is printed without being shown there first.
"""
from __future__ import annotations

import re

from . import geneinfo
from . import variants as vr

_AMINO = {"Ala": "Alanine", "Arg": "Arginine", "Asn": "Asparagine", "Asp": "Aspartic acid",
          "Cys": "Cysteine", "Gln": "Glutamine", "Glu": "Glutamic acid", "Gly": "Glycine",
          "His": "Histidine", "Ile": "Isoleucine", "Leu": "Leucine", "Lys": "Lysine",
          "Met": "Methionine", "Phe": "Phenylalanine", "Pro": "Proline", "Ser": "Serine",
          "Thr": "Threonine", "Trp": "Tryptophan", "Tyr": "Tyrosine", "Val": "Valine"}

_PATTERN = {"AD": "an autosomal dominant", "AR": "an autosomal recessive",
            "XLR": "an X-linked recessive", "XLD": "an X-linked dominant", "XL": "an X-linked",
            "YL": "a Y-linked", "MT": "a mitochondrial"}
_MUTATION = {"AD": "Heterozygous mutation", "AR": "Homozygous or compound heterozygous mutation",
             "XLR": "Hemizygous mutation", "XLD": "Mutation", "XL": "Mutation"}


def _lower_first(text: str) -> str:
    """'Dihydropyrimidine dehydrogenase' -> 'dihydropyrimidine dehydrogenase'; acronyms
    ('CYLD lysine ...') stay."""
    text = text.strip()
    return text if text[:2].isupper() else text[:1].lower() + text[1:]


def _codes(v: dict) -> list[str]:
    return [c.strip().upper() for c in re.split(r"[,/]", v.get("inheritance", "")) if c.strip()]


def _kind(v: dict) -> str:
    from .renderer import kind      # late import: renderer imports this module
    return kind(v)


# ---------------------------------------------------------------------------
# Description: what the gene does and the disease it is associated with
# ---------------------------------------------------------------------------

def _omim_ids(v: dict, disease: str) -> str:
    ids = vr.omim_ids_in(v, disease)
    if not ids and len([d for d in v.get("disease", "").split(";") if d.strip()]) == 1:
        ids = [i for i in re.split(r"[,\s]+", v.get("omim_id", "")) if i]
    return ", ".join(ids)


def _with_omim(disease: str, ids: str) -> str:
    return f"{disease} (OMIM#{ids})" if ids else disease


def _gene_line(v: dict) -> str:
    gene, name = v.get("gene", "").strip(), v.get("gene_name", "").strip().strip("()")
    if not (gene and name):
        return ""
    if _kind(v) == "mito":
        return f"{gene} encodes the {_lower_first(name)}."
    return f"The {gene} gene encodes {_lower_first(name)}."


def _disease_line(v: dict) -> str:
    gene = v.get("gene", "").strip()
    diseases = [d.strip() for d in v.get("disease", "").split(";") if d.strip() and d.strip() != "-"]
    if not (gene and diseases):
        return ""
    gmim = v.get("gene_mim", "") or vr.gene_mim_number(gene)
    gene_ref = f"the {gene} gene (OMIM*{gmim})" if gmim else f"the {gene} gene"
    named = [_with_omim(_lower_first(d), _omim_ids(v, d)) for d in diseases]
    if len(diseases) > 1:
        return f"Mutations in {gene_ref} are associated with {vr_joined(named)}."
    code = vr.disease_inheritance(v, diseases[0]) or (_codes(v)[0] if len(_codes(v)) == 1 else "")
    lead = _MUTATION.get(code, "Mutation")
    text = f"{lead} in {gene_ref} is associated with {named[0]}"
    pattern = _PATTERN.get(code)
    return text + (f", which follows {pattern} pattern of inheritance." if pattern else ".")


def vr_joined(items: list[str]) -> str:
    return (", ".join(items[:-1]) + " and " + items[-1]) if len(items) > 1 else "".join(items)


def _chromosome(hgvs: str) -> str:
    m = re.match(r"\s*NC_0+(\d+)\.", hgvs)
    if m:
        n = int(m.group(1))
        return {23: "X", 24: "Y"}.get(n, str(n))
    m = re.match(r"\s*chr([0-9XYM]+)", hgvs, re.I)
    return m.group(1).upper() if m else ""


def _cnv_description(v: dict) -> str:
    from .renderer import cnv_hgvs, cnv_change, cnv_size, _cnv_chrom
    hgvs = cnv_hgvs(v)
    change = cnv_change(dict(v, cnv_hgvs=hgvs)).lower() or "change"
    zyg = vr.allele_status(v).strip().lower()
    zyg = f"{zyg} " if zyg and zyg != "-" else ""
    size = cnv_size(v)
    chrom = _cnv_chrom(v) or _chromosome(hgvs)
    text = f"A {zyg}copy number {change}" + (f" of ~{size}" if size else "")
    text += f" is observed on chromosome {chrom}" if chrom else " is observed"
    gene = v.get("gene", "").strip()
    diseases = [d.strip() for d in v.get("disease", "").split(";") if d.strip()]
    if gene:
        text += f" which overlaps the {gene} gene"
        if diseases:
            text += f" associated with {vr_joined(diseases)}"
    return text + "."


def description(v: dict) -> str:
    """Description box: the gene's function and its OMIM disease (a CNV: the copy
    number change); paragraphs separated by a blank line. The gene-function paragraph
    is the NCBI RefSeq summary when available (geneinfo), else the short built line."""
    if _kind(v) == "cnv":
        return _cnv_description(v)
    if _kind(v) == "mito":
        return _gene_line(v)
    gene_para = geneinfo.gene_function(v.get("gene", "").strip()) or _gene_line(v)
    return "\n\n".join(p for p in (gene_para, _disease_line(v), _disease_clinical(v)) if p)


def _disease_clinical(v: dict) -> str:
    """The clinical-description paragraph(s) ('X is characterized by ...'), from NCBI
    MedGen by each disease's OMIM phenotype number. Up to two, de-duplicated."""
    diseases = [d.strip() for d in v.get("disease", "").split(";") if d.strip() and d.strip() != "-"]
    out: list[str] = []
    for d in diseases:
        for omim in re.split(r"[,\s]+", _omim_ids(v, d)):   # same resolution as the association line
            if omim.strip().isdigit():
                txt = geneinfo.disease_description(omim.strip())
                if txt and txt not in out:
                    out.append(txt)
                    break
        if len(out) >= 2:
            break
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# Variant evidence: the variant itself, its population frequency, ClinVar
# ---------------------------------------------------------------------------

def _location(v: dict) -> str:
    region = vr.region(v)
    m = re.match(r"(exon|intron)\s*(\d+)\s*(?:/|of)\s*(\d+)", region, re.I)
    if m:
        return f"in {m.group(1).lower()} {m.group(2)} (of {m.group(3)})"
    m = re.match(r"(exon|intron)\s*(\d+)", region, re.I)
    return f"in {m.group(1).lower()} {m.group(2)}" if m else ""


def _protein_effect(v: dict) -> str:
    p = v.get("protein", "").partition(":p.")[2] or v.get("protein", "").partition("p.")[2]
    p = p.strip("()")
    m = re.fullmatch(r"([A-Z][a-z]{2})(\d+)[A-Z][a-z]{2}fs(?:Ter|\*)(\d+)", p)
    if m:
        return (f", which causes a frameshift starting at amino acid position {m.group(2)} "
                f"and is predicted to create a premature stop codon")
    m = re.fullmatch(r"([A-Z][a-z]{2})(\d+)(Ter|\*)", p)
    if m:
        return f", which creates a premature stop codon at amino acid position {m.group(2)}"
    m = re.fullmatch(r"([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})", p)
    if m and m.group(1) in _AMINO and m.group(3) in _AMINO and m.group(1) != m.group(3):
        return (f", resulting in the substitution of {_AMINO[m.group(1)]} with {_AMINO[m.group(3)]} "
                f"at amino acid position {m.group(2)} of the protein")
    return ""


def _variant_line(v: dict) -> str:
    zyg = vr.allele_status(v).strip().lower()
    zyg = "" if zyg == "-" else zyg
    cons = v.get("consequence", "").strip() or (
        "" if vr.sequence_ontology(v) == "-" else f"{vr.sequence_ontology(v)} variant")
    # lower-case each word but keep all-caps acronyms (UTR) and 3'/5'; end with "variant"
    cons = " ".join(w if (len(w) > 1 and w.isupper()) else w.lower() for w in cons.split())
    if cons and "variant" not in cons.split():
        cons += " variant"
    if not cons:
        cons = "variant"
    what = " ".join(p for p in (zyg, cons) if p)
    article = "an" if what[:1].lower() in "aeiou" else "a"
    loc = _location(v)
    return (f"The variant observed in this patient is {article} {what}"
            + (f" {loc}" if loc else "") + _protein_effect(v) + ".")


def _fmt_pct(p: float) -> str:
    """A percentage without scientific notation: '0.0046', '0.12', '3.4'."""
    s = (f"{p:.2f}" if p >= 1 else f"{p:.6f}").rstrip("0").rstrip(".")
    return s or "0"


def _frequency_line(v: dict) -> str:
    """The population-frequency sentence, in the lab's qualitative style (the reports
    say 'extremely rare', 'not reported', rarely an exact figure, and never scientific
    notation). An implausible value (> 100%) is reported without a number."""
    raw = str(v.get("gnomad_all", "")).strip()
    if not raw:
        return "This variant has not been reported in the general population database (gnomAD v4)."
    try:
        af = float(raw)
    except ValueError:
        return ""
    if af <= 0:
        return "This variant has not been reported in the general population database (gnomAD v4)."
    if af > 1:      # not a valid allele fraction (bad / percentage data): no bogus number
        return "This variant has been reported in the general population database (gnomAD v4)."
    pct = af * 100
    if pct < 0.01:
        return "This variant is extremely rare in the general population database (gnomAD v4)."
    if pct < 0.1:
        return ("This variant has been reported at a very low frequency in the general population "
                "database (gnomAD v4).")
    return (f"This variant has been observed in the general population database (gnomAD v4) at an "
            f"allele frequency of {_fmt_pct(pct)}%.")


def _clinvar_line(v: dict) -> str:
    label = vr._class_label(v.get("clinvar", "")).strip()
    if not label:
        return ""
    label = "of uncertain significance" if "uncertain" in label.lower() else label.lower()
    return f"This variant has been classified as {label} in the ClinVar database."


def evidence(v: dict) -> str:
    """Variant evidence box: the variant observed (type, position, protein change), its
    gnomAD frequency and its ClinVar classification (a mitochondrial variant: its
    heteroplasmy level). Paragraphs separated by a blank line."""
    k = _kind(v)
    if k == "cnv":
        return ""
    if k == "mito":
        level = v.get("heteroplasmy", "").strip().rstrip("%").strip()
        ident = v.get("variant", "").strip()
        if ident and not re.match(r"[mgc]\.", ident):
            ident = f"m.{ident}"
        if not level:
            return ""
        return f"The {ident or 'variant'} variant identified in this patient is present at a heteroplasmy level of {level}%."
    return "\n\n".join(p for p in (_variant_line(v), _frequency_line(v), _clinvar_line(v)) if p)


def statement(v: dict) -> str:
    """The bold classification sentence after the evidence."""
    c = vr.classification(v).strip()
    if not c:
        return ""
    what = "a variant of uncertain significance" if "uncertain" in c.lower() else c.lower()
    k = _kind(v)
    if k == "cnv":
        return f"Based on the available evidence, this variant is classified as {what}."
    if k == "mito":
        return ("Based on the ACMG/AMP guidelines for mitochondrial DNA variants, this variant is "
                f"classified as {what}.")
    return f"Based on ACMG criteria, this variant is classified as {what}."


def title(v: dict) -> str:
    """The bold 'Variant NM_..:c.. / NP_..:p.. in GENE gene' line over the description
    (none for a CNV: the lab's reports describe a single CNV without one)."""
    from .renderer import _title     # late import: renderer imports this module
    parts = _title(v, False)
    return "".join(t for t, *_ in parts) if parts else ""


def full_description(v: dict) -> str:
    """The Description box as the report prints it: the bold title line, the gene /
    disease paragraphs, the variant evidence, then the classification statement in
    **bold**; paragraphs separated by a blank line."""
    s, t = statement(v), title(v)
    return "\n\n".join(p for p in (f"**{t}**" if t else "", description(v), evidence(v),
                                   f"**{s}**" if s else "") if p)


def texts(v: dict) -> dict:
    """The built text of one variant's Description box."""
    return {"description": full_description(v)}

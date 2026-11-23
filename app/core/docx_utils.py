"""Small Word (python-docx / OOXML) helpers used by the renderer."""
from __future__ import annotations

import copy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


class TemplateError(Exception):
    """The template is missing a part the renderer looks for."""


def runs(p_el):
    """The paragraph's text runs."""
    return [r for r in p_el.iter(qn("w:r")) if r.find(qn("w:t")) is not None]


def text(el) -> str:
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def set_text(p_el, value: str) -> None:
    """Replace a paragraph's text, keeping the first run's formatting (or the
    paragraph mark's when it has no run). Line breaks become Word line breaks."""
    rs = runs(p_el)
    if rs:
        first = rs[0]
        for r in rs[1:]:
            r.getparent().remove(r)
        for child in list(first):
            if child.tag != qn("w:rPr"):
                first.remove(child)
    else:
        first = OxmlElement("w:r")
        rpr = p_el.find(qn("w:pPr") + "/" + qn("w:rPr"))
        if rpr is not None:
            first.append(copy.deepcopy(rpr))
        p_el.append(first)
    for i, line in enumerate(value.split("\n")):
        if i:
            first.append(OxmlElement("w:br"))
        t = OxmlElement("w:t")
        t.text = line
        t.set(qn("xml:space"), "preserve")
        first.append(t)


def _is_bold(r) -> bool:
    rpr = r.find(qn("w:rPr"))
    return rpr is not None and rpr.find(qn("w:b")) is not None


def set_para_tail(p_el, value: str) -> None:
    """Keep the paragraph's bold lead-in ('Mitochondrial genome analysis: ') as one
    run and replace the rest with `value`, in the format of the first non-bold run."""
    rs = runs(p_el)
    k = next((i for i, r in enumerate(rs) if not _is_bold(r)), None)
    if not k:
        return
    lead = rs[:k]
    lead_text = "".join(text(r) for r in lead)
    for r in lead[1:]:
        r.getparent().remove(r)
    ts = list(lead[0].iter(qn("w:t")))
    ts[0].text = lead_text
    ts[0].set(qn("xml:space"), "preserve")
    for t in ts[1:]:
        t.getparent().remove(t)
    tail = rs[k]
    for child in list(tail):
        if child.tag != qn("w:rPr"):
            tail.remove(child)
    t = OxmlElement("w:t")
    t.text = value
    t.set(qn("xml:space"), "preserve")
    tail.append(t)
    for later in list(tail.itersiblings()):
        if later.tag in (qn("w:r"), qn("w:hyperlink")):
            p_el.remove(later)

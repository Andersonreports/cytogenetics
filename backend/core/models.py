"""Data model of one CMC Cytogenetics WES & Mito report."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date


def today_str() -> str:
    return date.today().strftime("%d/%m/%Y")


def _from_dict(cls, d: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (d or {}).items() if k in names})


@dataclass
class PatientInfo:
    """The NAME / HOSP NO table at the top of the report."""
    name: str = ""
    hosp_no: str = ""
    age: str = ""
    lab_no: str = ""
    sex: str = ""
    sample: str = ""
    referred_by: str = ""
    received_date: str = ""
    unit: str = ""
    report_date: str = ""


@dataclass
class ReportData:
    patient: PatientInfo = field(default_factory=PatientInfo)
    indication: str = ""
    # Listed variants (core.variants) with a "selected" flag: the ticked ones are
    # reported. Each one's "finding" puts it in the primary block ("" / "primary"),
    # the Secondary finding block ("secondary") or the Incidental finding block
    # ("incidental"); no primary one ticked = a report with no primary finding.
    variants: list = field(default_factory=list)
    summary: str = ""            # blank = built from the ticked variants
    secondary_summary: str = ""  # Summary of the Secondary finding block; blank = built
    incidental_summary: str = "" # Summary of the Incidental finding block; blank = built
    conclusion: str = ""         # paragraph(s) after the variant descriptions (**bold** as typed)
    mito: str = ""               # blank = "No variant that warrants reporting was identified."
    recommendations: str = ""    # blank = no Recommendations section
    signatory: str = ""          # "Dr. Name\nDesignation"; blank = "Dr." left to fill

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ReportData":
        d = dict(d or {})
        data = _from_dict(cls, {k: v for k, v in d.items() if k != "patient"})
        data.patient = _from_dict(PatientInfo, d.get("patient", {}))
        data.variants = [dict(v) for v in d.get("variants", []) or []]
        for name in ("indication", "summary", "secondary_summary", "incidental_summary",
                     "conclusion", "mito", "recommendations", "signatory"):
            setattr(data, name, str(getattr(data, name) or ""))
        return data

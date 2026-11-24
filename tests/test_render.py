"""Smoke tests: the template fills with and without variants, and the web API answers.

Run:  python -m unittest discover -s tests -v
Uses a made-up variant (no patient data).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.core.models import PatientInfo, ReportData  # noqa: E402
from backend.core.renderer import MITO_DEFAULT, NO_VARIANT_SUMMARY, file_stem, render_report  # noqa: E402

VARIANT = {
    "gene": "DPYD", "nm_id": "NM_000110.4", "variant": "c.1905+1G>A", "protein": "NP_000101.2:p.(?)",
    "genomic_position": "Chr1:NC_000001.11:g.97450058C>T (NM_000110.4)", "region": "Intron 14/22",
    "consequence": "Splice Donor Variant", "zygosity": "HET", "classification": "Pathogenic",
    "disease": "Dihydropyrimidine dehydrogenase deficiency", "inheritance": "AR",
    "gene_name": "Dihydropyrimidine dehydrogenase", "hgnc": "3012",
    "omim_phenotype": "The DPYD gene encodes dihydropyrimidine dehydrogenase.",
    "evidence": "First evidence paragraph.\n\nSecond evidence paragraph.", "selected": True,
}


def _texts(doc):
    return [p.text for p in doc.paragraphs]


def _table_text(doc, first):
    t = next(t for t in doc.tables if t.rows[0].cells[0].text.strip().upper().startswith(first))
    return [[c.text for c in r.cells] for r in t.rows]


class RenderTests(unittest.TestCase):
    def data(self, variants):
        return ReportData(
            patient=PatientInfo(name="Test Patient", hosp_no="123456A", age="6 Years", lab_no="WES 01/26",
                                sex="Male", sample="Peripheral Blood", referred_by="Dr. A",
                                received_date="01/11/2026", unit="Clinical Genetics",
                                report_date="23/11/2026"),
            indication="Seizures", variants=variants,
            recommendations="Counselling is advised.", signatory="Dr. B\nProfessor")

    def test_with_variant(self):
        doc = render_report(self.data([dict(VARIANT)]))
        texts = _texts(doc)
        labels = _table_text(doc, "NAME")
        self.assertEqual(labels[0][2], "Test Patient")
        self.assertEqual(labels[0][5], "123456A")
        self.assertEqual(labels[1][5], "WES 01/26")
        rows = _table_text(doc, "GENE")
        self.assertEqual(len(rows), 2)
        self.assertIn("DPYD", rows[1][0])
        self.assertIn("HGNC: 3012", rows[1][0])
        self.assertIn("NC_000001.11:g.97450058C>T", rows[1][2])
        self.assertNotIn("Chr1", rows[1][2])
        self.assertIn("Heterozygous", rows[1][3])
        self.assertIn("(AR)", rows[1][4])
        self.assertTrue(any(t.startswith("Whole exome analysis in this sample shows the following "
                                         "pathogenic variant in the DPYD gene") for t in texts))
        self.assertIn("Variant NM_000110.4:c.1905+1G>A / NP_000101.2:p.(?) in DPYD gene", texts)
        self.assertIn("Second evidence paragraph.", texts)
        self.assertIn(f"Mitochondrial genome analysis: {MITO_DEFAULT}", texts)
        self.assertIn("Counselling is advised.", texts)
        self.assertTrue(any(t.startswith("* AR= autosomal recessive") for t in texts))
        self.assertEqual(rows[0][5].strip(), "ACMG classification (attributes)")
        self.assertIn("Table detailing primary finding:", [t.strip() for t in texts])
        self.assertIn("Description of primary finding:", texts)

    def test_criteria_and_plural_headings(self):
        two = [dict(VARIANT, criteria="PVS1,PM2 Supporting"), dict(VARIANT, gene="TP53", criteria="")]
        doc = render_report(self.data(two))
        texts = [t.strip() for t in _texts(doc)]
        rows = _table_text(doc, "GENE")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][5].split("\n"), ["Pathogenic", "", "(PVS1, PM2 Supporting)"])
        self.assertEqual(rows[2][5].strip(), "Pathogenic")
        self.assertIn("Table detailing primary findings:", texts)
        self.assertIn("Description of primary findings:", texts)

    def test_old_omim_sentence_left_out(self):
        """A form saved by an older version still holds the pre-filled OMIM sentence:
        only the bold title line is printed."""
        auto = "Dihydropyrimidine dehydrogenase deficiency (OMIM#274270) is caused by mutation in the DPYD gene (OMIM*612779)."
        doc = render_report(self.data([dict(VARIANT, omim_phenotype=auto, omim_phenotype_prefix=auto,
                                            evidence="")]))
        texts = [t.strip() for t in _texts(doc)]
        title = "Variant NM_000110.4:c.1905+1G>A / NP_000101.2:p.(?) in DPYD gene"
        self.assertIn(title, texts)
        self.assertNotIn(auto, texts)
        self.assertTrue(texts[texts.index(title) + 1].startswith("Mitochondrial genome analysis"))

    def test_without_variant(self):
        d = self.data([dict(VARIANT, selected=False)])
        d.recommendations = ""
        texts = _texts(render_report(d))
        self.assertIn(NO_VARIANT_SUMMARY, texts)
        self.assertFalse(any(t.startswith(("Primary finding", "Table detailing", "Description of",
                                           "Recommendations")) for t in texts))

    def test_file_stem(self):
        self.assertEqual(file_stem(self.data([])), "Test_Patient_WES_&_Mito_Report_23_11_2026")


class ApiTests(unittest.TestCase):
    def test_init_and_page(self):
        from backend.server import app
        c = app.test_client()
        self.assertEqual(c.get("/").status_code, 200)
        self.assertIn("today", c.get("/api/init").get_json())

    def test_export_docx(self):
        from backend.server import app
        c = app.test_client()
        r = c.post("/api/export", json={"kind": "docx", "data": RenderTests().data([VARIANT]).to_dict()})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Test_Patient_WES_", r.headers["Content-Disposition"])
        r.close()


class ExtraBlockTests(unittest.TestCase):
    """Secondary / Incidental finding blocks."""

    def test_primary_secondary_incidental(self):
        vs = [dict(VARIANT),
              dict(VARIANT, gene="SCN5A", finding="secondary", classification="Likely Pathogenic",
                   omim_phenotype="", evidence=""),
              dict(VARIANT, gene="HBB", finding="incidental", zygosity="Heterozygous",
                   omim_phenotype="HBB encodes beta-globin.", evidence=""),
              dict(VARIANT, gene="G6PD", finding="incidental", omim_phenotype="", evidence="")]
        d = RenderTests().data(vs)
        d.secondary_summary = "An actionable variant was identified in the SCN5A gene."
        texts = [t.strip() for t in _texts(render_report(d))]
        order = ["Primary finding:", "Table detailing primary finding:", "Description of primary finding:",
                 "Secondary finding:", "An actionable variant was identified in the SCN5A gene.",
                 "Table detailing secondary finding:",
                 "Incidental finding:", "Table detailing incidental findings:",
                 "Description of incidental findings:", "HBB encodes beta-globin.",
                 f"Mitochondrial genome analysis: {MITO_DEFAULT}"]
        pos = [texts.index(t) for t in order]
        self.assertEqual(pos, sorted(pos))
        self.assertNotIn("Description of secondary finding:", texts)     # no text -> no description
        # One paragraph per incidental variant; one heterozygous pathogenic variant of an AR
        # disease gets the carrier-state sentences.
        hbb = next(t for t in texts if t.startswith("A pathogenic variant was identified in the HBB gene"))
        self.assertEqual(hbb, "A pathogenic variant was identified in the HBB gene in a heterozygous state. "
                              "This variant is associated with Dihydropyrimidine dehydrogenase deficiency, an "
                              "autosomal recessive condition. This finding is unlikely to contribute to the "
                              "patient’s clinical phenotype. As the variant is present in the heterozygous "
                              "state, the patient is considered a carrier of dihydropyrimidine dehydrogenase "
                              "deficiency and is not, in usual circumstances, expected to manifest clinical "
                              "features of dihydropyrimidine dehydrogenase deficiency. This variant is being "
                              "reported to facilitate appropriate carrier screening for family members and "
                              "genetic counselling.")
        self.assertTrue(any(t.startswith("A pathogenic variant was identified in the G6PD gene") for t in texts))
        doc = render_report(d)
        genes = [t.rows[1].cells[0].text.split("\n")[0] for t in doc.tables
                 if t.rows[0].cells[0].text.strip().upper().startswith("GENE")]
        self.assertEqual(genes, ["DPYD", "SCN5A", "HBB"])

    def test_incidental_only(self):
        d = RenderTests().data([dict(VARIANT, finding="incidental")])
        texts = [t.strip() for t in _texts(render_report(d))]
        self.assertIn("Primary finding:", texts)            # kept, as the lab's reports do
        self.assertIn(NO_VARIANT_SUMMARY, texts)
        self.assertNotIn("Table detailing primary finding:", texts)
        self.assertIn("Incidental finding:", texts)
        self.assertIn("Table detailing incidental finding:", texts)
        self.assertIn("Description of incidental finding:", texts)


CNV = {"kind": "cnv", "gene": "DMD", "variant": "NC_000023.11:g.(?_31874949)_(31968677_?)del",
       "zygosity": "Hemizygous", "size": "93.73 kb", "disease": "Becker muscular dystrophy",
       "inheritance": "XLR", "classification": "Pathogenic", "criteria": "1A, 2E",
       "evidence": "A hemizygous copy number loss is observed on chromosome X.",
       "statement": "Based on the available evidence, this variant is classified as pathogenic.",
       "segment_genes": "DMD", "selected": True}
MITO = {"kind": "mito", "gene": "MT-TI", "variant": "4296G>A", "heteroplasmy": "80.46",
        "disease": "Mitochondrial disease", "classification": "Variant of Uncertain Significance",
        "criteria": "PM2_Supporting", "evidence": "MT-TI encodes a tRNA.", "selected": True}


class CnvMitoTests(unittest.TestCase):
    """Copy number and mitochondrial variants, as in the lab's CNV / mtDNA reports."""

    def test_cnv_only(self):
        doc = render_report(RenderTests().data([dict(CNV)]))
        texts = [t.strip() for t in _texts(doc)]
        self.assertIn("Primary finding:", texts)
        self.assertNotIn("Table detailing primary finding:", texts)
        self.assertIn("Table detailing primary finding (CNV):", texts)
        self.assertIn("Description of primary finding (CNV):", texts)
        self.assertTrue(any(t.startswith("Sequencing data was indicative of the following pathogenic copy "
                                         "number variant (CNV) overlapping the DMD gene") for t in texts))
        self.assertIn(CNV["statement"], texts)
        rows = _table_text(doc, "VARIANT")
        self.assertEqual(rows[0][5], "ACMG/ClinGen classification")
        self.assertEqual(rows[1][:3], [CNV["variant"], "Hemizygous", "93.73 kb"])
        self.assertIn("recessive", rows[1][4])
        seg = _table_text(doc, "REGION")
        self.assertEqual(seg[1][1:], ["Loss", "93.73 kb", "DMD"])
        self.assertLess(texts.index("Table showing all genes in the involved segment:"), next(i for i, t in enumerate(texts) if t.startswith("Dr. B")))

    def test_snv_and_cnv(self):
        texts = [t.strip() for t in _texts(render_report(RenderTests().data([dict(VARIANT), dict(CNV)])))]
        order = ["Table detailing primary finding (SNV):", "Description of primary finding (SNV):",
                 "Table detailing primary finding (CNV):", "Description of primary finding (CNV):"]
        pos = [texts.index(t) for t in order]
        self.assertEqual(pos, sorted(pos))

    def test_mito(self):
        doc = render_report(RenderTests().data([dict(VARIANT), dict(MITO)]))
        texts = [t.strip() for t in _texts(doc)]
        self.assertIn("Mitochondrial genome analysis:", texts)
        self.assertIn("A variant of uncertain significance was identified in the mitochondrial gene MT-TI at "
                      "a heteroplasmy level of 80.46% (see table and description below).", texts)
        self.assertIn("Variant NC_012920.1:m.4296G>A in MT-TI gene", texts)
        self.assertLess(texts.index("Description of mitochondrial variant:"), texts.index("Recommendations"))
        rows = [r for r in (_table_text(doc, "GENE"),)][0]      # the primary table: DPYD only
        self.assertEqual(len(rows), 2)
        mt = [t for t in doc.tables if t.rows[0].cells[0].text.strip() == "Gene"
              and t.rows[0].cells[2].text.strip() == "DNA source"][0]
        cells = [c.text for c in mt.rows[1].cells]
        self.assertIn("NC_012920.1(MT-TI):m.4296G>A", cells[1])
        self.assertEqual(cells[2], "Blood")
        self.assertEqual(cells[4], "Heteroplasmy\n(80.46%)")
        self.assertTrue(any("mitochondrial DNA variant interpretation" in t for t in texts))


class DescriptionBoxTests(unittest.TestCase):
    """The variant's one Description box: paragraphs and **bold** as typed."""

    def test_bold_and_paragraphs(self):
        v = dict(VARIANT, description="The DPYD gene encodes an enzyme.\n\n"
                                      "**While this variant is established, its relevance is uncertain.**")
        doc = render_report(RenderTests().data([v]))
        paras = [p for p in doc.paragraphs if p.text.strip()]
        i = next(k for k, p in enumerate(paras) if p.text.startswith("Variant NM_000110.4"))
        self.assertEqual(paras[i + 1].text, "The DPYD gene encodes an enzyme.")
        self.assertEqual(paras[i + 2].text, "While this variant is established, its relevance is uncertain.")
        self.assertTrue(all(r.bold for r in paras[i + 2].runs if r.text.strip()))
        self.assertFalse(any(r.bold for r in paras[i + 1].runs if r.text.strip()))
        self.assertNotIn("**", "".join(p.text for p in paras))

    def test_italic(self):
        v = dict(VARIANT, description="Plain <i>italic words</i> and **bold <i>both</i>** end.")
        doc = render_report(RenderTests().data([v]))
        p = next(p for p in doc.paragraphs if p.text.startswith("Plain"))
        self.assertEqual(p.text, "Plain italic words and bold both end.")
        style = {r.text: (bool(r.bold), bool(r.italic)) for r in p.runs if r.text.strip()}
        self.assertEqual(style["italic words"], (False, True))
        self.assertEqual(style["both"], (True, True))
        self.assertEqual(style["bold "], (True, False))
        self.assertEqual(style["Plain "], (False, False))

    def test_title_line_in_box(self):
        """The box's own (edited) bold 'Variant ...' line replaces the built one."""
        v = dict(VARIANT, description="**Variant NM_000110.4:c.1905+1G>A in DPYD gene (edited)**\n\nBody text.")
        texts = [p.text.strip() for p in render_report(RenderTests().data([v])).paragraphs]
        self.assertIn("Variant NM_000110.4:c.1905+1G>A in DPYD gene (edited)", texts)
        self.assertNotIn("Variant NM_000110.4:c.1905+1G>A / NP_000101.2:p.(?) in DPYD gene", texts)
        self.assertEqual(texts[texts.index("Variant NM_000110.4:c.1905+1G>A in DPYD gene (edited)") + 1],
                         "Body text.")
        # A box without the line still gets the built one.
        texts = [p.text.strip() for p in render_report(RenderTests().data([dict(VARIANT, description="Only body.")])).paragraphs]
        i = texts.index("Variant NM_000110.4:c.1905+1G>A / NP_000101.2:p.(?) in DPYD gene")
        self.assertEqual(texts[i + 1], "Only body.")

    def test_old_three_boxes_joined(self):
        v = dict(VARIANT, statement="Classified as pathogenic.")
        texts = [p.text for p in render_report(RenderTests().data([v])).paragraphs]
        pos = [texts.index(t) for t in ("The DPYD gene encodes dihydropyrimidine dehydrogenase.",
                                         "Second evidence paragraph.", "Classified as pathogenic.")]
        self.assertEqual(pos, sorted(pos))


class SummaryTests(unittest.TestCase):
    """The generated Summary the form shows in its box (and the report prints)."""

    def test_carrier_summary(self):
        from backend.core.renderer import summary_default
        self.assertEqual(summary_default([dict(VARIANT)]),
                         "Whole exome analysis in this sample shows the following pathogenic variant in the DPYD "
                         "gene that is associated with autosomal recessive dihydropyrimidine dehydrogenase "
                         "deficiency (see table and description below). Note that causation of disease with "
                         "respect to this condition requires bi-allelic disease causing variants. The presence "
                         "of only one pathogenic variant as seen in this patient represents a carrier state.")

    def test_variant_texts(self):
        from backend.core import narrative
        v = dict(VARIANT, gene="STS", gene_name="Steroid sulfatase", disease="Ichthyosis, X-linked",
                 inheritance="XLR", region="Exon 8/10", consequence="Missense Variant",
                 protein="NP_000342.3:p.Arg381Ser", gnomad_all="4.55453e-06", gnomad_sa="4",
                 clinvar="Uncertain Significance", classification="Variant of Uncertain Significance")
        t = {"omim_phenotype": narrative.description(v), "evidence": narrative.evidence(v),
             "statement": narrative.statement(v)}
        full = narrative.texts(v)["description"]
        self.assertTrue(full.endswith("**Based on ACMG criteria, this variant is classified as a variant "
                                      "of uncertain significance.**"))
        self.assertTrue(t["omim_phenotype"].startswith("The STS gene encodes steroid sulfatase."))
        self.assertIn("is associated with Ichthyosis, X-linked", t["omim_phenotype"])
        self.assertIn("heterozygous missense variant in exon 8 (of 10), resulting in the substitution of "
                      "Arginine with Serine at amino acid position 381", t["evidence"])
        self.assertIn("allele frequency of 0.00046%, with 4 alleles in the South Asian population", t["evidence"])
        self.assertIn("classified as of uncertain significance in the ClinVar database", t["evidence"])
        self.assertEqual(t["statement"], "Based on ACMG criteria, this variant is classified as a variant "
                                         "of uncertain significance.")

    def test_secondary_and_no_variant_summaries(self):
        from backend.core.renderer import block_summary_default, summary_default
        g = dict(VARIANT, gene="G6PD", disease="Anemia, congenital nonspherocytic hemolytic, 1", inheritance="XLR")
        self.assertEqual(block_summary_default([g], "secondary"),
                         "A pathogenic variant in the G6PD gene was identified (see table below) in this sample. "
                         "Pathogenic mutations in this gene cause anemia, congenital nonspherocytic hemolytic, 1. "
                         "The contribution of this variant to the indication for testing in this patient is "
                         "uncertain. However, this variant is being reported to facilitate appropriate "
                         "management of the related condition.\n\n"
                         "Further details are provided in the table and description below.")
        self.assertTrue(summary_default([]).startswith(
            "Whole exome and mitochondrial sequencing did not detect any pathogenic / likely pathogenic"))

    def test_defaults_api(self):
        from backend.server import app
        data = RenderTests().data([dict(VARIANT), dict(VARIANT, gene="HBB", finding="incidental")]).to_dict()
        j = app.test_client().post("/api/defaults", json={"data": data}).get_json()
        self.assertTrue(j["summary"].startswith("Whole exome analysis in this sample shows the following "
                                                "pathogenic variant in the DPYD gene"))
        self.assertIn("HBB gene", j["incidental_summary"])
        self.assertEqual(j["secondary_summary"], "")
        self.assertEqual(j["mito"], MITO_DEFAULT)


class RawExportTests(unittest.TestCase):
    """The full VarSeq table export: title row, column-group row, column-name row."""

    def test_reads_table_fields(self):
        import tempfile
        from openpyxl import Workbook
        from backend.core import renderer, variants as vr
        cols = [  # (group, name, value); made-up variant, no patient data
            ("Complex Variants x.vcf.gz", "Variant Allele Fraction", None),   # empty INFO block
            ("", "Allelic Depths (AD)", None),
            ("Variant Info", "Chr:Pos", "1:97450058"), ("", "Ref/Alt", "C/T"),
            ("SAMPLE", "Variant Allele Fraction", 0.5), ("", "Allelic Depths (AD)", "50,50"),
            ("", "Zygosity", "Heterozygous"),
            ("Flags", "Primary Finding", "True"), ("", "Secondary Finding", "False"),
            ("RefSeq Genes 110 v2, NCBI", "Gene Names", "DPYD"),
            ("", "Transcript Name (Clinically Relevant)", "NM_000110.4"),
            ("", "Exon Number (Clinically Relevant)", 14),
            ("", "HGVS c. (Clinically Relevant)", "NM_000110.4:c.1905G>A"),
            ("", "HGVS p. (Clinically Relevant)", "NP_000101.2:p.Trp635Ter"),
            ("", "Sequence Ontology (Clinically Relevant)", "stop_gained"),
            ("OMIM Phenotypes with Details", "OMIM ID", "274270"),
            ("", "Inheritance", "Autosomal recessive"),
            ("", "Title", "DIHYDROPYRIMIDINE DEHYDROGENASE DEFICIENCY; DPDD"),
            ("ACMG Sample Classifier for SAMPLE", "Classification", "Pathogenic"),
            ("Transcript Interactions RefSeq Genes", "Transcript Name", "NM_X.1,NM_000110.4"),
            ("", "Exon Number", "13,14"), ("", "# of Exons", "22,23"),
            ("Aux Fields RefSeq Genes 110 v2, NCBI", "Transcript Name", "NM_X.1,NM_000110.4"),
            ("", "Summary of Product", "other,dihydropyrimidine dehydrogenase"),
            ("", "HGNC", "3012,3012"),
            ("", "Product ID", "NP_X.1,NP_000101.2"),
        ]
        wb = Workbook()
        ws = wb.active
        ws.append(["Complex Variants x.vcf.gz for SAMPLE"])
        ws.append([g or None for g, _, _ in cols])
        ws.append([n for _, n, _ in cols])
        ws.append([v for _, _, v in cols])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "raw.xlsx")
            wb.save(path)
            (v,) = vr.read_variants(path)
        self.assertEqual((v["gene"], v["nm_id"], v["variant"]), ("DPYD", "NM_000110.4", "c.1905G>A"))
        self.assertEqual(v["protein"], "NP_000101.2:p.Trp635Ter")
        self.assertEqual(v["gene_name"], "Dihydropyrimidine dehydrogenase")
        self.assertEqual(v["hgnc"], "3012")
        self.assertEqual(vr.region(v), "Exon 14/23")
        self.assertEqual(v["consequence"], "Nonsense Variant")
        self.assertEqual(vr.classification(v), "Pathogenic")
        self.assertEqual(vr.allelic_depth(v), "Ref(C): 50, Alt(T): 50, VAF: 50.00%")
        self.assertEqual(renderer._diseases(v), ["Dihydropyrimidine dehydrogenase deficiency (AR)"])
        self.assertEqual(renderer._genomic(v), "NC_000001.11:g.97450058C>T")

        # No HGVS p. (UTR / intronic): the transcript's NP accession with p.(?)
        ws.cell(4, next(i for i, (_, n, _) in enumerate(cols, 1)
                        if n == "HGVS p. (Clinically Relevant)")).value = None
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "raw.xlsx")
            wb.save(path)
            (v,) = vr.read_variants(path)
        self.assertEqual(v["protein"], "NP_000101.2:p.(?)")


if __name__ == "__main__":
    unittest.main()

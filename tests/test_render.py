"""Smoke tests: the template fills with and without variants, and the web API answers.

Run:  python -m unittest discover -s tests -v
Uses a made-up variant (no patient data).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.models import PatientInfo, ReportData  # noqa: E402
from app.core.renderer import MITO_DEFAULT, NO_VARIANT_SUMMARY, file_stem, render_report  # noqa: E402

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
        from app.web.server import app
        c = app.test_client()
        self.assertEqual(c.get("/").status_code, 200)
        self.assertIn("today", c.get("/api/init").get_json())

    def test_export_docx(self):
        from app.web.server import app
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
        self.assertIn("A pathogenic variant was identified in the HBB gene in a heterozygous state. "
                      "A pathogenic variant was identified in the G6PD gene in a heterozygous state "
                      "(see table below).", texts)
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


class RawExportTests(unittest.TestCase):
    """The full VarSeq table export: title row, column-group row, column-name row."""

    def test_reads_table_fields(self):
        import tempfile
        from openpyxl import Workbook
        from app.core import renderer, variants as vr
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

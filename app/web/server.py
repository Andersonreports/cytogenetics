"""Flask server: the form page and its API (variants upload, preview, export)."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import traceback

from flask import Flask, jsonify, render_template, request, send_file

from ..core import variants as vr
from ..core.models import ReportData, today_str
from ..core.pdf import docx_to_pdf, pdf_pages_png
from ..core.renderer import MITO_DEFAULT, NO_VARIANT_SUMMARY, file_stem, render_docx

app = Flask(__name__, template_folder="templates")

SAMPLES = ["Peripheral Blood", "DNA", "Amniotic fluid", "Product Of Conception", "CVS"]
CLASSES = ["Pathogenic", "Likely Pathogenic", "Variant of Uncertain Significance",
           "Pathogenic (carrier state)", "Drug response", "Likely Benign", "Benign"]


def _later_rmtree(path: str, delay: int = 60) -> None:
    """Remove a temp folder once the browser has had time to download from it."""
    threading.Timer(delay, lambda: shutil.rmtree(path, ignore_errors=True)).start()


def _error(e: Exception, status: int = 500):
    traceback.print_exc()
    return jsonify({"error": str(e)}), status


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/init")
def api_init():
    return jsonify({
        "today": today_str(), "samples": SAMPLES, "classes": CLASSES,
        "mito_default": MITO_DEFAULT, "no_variant_summary": NO_VARIANT_SUMMARY,
    })


@app.route("/api/upload-variants", methods=["POST"])
def api_upload_variants():
    file = request.files.get("file")
    if file is None:
        return jsonify({"error": "No file uploaded."}), 400
    tmp = tempfile.mkdtemp(prefix="cyto_xlsx_")
    try:
        path = os.path.join(tmp, "variants.xlsx")
        file.save(path)
        found = vr.read_variants(path)
    except vr.VariantError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001 - shown to the user
        return _error(e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for v in found:     # the boxes the form edits, starting from the Excel's values
        v["genomic_position"] = vr.genomic_text(v)
        v["class_options"] = vr.classification_options(v)
        v["consequence_default"] = ("" if vr.sequence_ontology(v) == "-"
                                    else f"{vr.sequence_ontology(v)} Variant")
        v["region_default"] = vr.region(v)
        v["omim_phenotype"] = ""    # the description is typed by the user, not pre-filled
        # VarSeq's "Secondary Finding" flag (or a "Secondary Findings" block) -> that block
        v["finding"] = "secondary" if vr.is_secondary(v) else ""
        v.setdefault("gene_name", "")
        v.setdefault("hgnc", "")
        v.setdefault("consequence", "")
    return jsonify({"variants": found})


@app.route("/api/preview", methods=["POST"])
def api_preview():
    body = request.json or {}
    tmp = tempfile.mkdtemp(prefix="cyto_preview_")
    try:
        data = ReportData.from_dict(body.get("data", {}))
        docx = render_docx(data, os.path.join(tmp, "preview.docx"))
        pdf = docx_to_pdf(docx, tmp)
        width = max(400, min(int(body.get("width") or 900), 1600))
        return jsonify({"pages": pdf_pages_png(pdf, width)})
    except Exception as e:  # noqa: BLE001 - shown in the preview panel
        return _error(e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.route("/api/export", methods=["POST"])
def api_export():
    body = request.json or {}
    kind = body.get("kind", "docx")
    tmp = tempfile.mkdtemp(prefix="cyto_export_")
    try:
        data = ReportData.from_dict(body.get("data", {}))
        stem = file_stem(data)
        docx = render_docx(data, os.path.join(tmp, stem + ".docx"))
        if kind == "pdf":
            path, mime = docx_to_pdf(docx, tmp), "application/pdf"
        else:
            path = docx
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        _later_rmtree(tmp)
        return send_file(path, mimetype=mime, as_attachment=True,
                         download_name=os.path.basename(path))
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        return _error(e)

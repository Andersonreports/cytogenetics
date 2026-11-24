"""DOCX -> PDF (Microsoft Word on Windows, else LibreOffice) and PDF -> page images.

Word is kept open on one thread of its own between conversions (a COM object can
only be used from the thread that made it, and every web request runs on its own
thread). LibreOffice keeps one profile between runs so only the first conversion
pays its ~10 s start-up.
"""
from __future__ import annotations

import atexit
import base64
import io
import os
import queue
import subprocess
import tempfile
import threading
from pathlib import Path

from .os_utils import find_soffice


class PdfError(Exception):
    pass


_PROFILE = os.path.join(tempfile.gettempdir(), "cyto_lo_profile")
_LOCK = threading.Lock()


def _via_libreoffice(soffice: str, docx_path: str, out_dir: str) -> None:
    cmd = [soffice, "--headless", "--norestore", "--nologo", "--nolockcheck",
           f"-env:UserInstallation={Path(_PROFILE).as_uri()}",
           "--convert-to", "pdf", "--outdir", out_dir, docx_path]
    with _LOCK:
        try:
            subprocess.run(cmd, capture_output=True, timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as e:
            raise PdfError("PDF conversion timed out") from e


class _WordThread:
    """A private, hidden Word instance owned by one thread; quits at exit."""

    def __init__(self):
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start = threading.Lock()

    def call(self, fn):
        with self._start:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="word-pdf", daemon=True)
                self._thread.start()
        done, box = threading.Event(), {}
        self._jobs.put((fn, done, box))
        done.wait()
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def _loop(self):
        import pythoncom
        from win32com.client import DispatchEx
        pythoncom.CoInitialize()
        word, stopped = None, None
        try:
            while True:
                fn, done, box = self._jobs.get()
                if fn is None:
                    stopped = done
                    return
                try:
                    if word is None:
                        word = DispatchEx("Word.Application")
                        word.Visible = False
                        word.DisplayAlerts = 0
                    box["result"] = fn(word)
                except Exception as e:  # noqa: BLE001 - re-raised in call()
                    box["error"] = e
                    try:                        # Word may have died: start afresh next time
                        word.Quit()
                    except Exception:  # noqa: BLE001
                        pass
                    word = None
                finally:
                    done.set()
        finally:
            if word is not None:
                try:
                    word.Quit()
                except Exception:  # noqa: BLE001
                    pass
            pythoncom.CoUninitialize()
            if stopped is not None:
                stopped.set()

    def quit(self, timeout: float = 15):
        if self._thread is not None and self._thread.is_alive():
            done = threading.Event()
            self._jobs.put((None, done, {}))
            done.wait(timeout)


_WORD = _WordThread()
atexit.register(_WORD.quit)


def _via_word(docx_path: str, pdf_path: str) -> None:
    try:
        import pythoncom  # noqa: F401 - only checks pywin32 is there
        import win32com.client  # noqa: F401
    except ImportError as e:
        raise PdfError("No PDF converter found: install Microsoft Word or LibreOffice.") from e

    def convert(word):
        doc = word.Documents.Open(os.path.abspath(docx_path), False, True)
        try:
            doc.ExportAsFixedFormat(os.path.abspath(pdf_path), 17)   # 17 = PDF
        finally:
            doc.Close(False)

    with _LOCK:
        try:
            _WORD.call(convert)
        except Exception as e:  # noqa: BLE001
            raise PdfError(f"Word PDF conversion failed: {e}") from e


def docx_to_pdf(docx_path: str, out_dir: str) -> str:
    """Convert docx_path to <out_dir>/<same name>.pdf and return that path."""
    pdf_path = os.path.join(out_dir, Path(docx_path).stem + ".pdf")
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    word_problem = ""
    if os.name == "nt":
        try:
            _via_word(docx_path, pdf_path)
            if os.path.exists(pdf_path):
                return pdf_path
            word_problem = "Microsoft Word ran but did not write the PDF"
        except Exception as e:  # noqa: BLE001 - fall back to LibreOffice
            word_problem = _word_problem(e)
            print(f"[PDF] {word_problem}")
    soffice = find_soffice()
    if soffice:
        _via_libreoffice(soffice, docx_path, out_dir)
        if os.path.exists(pdf_path):
            return pdf_path
        raise PdfError(f"LibreOffice ({soffice}) did not produce the PDF."
                       + (f" {word_problem}." if word_problem else ""))
    if os.name != "nt":
        raise PdfError(f"No PDF converter found: install LibreOffice ({LO_HINT}).")
    raise PdfError(f"{word_problem or 'Microsoft Word could not make the PDF'}, and LibreOffice is not "
                   f"installed. Install LibreOffice (free, {LO_HINT}) and restart the tool; DOCX export "
                   "works without it.")


LO_HINT = "https://www.libreoffice.org/download/"


def _word_problem(e: Exception) -> str:
    """Why Word could not make the PDF, in words the user can act on."""
    text = str(e)
    cause = e.__cause__ or e
    codes = {getattr(cause, "hresult", None)} | set(getattr(cause, "args", ())[:1])
    if -2147221005 in codes or "Invalid class string" in text:      # CO_E_CLASSSTRING
        return "Microsoft Word is not installed on this PC"
    if -2147221164 in codes or "Class not registered" in text:      # REGDB_E_CLASSNOTREG
        return "Microsoft Word is not set up for other programs on this PC (Office web / Store version?)"
    if "No PDF converter" in text:
        return "Microsoft Word cannot be used from this program"
    return f"Microsoft Word could not make the PDF ({text})"


def pdf_pages_png(pdf_path: str, width: int = 900) -> list[str]:
    """Each page as a base64 PNG, `width` pixels wide (for the live preview)."""
    import pypdfium2 as pdfium
    out = []
    doc = pdfium.PdfDocument(pdf_path)
    try:
        for i in range(len(doc)):
            page = doc[i]
            img = page.render(scale=width / page.get_width()).to_pil()
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            out.append(base64.b64encode(buf.getvalue()).decode("ascii"))
    finally:
        doc.close()
    return out

"""Gene-function summary fetched from NCBI's public gene database, cached locally.

The Description box of a variant starts with a paragraph on what the gene does. The
lab's reports take this, almost word for word, from the NCBI RefSeq "summary" of the
gene, so this module fetches that same text (NCBI Datasets v2, no key needed) and the
narrative builder uses it in place of the short "The GENE gene encodes ..." line.

Only the gene symbol is sent to NCBI - never any patient data. Every result is cached
in the data folder (gene_cache.json) so repeat lookups are instant and work offline;
when NCBI cannot be reached the narrative falls back to the short built line.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT = 8               # seconds per request; a slow / missing network falls back fast
_RETRY_AFTER = 600         # after a network failure, skip NCBI this long (s): no hang per lookup
_DOWN_UNTIL = 0.0          # time until which NCBI counts as unreachable
_CACHE_LOCK = threading.RLock()
_CACHE: dict | None = None     # {SYMBOL: {"function": str, "fetched": epoch}}


def _cache_path() -> str:
    from ..auth import data_dir      # late import: auth sets up the writable data folder
    return os.path.join(data_dir(), "gene_cache.json")


def _load_cache() -> dict:
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is None:
            try:
                with open(_cache_path(), encoding="utf-8") as f:
                    _CACHE = json.load(f)
                if not isinstance(_CACHE, dict):
                    _CACHE = {}
            except (OSError, ValueError):
                _CACHE = {}
        return _CACHE


def _save_cache() -> None:
    """Written to a temporary file and swapped in, so a crash mid-write cannot leave a
    broken cache behind."""
    with _CACHE_LOCK:
        path = _cache_path()
        try:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(_CACHE, f)
            os.replace(path + ".tmp", path)
        except OSError:
            pass


class NetworkDown(Exception):
    """NCBI was unreachable a moment ago: lookups are skipped until _DOWN_UNTIL."""


def _get_json(url: str) -> dict:
    """GET a JSON page. Uses the HTTPS_PROXY / HTTP_PROXY environment variables when set (a
    server behind a hospital proxy). A connection failure or timeout pauses all lookups
    for _RETRY_AFTER seconds, so a server without internet answers at once (short text)
    instead of waiting on every gene; an HTTP error from NCBI itself does not."""
    global _DOWN_UNTIL
    if time.time() < _DOWN_UNTIL:
        raise NetworkDown()
    req = urllib.request.Request(url, headers={"User-Agent": "cmc-cyto-report/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError:
        raise                       # NCBI answered (404, 429, 5xx): not a network outage
    except OSError:                 # URLError, timeout, refused / no route
        _DOWN_UNTIL = time.time() + _RETRY_AFTER
        raise


def _clean(text: str) -> str:
    """Drop the trailing '[provided by RefSeq, ...]' attribution the lab's reports omit."""
    return re.sub(r"\s*\[provided by [^\]]*\]\s*$", "", (text or "").strip()).strip()


def _summary_text(gene: dict) -> str:
    summ = gene.get("summary")
    if isinstance(summ, list):          # NCBI returns [{"description": "..."}]
        summ = summ[0] if summ else {}
    if isinstance(summ, dict):
        return _clean(summ.get("description", ""))
    if isinstance(summ, str):
        return _clean(summ)
    return ""


def gene_function(symbol: str) -> str:
    """The RefSeq functional summary for a human gene symbol, or '' when NCBI has none
    or cannot be reached. Cached: a cached value (including a cached '') skips the network.
    A network error is not cached, so it is retried next time."""
    if os.environ.get("CYTO_GENEINFO_OFFLINE"):     # tests / forced-offline: skip the network
        return ""
    symbol = (symbol or "").strip().upper()
    if not symbol or not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,30}", symbol):
        return ""
    cache = _load_cache()
    with _CACHE_LOCK:
        if symbol in cache:
            return cache[symbol].get("function", "")
    try:
        url = ("https://api.ncbi.nlm.nih.gov/datasets/v2alpha/gene/symbol/"
               f"{urllib.parse.quote(symbol)}/taxon/9606")
        data = _get_json(url)
    except Exception:       # offline, timeout, HTTP error: fall back, do not cache
        return ""
    reports = data.get("reports") or []
    text = ""
    exact = [r.get("gene") or {} for r in reports
             if (r.get("gene") or {}).get("symbol", "").upper() == symbol]
    for gene in (exact or [r.get("gene") or {} for r in reports]):
        text = _summary_text(gene)
        if text:
            break
    with _CACHE_LOCK:
        cache[symbol] = {"function": text, "fetched": int(time.time())}
        _save_cache()
    return text


# ---------------------------------------------------------------------------
# Disease clinical description: the "X is characterized by ..." paragraph, taken
# from NCBI MedGen by the disease's OMIM phenotype number (precise), cached too.
# ---------------------------------------------------------------------------

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _cap_sentences(text: str, max_chars: int = 700) -> str:
    """Keep whole sentences up to about max_chars, so a long GeneReviews definition
    becomes a report-sized paragraph the curator can trim further."""
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return (cut[:end + 1] if end > 120 else cut.rstrip()).strip()


def disease_description(omim: str) -> str:
    """The MedGen clinical description for a disease's OMIM phenotype number, or ''
    when none / offline. Cached (key 'MIM:<n>'), including a cached ''."""
    if os.environ.get("CYTO_GENEINFO_OFFLINE"):
        return ""
    omim = (omim or "").strip()
    if not omim.isdigit():
        return ""
    key = f"MIM:{omim}"
    cache = _load_cache()
    with _CACHE_LOCK:
        if key in cache:
            return cache[key].get("disease", "")
    try:
        es = _get_json(f"{_EUTILS}/esearch.fcgi?db=medgen&term={omim}%5BMIM%5D&retmode=json")
        ids = (es.get("esearchresult") or {}).get("idlist") or []
        text = ""
        if ids:
            su = _get_json(f"{_EUTILS}/esummary.fcgi?db=medgen&id={ids[0]}&retmode=json")
            u = (su.get("result") or {}).get(ids[0], {})
            defn = u.get("definition")
            raw = defn.get("value") if isinstance(defn, dict) else defn
            text = _cap_sentences(_clean(raw or ""))
    except Exception:       # offline / HTTP error: fall back, do not cache
        return ""
    with _CACHE_LOCK:
        cache[key] = {"disease": text, "fetched": int(time.time())}
        _save_cache()
    return text

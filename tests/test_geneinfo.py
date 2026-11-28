"""NCBI lookups (backend/core/geneinfo.py) without the network: a network failure must not
make every later lookup wait again, and the cache file is written whole.

Run:  python -m unittest discover -s tests -v
"""
import json
import os
import unittest
import urllib.error
from unittest import mock

import helpers  # noqa: F401  (test data folder; also turns the lookups off by default)

from backend.core import geneinfo


class GeneinfoTests(unittest.TestCase):
    def setUp(self):
        self._offline = os.environ.pop("CYTO_GENEINFO_OFFLINE", None)   # this test calls the code
        geneinfo._CACHE, geneinfo._DOWN_UNTIL = None, 0.0
        try:
            os.remove(geneinfo._cache_path())
        except OSError:
            pass

    def tearDown(self):
        if self._offline is not None:
            os.environ["CYTO_GENEINFO_OFFLINE"] = self._offline
        geneinfo._CACHE, geneinfo._DOWN_UNTIL = None, 0.0

    def test_network_down_pauses_lookups(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")) as up:
            self.assertEqual(geneinfo.gene_function("ATM"), "")
            self.assertEqual(geneinfo.gene_function("COLQ"), "")
            self.assertEqual(geneinfo.disease_description("208900"), "")
        self.assertEqual(up.call_count, 1)          # only the first lookup tried the network
        self.assertNotIn("ATM", geneinfo._load_cache())     # a failure is not remembered as "none"

    def test_http_error_does_not_pause(self):
        err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err) as up:
            geneinfo.gene_function("ATM")
            geneinfo.gene_function("COLQ")
        self.assertEqual(up.call_count, 2)

    def test_found_text_is_cached_to_file(self):
        body = json.dumps({"reports": [{"gene": {"symbol": "ATM", "summary": [
            {"description": "Kinase text. [provided by RefSeq, Aug 2010]"}]}}]}).encode()
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = body
        with mock.patch("urllib.request.urlopen", return_value=resp):
            self.assertEqual(geneinfo.gene_function("ATM"), "Kinase text.")
        with open(geneinfo._cache_path(), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["ATM"]["function"], "Kinase text.")
        self.assertFalse(os.path.exists(geneinfo._cache_path() + ".tmp"))


if __name__ == "__main__":
    unittest.main()

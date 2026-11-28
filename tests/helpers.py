"""Test setup shared by the test modules: user accounts in a throw-away folder (never the
real instance/ one) and a Flask test client signed in as a test user."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["CYTO_DATA_DIR"] = tempfile.mkdtemp(prefix="cyto_test_data_")
# Keep the built narrative deterministic and network-free: the NCBI gene-function
# lookup (backend/core/geneinfo.py) is skipped, so description() falls back to its
# short built line, which the tests assert on.
os.environ.setdefault("CYTO_GENEINFO_OFFLINE", "1")

TEST_USER, TEST_PASSWORD = "tester", "test-password-1"


def signed_in_client():
    from backend import auth
    from backend.server import app

    app.config["TESTING"] = True
    if TEST_USER not in auth.load_users():
        auth.create_user(TEST_USER, TEST_PASSWORD, admin=True)
    c = app.test_client()
    c.get("/login")
    with c.session_transaction() as s:
        token = s["csrf"]
    r = c.post("/login", data={"username": TEST_USER, "password": TEST_PASSWORD, "csrf": token})
    assert r.status_code == 302, r.status_code
    return c

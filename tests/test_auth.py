"""Sign-in: pages and API need a user, first-start setup, admin rules, sign-in ending.

Run:  python -m unittest discover -s tests -v
Accounts live in a throw-away folder (tests/helpers.py), never in instance/.
"""
import os
import shutil
import tempfile
import time
import unittest

from helpers import TEST_PASSWORD, TEST_USER, signed_in_client

from backend import auth  # noqa: E402
from backend.server import app  # noqa: E402


def _csrf(c, page="/login"):
    c.get(page)
    with c.session_transaction() as s:
        return s["csrf"]


class EmptyStoreTests(unittest.TestCase):
    """A fresh install (no users yet) in a folder of its own."""

    def setUp(self):
        self.saved = os.environ["CYTO_DATA_DIR"]
        self.dir = tempfile.mkdtemp(prefix="cyto_test_empty_")
        os.environ["CYTO_DATA_DIR"] = self.dir

    def tearDown(self):
        os.environ["CYTO_DATA_DIR"] = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_first_start_asks_for_admin(self):
        c = app.test_client()
        r = c.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/setup"))
        token = _csrf(c, "/setup")
        r = c.post("/setup", data={"username": "Boss", "password": "longenough1",
                                   "confirm": "longenough1", "csrf": token})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(auth.load_users()["boss"]["admin"])
        self.assertEqual(c.get("/").status_code, 200)          # signed in straight away
        self.assertEqual(c.get("/setup").status_code, 302)     # setup only once
        with open(os.path.join(self.dir, "users.json"), encoding="utf-8") as f:
            self.assertNotIn("longenough1", f.read())          # only the hash is stored

    def test_web_version_has_no_setup_page(self):
        os.environ["CYTO_DISABLE_SETUP"] = "1"
        try:
            c = app.test_client()
            self.assertEqual(c.get("/setup").status_code, 503)
            r = c.post("/setup", data={"username": "intruder", "password": "longenough1",
                                       "confirm": "longenough1", "csrf": "x"})
            self.assertEqual(r.status_code, 503)
            self.assertEqual(auth.load_users(), {})
        finally:
            del os.environ["CYTO_DISABLE_SETUP"]

    def test_health_check_needs_no_sign_in(self):
        r = app.test_client().get("/healthz")
        self.assertEqual((r.status_code, r.data), (200, b"ok"))


class AuthTests(unittest.TestCase):
    def setUp(self):
        signed_in_client()          # makes sure the test admin exists

    def test_signed_out_is_refused(self):
        c = app.test_client()
        r = c.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])
        r = c.post("/api/defaults", json={"data": {}})
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.get_json()["signed_out"])
        r = c.get("/static/css/style.css")          # the sign-in page's css
        self.assertEqual(r.status_code, 200)
        r.close()

    def test_wrong_password_and_lockout(self):
        c = app.test_client()
        token = _csrf(c)
        for _ in range(auth.MAX_FAILURES):
            r = c.post("/login", data={"username": "nobody", "password": "x" * 9, "csrf": token})
            self.assertIn(b"Wrong user name or password", r.data)
        r = c.post("/login", data={"username": "nobody", "password": "x" * 9, "csrf": token})
        self.assertIn(b"Too many failed attempts", r.data)

    def test_login_needs_form_token(self):
        c = app.test_client()
        r = c.post("/login", data={"username": TEST_USER, "password": TEST_PASSWORD})
        self.assertEqual(r.status_code, 400)

    def test_next_stays_on_this_site(self):
        c = app.test_client()
        token = _csrf(c)
        r = c.post("/login", data={"username": TEST_USER, "password": TEST_PASSWORD, "csrf": token,
                                   "next": "https://evil.example/"})
        self.assertEqual(r.headers["Location"], "/")

    def test_sign_in_ends_after_hours(self):
        c = signed_in_client()
        with c.session_transaction() as s:
            s["since"] = time.time() - auth.SESSION_HOURS * 3600 - 1
        self.assertEqual(c.post("/api/defaults", json={"data": {}}).status_code, 401)

    def test_password_reset_ends_other_sign_ins(self):
        auth.create_user("temp1", "first-pass-1") if "temp1" not in auth.load_users() else None
        c = app.test_client()
        token = _csrf(c)
        c.post("/login", data={"username": "temp1", "password": "first-pass-1", "csrf": token})
        self.assertEqual(c.get("/").status_code, 200)
        auth.set_password("temp1", "second-pass-2")
        self.assertEqual(c.get("/").status_code, 302)
        auth.delete_user("temp1")

    def test_admin_page_rules(self):
        admin = signed_in_client()
        token = _csrf(admin, "/admin")
        r = admin.post("/admin", data={"csrf": token, "action": "add", "name": "Clerk",
                                       "password": "clerk-pass-1"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(auth.load_users()["clerk"]["admin"])
        r = admin.post("/admin", data={"csrf": token, "action": "delete", "name": TEST_USER})
        self.assertIn(b"cannot remove your own account", r.data)
        r = admin.post("/admin", data={"csrf": token, "action": "add", "name": "x",
                                       "password": "clerk-pass-1"})
        self.assertIn(b"2-32 characters", r.data)

        clerk = app.test_client()       # not an admin: no user page
        t2 = _csrf(clerk)
        clerk.post("/login", data={"username": "clerk", "password": "clerk-pass-1", "csrf": t2})
        self.assertEqual(clerk.get("/").status_code, 200)
        self.assertEqual(clerk.get("/admin").status_code, 403)
        self.assertNotIn(b">Users</a>", clerk.get("/").data)

        admin.post("/admin", data={"csrf": token, "action": "delete", "name": "clerk"})
        self.assertNotIn("clerk", auth.load_users())
        self.assertEqual(clerk.get("/").status_code, 302)       # removed user is signed out

    def test_last_admin_kept(self):
        users = auth.load_users()
        others = [n for n, u in users.items() if u.get("admin") and n != TEST_USER]
        if others:
            self.skipTest("other admins present")
        with self.assertRaises(auth.AuthError):
            auth.set_admin(TEST_USER, False)

    def test_new_tab_must_sign_in(self):
        """Only the page right after signing in is 'fresh' (that tab is let in by
        js/tab.js); the cookie ends with the browser."""
        c = app.test_client()
        token = _csrf(c)
        r = c.post("/login", data={"username": TEST_USER, "password": TEST_PASSWORD, "csrf": token})
        self.assertNotIn("Expires=", r.headers.get("Set-Cookie", ""))     # browser-session cookie
        self.assertIn(b'data-fresh="1"', c.get("/").data)
        self.assertIn(b'data-fresh="0"', c.get("/").data)                  # a later / new-tab load
        self.assertIn(b"js/tab.js", c.get("/").data)

    def test_only_admins_set_passwords(self):
        """A user cannot change their own password (no menu item, page refused)."""
        auth.create_user("plain1", "plain-pass-1") if "plain1" not in auth.load_users() else None
        c = app.test_client()
        token = _csrf(c)
        c.post("/login", data={"username": "plain1", "password": "plain-pass-1", "csrf": token})
        self.assertNotIn(b"Change password", c.get("/").data)
        self.assertEqual(c.get("/account").status_code, 403)
        r = c.post("/account", data={"csrf": token, "current": "plain-pass-1",
                                     "password": "new-pass-222", "confirm": "new-pass-222"})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(auth.verify("plain1", "plain-pass-1"))      # unchanged
        auth.delete_user("plain1")

    def test_admin_changes_own_password(self):
        auth.create_user("self1", "old-pass-111", admin=True) if "self1" not in auth.load_users() else None
        c = app.test_client()
        token = _csrf(c)
        c.post("/login", data={"username": "self1", "password": "old-pass-111", "csrf": token})
        self.assertIn(b"Change password", c.get("/").data)
        token = _csrf(c, "/account")
        r = c.post("/account", data={"csrf": token, "current": "wrong", "password": "new-pass-222",
                                     "confirm": "new-pass-222"})
        self.assertIn(b"current password is wrong", r.data)
        r = c.post("/account", data={"csrf": token, "current": "old-pass-111",
                                     "password": "new-pass-222", "confirm": "new-pass-222"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get("/").status_code, 200)       # still signed in here
        self.assertTrue(auth.verify("self1", "new-pass-222"))
        auth.delete_user("self1")


if __name__ == "__main__":
    unittest.main()

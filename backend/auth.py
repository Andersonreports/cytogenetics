"""Sign-in for the tool: one account per person, kept in users.json in the data folder.

Every page and API call needs a signed-in user (the computer running the tool too).
The first start asks for the admin account (/setup); admins add / remove users and reset
passwords on /admin; everyone can change their own password on /account. A sign-in lasts
SESSION_HOURS from login.

Passwords are stored only as salted hashes (werkzeug). The data folder (users.json and the
key that signs the session cookie) is `instance/` in the project, or `cyto_data/` next to
the exe; CYTO_DATA_DIR overrides it. It is never bundled or committed.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

SESSION_HOURS = 5
MIN_PASSWORD = 8
USERNAME_RE = re.compile(r"^[a-z0-9._-]{2,32}$")
# Failed sign-ins: this many within LOCK_SECONDS for one name from one address -> wait.
MAX_FAILURES = 5
LOCK_SECONDS = 10 * 60

bp = Blueprint("auth", __name__)
_lock = threading.Lock()
_failures: dict[tuple[str, str], list[float]] = {}
# A hash to check against when the name is unknown, so both cases take the same time.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def data_dir() -> str:
    """The writable folder for users.json and the cookie key (created on first use)."""
    path = os.environ.get("CYTO_DATA_DIR")
    if not path:
        if getattr(sys, "frozen", False):
            path = os.path.join(os.path.dirname(sys.executable), "cyto_data")
        else:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "instance")
    os.makedirs(path, exist_ok=True)
    return os.path.abspath(path)


def _users_file() -> str:
    return os.path.join(data_dir(), "users.json")


def load_users() -> dict:
    try:
        with open(_users_file(), encoding="utf-8") as f:
            return json.load(f).get("users", {})
    except FileNotFoundError:
        return {}


def _save_users(users: dict) -> None:
    path = _users_file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"users": users}, f, indent=1)
    os.replace(tmp, path)


def secret_key() -> bytes:
    """The key that signs session cookies, kept so sign-ins survive a restart."""
    path = os.path.join(data_dir(), "secret_key")
    with _lock:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(secrets.token_hex(32))
        with open(path, encoding="utf-8") as f:
            return f.read().strip().encode()


class AuthError(ValueError):
    """A user-facing reason an account change was refused."""


def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"The password must be at least {MIN_PASSWORD} characters.")


def clean_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not USERNAME_RE.match(name):
        raise AuthError("User names are 2-32 characters: letters, digits, '.', '_' or '-'.")
    return name


def create_user(name: str, password: str, admin: bool = False) -> str:
    name = clean_name(name)
    _check_password(password)
    with _lock:
        users = load_users()
        if name in users:
            raise AuthError(f"There is already a user '{name}'.")
        users[name] = {"hash": generate_password_hash(password), "admin": bool(admin),
                       "created": datetime.now().strftime("%d/%m/%Y %H:%M")}
        _save_users(users)
    return name


def set_password(name: str, password: str) -> None:
    _check_password(password)
    with _lock:
        users = load_users()
        if name not in users:
            raise AuthError(f"No user '{name}'.")
        users[name]["hash"] = generate_password_hash(password)
        _save_users(users)


def _admins(users: dict) -> list[str]:
    return [n for n, u in users.items() if u.get("admin")]


def set_admin(name: str, admin: bool) -> None:
    with _lock:
        users = load_users()
        if name not in users:
            raise AuthError(f"No user '{name}'.")
        if not admin and _admins(users) == [name]:
            raise AuthError("There must be at least one admin.")
        users[name]["admin"] = bool(admin)
        _save_users(users)


def delete_user(name: str) -> None:
    with _lock:
        users = load_users()
        if name not in users:
            raise AuthError(f"No user '{name}'.")
        if _admins(users) == [name]:
            raise AuthError("The last admin cannot be removed.")
        del users[name]
        _save_users(users)


def verify(name: str, password: str) -> bool:
    user = load_users().get((name or "").strip().lower())
    ok = check_password_hash(user["hash"] if user else _DUMMY_HASH, password or "")
    return bool(user) and ok


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
def _stamp(user: dict) -> str:
    """Part of the password hash: a password change / reset ends that user's sign-ins."""
    return user["hash"][-16:]


def current_user() -> str | None:
    """The signed-in user's name, or None (no sign-in, expired, removed, password changed)."""
    name = session.get("user")
    if not name:
        return None
    user = load_users().get(name)
    if (user is None or session.get("stamp") != _stamp(user)
            or time.time() - session.get("since", 0) > SESSION_HOURS * 3600):
        session.clear()
        return None
    g.is_admin = bool(user.get("admin"))
    return name


def _sign_in(name: str) -> None:
    session.clear()
    session.permanent = True
    session["user"] = name
    session["stamp"] = _stamp(load_users()[name])
    session["since"] = time.time()
    session["csrf"] = secrets.token_hex(16)


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def _check_csrf() -> None:
    sent = request.form.get("csrf", "")
    if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
        abort(400, "The form expired; reload the page and try again.")


def _safe_next(target: str | None) -> str:
    """Only a path on this site (no other host) after signing in."""
    if target:
        u = urlparse(target)
        if not u.scheme and not u.netloc and target.startswith("/") and not target.startswith("//"):
            return target
    return url_for("index")


def _throttled(key: tuple[str, str]) -> bool:
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(key, []) if now - t < LOCK_SECONDS]
        _failures[key] = recent
        return len(recent) >= MAX_FAILURES


def _failed(key: tuple[str, str]) -> None:
    with _lock:
        _failures.setdefault(key, []).append(time.time())


def admin_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not g.get("is_admin"):
            abort(403)
        return view(*a, **kw)
    return wrapper


OPEN_ENDPOINTS = {"auth.login", "auth.setup", "static", "auth.healthz"}


def _env_on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def init_app(app) -> None:
    app.secret_key = secret_key()
    app.config.update(
        SESSION_COOKIE_NAME="cyto_session",     # not 'session': other local tools share the host
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Web version behind HTTPS: the cookie is never sent over plain http.
        SESSION_COOKIE_SECURE=_env_on("CYTO_HTTPS"),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_HOURS),
        SESSION_REFRESH_EACH_REQUEST=False,     # 5 hours from sign-in, not from last click
    )
    if _env_on("CYTO_BEHIND_PROXY"):
        # Behind one reverse proxy (nginx): the user's address and https come from its
        # X-Forwarded-* headers (sign-in throttling, redirects).
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.register_blueprint(bp)

    @app.before_request
    def _require_sign_in():
        g.user = current_user()
        if request.endpoint in OPEN_ENDPOINTS or g.user:
            return None
        if not load_users():
            return redirect(url_for("auth.setup"))
        if request.path.startswith("/api/"):
            return jsonify({"error": "Signed out: sign in again.", "signed_out": True}), 401
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    @app.after_request
    def _no_cache(resp):
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if app.config["SESSION_COOKIE_SECURE"]:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@bp.route("/healthz")
def healthz():
    """For the server's health check (Docker / load balancer): no sign-in, no data."""
    return "ok", 200, {"Content-Type": "text/plain"}


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    """First start only: create the admin account. Off in the web version
    (CYTO_DISABLE_SETUP): there the first admin is made on the server's command line, so
    nobody who finds the address first can take the account."""
    if load_users():
        return redirect(url_for("auth.login"))
    if _env_on("CYTO_DISABLE_SETUP"):
        return render_template("auth/no_setup.html"), 503
    error = None
    if request.method == "POST":
        _check_csrf()
        f = request.form
        try:
            if f.get("password") != f.get("confirm"):
                raise AuthError("The two passwords are not the same.")
            name = create_user(f.get("username", ""), f.get("password", ""), admin=True)
            _sign_in(name)
            return redirect(url_for("index"))
        except AuthError as e:
            error = str(e)
    return render_template("auth/setup.html", error=error)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not load_users():
        return redirect(url_for("auth.setup"))
    nxt = request.values.get("next")
    if request.method == "GET" and current_user():
        return redirect(_safe_next(nxt))
    error = None
    if request.method == "POST":
        _check_csrf()
        name = request.form.get("username", "").strip().lower()
        key = (request.remote_addr or "", name)
        if _throttled(key):
            error = f"Too many failed attempts. Try again in {LOCK_SECONDS // 60} minutes."
        elif verify(name, request.form.get("password", "")):
            with _lock:
                _failures.pop(key, None)
            _sign_in(name)
            return redirect(_safe_next(nxt))
        else:
            _failed(key)
            error = "Wrong user name or password."
    return render_template("auth/login.html", error=error, next=nxt or "",
                           expired=request.args.get("expired"))


@bp.route("/logout", methods=["POST"])
def logout():
    _check_csrf()
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
def account():
    error = None
    if request.method == "POST":
        _check_csrf()
        f = request.form
        try:
            if not verify(g.user, f.get("current", "")):
                raise AuthError("The current password is wrong.")
            if f.get("password") != f.get("confirm"):
                raise AuthError("The two new passwords are not the same.")
            set_password(g.user, f.get("password", ""))
            _sign_in(g.user)            # stays signed in here; other sign-ins end
            flash("Your password was changed.")
            return redirect(url_for("auth.account"))
        except AuthError as e:
            error = str(e)
    return render_template("auth/account.html", error=error)


@bp.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    error = None
    if request.method == "POST":
        _check_csrf()
        f, action, name = request.form, request.form.get("action"), request.form.get("name", "")
        try:
            if action == "add":
                name = create_user(name, f.get("password", ""), admin=bool(f.get("admin")))
                flash(f"User '{name}' added. Give them the password; they can change it under 'Password'.")
            elif action == "reset":
                set_password(name, f.get("password", ""))
                if name == g.user:
                    _sign_in(name)
                flash(f"Password of '{name}' changed.")
            elif action in ("make_admin", "remove_admin"):
                set_admin(name, action == "make_admin")
                flash(f"'{name}' is {'now' if action == 'make_admin' else 'no longer'} an admin.")
            elif action == "delete":
                if name == g.user:
                    raise AuthError("You cannot remove your own account.")
                delete_user(name)
                flash(f"User '{name}' removed.")
            else:
                abort(400)
            return redirect(url_for("auth.admin"))
        except AuthError as e:
            error = str(e)
    users = sorted(load_users().items())
    return render_template("auth/admin.html", users=users, error=error, min_password=MIN_PASSWORD)

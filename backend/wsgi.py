"""The web version's entry point for a production WSGI server (gunicorn), e.g.

    gunicorn --workers 1 --threads 8 --timeout 180 --bind 0.0.0.0:8000 backend.wsgi:app

One worker process on purpose: the user accounts file and the sign-in throttling are
guarded per process; threads serve several users at once. See DEPLOY.md.
"""
from backend.server import app  # noqa: F401

# The web version of the CMC Cytogenetics report tool (see DEPLOY.md).
#   docker compose up -d --build
# PDFs and the live preview are made with LibreOffice inside the image. The report
# template's Times New Roman / Arial / Courier New are matched by the Liberation fonts
# (same widths, so the same line and page breaks); build with --build-arg MS_FONTS=1 to
# install Microsoft's own core fonts instead (downloaded at build time, accepts their EULA).
FROM python:3.12-slim-bookworm

ARG MS_FONTS=0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CYTO_DATA_DIR=/data \
    CYTO_DISABLE_SETUP=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends libreoffice-writer-nogui fonts-liberation fonts-dejavu-core \
 && if [ "$MS_FONTS" = "1" ]; then \
      sed -i 's/^Components: main$/Components: main contrib/' /etc/apt/sources.list.d/debian.sources \
      && apt-get update \
      && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections \
      && apt-get install -y --no-install-recommends ttf-mscorefonts-installer; \
    fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY backend ./backend
COPY frontend ./frontend
# Only the blank template: assets/ may hold patient reports.
COPY assets/cmc_cytogenetics.docx ./assets/cmc_cytogenetics.docx

# /data: user accounts + cookie key (a volume). /app/database: the licensed OMIM tables,
# mounted read-only from the server, never built into the image.
RUN useradd --system --uid 10001 --home-dir /tmp cyto \
 && mkdir -p /data /app/database \
 && chown cyto /data
USER cyto

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
# One worker process (accounts file + sign-in throttling are per process), 8 threads.
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--timeout", "180", \
     "--bind", "0.0.0.0:8000", "--access-logfile", "-", "backend.wsgi:app"]

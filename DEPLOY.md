# Deploying the web version

The CMC Cytogenetics report tool as a web application on a Linux server: staff open
it at an address such as `https://cyto-reports.example.org`, sign in, and make the
report in the browser. Nothing is installed on their computers.

The desktop version (the `.exe` and `run.bat`, see README.md) keeps working as before;
both run the same code.

## What runs

```
browser --HTTPS--> nginx (on the server, port 443) --> Docker container (127.0.0.1:8000)
                                                         gunicorn + the Flask app
                                                         LibreOffice (PDF + preview)
```

| Piece | Where |
|---|---|
| `Dockerfile` | the image: Python 3.12, LibreOffice Writer, fonts, the app, gunicorn |
| `docker-compose.yml` | runs it: port 8000 on localhost only, the data volume, the OMIM folder |
| `deploy/nginx.conf` | HTTPS in front of it |
| `requirements-web.txt` | Python packages (the app's + gunicorn) |
| `backend/wsgi.py` | gunicorn's entry point (`backend.wsgi:app`) |

## Requirements

- A Linux server (Ubuntu 22.04/24.04 or similar) with Docker Engine and the Compose
  plugin, and nginx.
- 2 CPU cores and 2 GB RAM are enough for a lab's staff. LibreOffice makes each PDF and
  preview page; conversions run one at a time (about 1-3 s each).
- A DNS name and a TLS certificate for it (certbot / Let's Encrypt, or the hospital's).
- Outbound internet is needed only while building the image.

## Install

```bash
git clone https://github.com/Andersonreports/cytogenetics_report_automation.git
cd cytogenetics_report_automation
docker compose up -d --build
curl http://127.0.0.1:8000/healthz        # -> ok
```

To use Microsoft's own Times New Roman / Arial instead of the metric-compatible
Liberation fonts (accepts Microsoft's core-fonts EULA, downloaded at build time):
`docker compose build --build-arg MS_FONTS=1 && docker compose up -d`.

### Create the first admin

The web version has no first-start page: anyone who found the address first could
otherwise create the admin account. Create it on the server:

```bash
docker compose exec cyto python -m backend.main --reset-password admin
```

It asks for the password twice. That admin then signs in and adds the other users
(name menu at the top right > *Users*). The same command later resets a password when
no admin can sign in.

### HTTPS with nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/cyto-report
sudo nano /etc/nginx/sites-available/cyto-report      # server_name + certificate paths
sudo ln -s /etc/nginx/sites-available/cyto-report /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

The container listens on 127.0.0.1 only; nginx is the only way in. Allow ports 80 and
443 in the firewall (or only from the hospital network / VPN if it should not be
reachable from the internet).

**Plain http (testing only):** set `CYTO_HTTPS: "0"` in `docker-compose.yml`, otherwise
the browser never sends the sign-in cookie back over http and sign-in seems to do
nothing. Never use plain http with patient data.

## OMIM tables (optional)

The OMIM files are licensed and are never built into the image. Put
`omim_genemap2.txt` and `omim_mim2gene.txt` in `database/` next to
`docker-compose.yml` (mounted read-only into the container) and restart:
`docker compose restart`. Without them the tool works, but does not suggest OMIM
numbers / diseases.

## Data, privacy and backups

- **Stored on the server**: only the `cyto_data` volume: `users.json` (user names,
  salted password hashes, admin flag) and `secret_key` (signs the sign-in cookie).
  Back it up: `docker compose cp cyto:/data ./cyto_data_backup` (restore: copy the two
  files back with `docker compose cp ./cyto_data_backup/. cyto:/data` and restart).
- **Patient data is not stored on the server.** The uploaded Excel, the previews and
  the exported files are made in temporary folders and deleted (exports a minute after
  the download). The unfinished report is kept in each user's own browser, per user.
- The access log (`docker compose logs`) has addresses and paths, no patient data.
- If `secret_key` leaks, delete it and restart: a new one is made and everyone signs
  in again.

## Settings

Environment variables (in `docker-compose.yml`):

| Variable | Default in the image | Meaning |
|---|---|---|
| `CYTO_HTTPS` | `1` (compose) | sign-in cookie only over HTTPS; adds HSTS |
| `CYTO_BEHIND_PROXY` | `1` (compose) | trust one proxy's `X-Forwarded-For/Proto/Host` |
| `CYTO_DISABLE_SETUP` | `1` | no first-start page (admin made on the command line) |
| `CYTO_DATA_DIR` | `/data` | where accounts and the cookie key are kept |

Sign-in lasts 5 hours; five wrong passwords for one name block it from that address
for 10 minutes. gunicorn runs **one worker with 8 threads** on purpose: the accounts
file and the sign-in throttling are kept per process. Do not raise `--workers`.

## Update

```bash
git pull
docker compose up -d --build
```

Accounts survive (they are in the volume). Users who are signed in keep their
sign-in.

## Troubleshooting

| Symptom | Check |
|---|---|
| Sign-in page comes back after signing in | served over plain http with `CYTO_HTTPS=1`; use HTTPS (or `0` for a test) |
| "Not set up yet" page | no admin yet: see *Create the first admin* |
| Preview / PDF fails | `docker compose logs cyto`; LibreOffice is in the image, so usually memory (raise RAM) or a timeout under heavy load |
| 413 on Excel upload | nginx `client_max_body_size` (50m in `deploy/nginx.conf`) |
| 502 from nginx | container down: `docker compose ps`, `docker compose logs cyto` |

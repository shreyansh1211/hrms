# Go-live checklist: hrms.infisetu.in + itm.infisetu.in (one VPS)

```
internet :443 -> Caddy (host) -> 127.0.0.1:8000  Django/gunicorn (Docker, host network)   hrms.infisetu.in
                              -> 127.0.0.1:8100  Infi Time Manager (systemd)               itm.infisetu.in
Django scheduler --http://127.0.0.1:8100/api/v1--> tracker   (loopback only, bearer key)
PostgreSQL / Redis: Docker, published on 127.0.0.1 only
```

None of this has been run on a real server yet: Docker was not available for a full build here
(the compose file was validated with `docker compose config` only). Expect to fix small things on the
first run, and do the whole thing on the real VPS before inviting staff.

## 1. DNS (do first, propagation takes time)
- [ ] `A  hrms.infisetu.in -> <VPS IPv4>`
- [ ] `A  itm.infisetu.in  -> <VPS IPv4>`
- [ ] `nslookup` for both shows the VPS IP (HTTPS certificates fail until it does)

## 2. VPS
- [ ] Ubuntu 22.04/24.04, 2 vCPU / 4 GB, SSH key login, non-root sudo user
- [ ] Copy the HRMS project to `/opt/infisetu-mis` (exclude `.venv`, `.env`, `*.sqlite3`, `media/`)
- [ ] `sudo bash deploy/setup-vps.sh` (Docker, Caddy, swap, firewall 22/80/443)

## 3. HRMS configuration
- [ ] `cp .env.production.example .env && chmod 600 .env`
- [ ] Replace every `CHANGE_ME` (SECRET_KEY, DB_INIT_PASSWORD, DB and Redis passwords; keep the
      password inside `DATABASE_URL` / `REDIS_URL` identical to `POSTGRES_PASSWORD` / `REDIS_PASSWORD`)
- [ ] Leave `ACTIVITY_TRACKER_API_KEY` for step 6

## 4. Start the HRMS
- [ ] `docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d`
- [ ] `docker compose ... ps` shows web healthy, scheduler running (exactly one)
- [ ] `curl -I http://127.0.0.1:8000/health/` answers
- [ ] `docker compose ... exec web python manage.py createhorillauser --first_name Mayur --last_name <surname> --username <you> --password '<strong>' --email <your email> --phone <number>`
      (or use the first-run page and the `DB_INIT_PASSWORD`)
- [ ] `docker compose ... exec web python manage.py seed_infisetu_setup`  (shifts, holidays, leave types, templates)
- [ ] `docker compose ... exec web python manage.py setup_infisetu_theme`  (logo + colours)
- [ ] `docker compose ... exec web python manage.py seed_it_assets`  (asset categories)

## 5. Tracker (Infi Time Manager)
Copy the tracker project to the VPS and unpack it (see its `docs/DEPLOYMENT.md`), then:
- [ ] `sudo PROXY=none DOMAIN=itm.infisetu.in TZ_NAME=Asia/Kolkata bash deploy/install.sh`
      (`PROXY=none` because the shared Caddy below serves both sites)
- [ ] **Save `INFITIME_MASTER_KEY` offline** (password manager). Lost key = every PC must re-enrol.
- [ ] `sudo itm-admin enable-2fa`
- [ ] Keep `/etc/itm/itm.env` as installed: `ITM_HOST=127.0.0.1`, `INFITIME_API_ALLOW_REMOTE=0`

## 6. HTTPS front door
- [ ] `sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy`
- [ ] `https://hrms.infisetu.in/` shows the login page with a valid certificate
- [ ] `https://itm.infisetu.in/healthz` is OK; `https://itm.infisetu.in/api/v1/active-time` returns 404 (internal only)
- [ ] Optional: uncomment the office/VPN IP allow-lists in the Caddyfile (HRMS and tracker console)

## 7. Connect HRMS to the tracker
- [ ] Tracker console -> Settings -> create API key -> put it in `.env` as `ACTIVITY_TRACKER_API_KEY`
- [ ] `docker compose ... up -d` (recreates web + scheduler with the key)
- [ ] HRMS -> Attendance -> Team Time -> "Sync from tracker now" runs without an error banner
- [ ] Each employee in the tracker has `external_id` = their HRMS Badge ID (or their work email)

## 8. Email (required: auto sign-out, intimations, leave and payroll mails)
- [ ] HRMS -> Settings -> Email: add the SMTP server and send a test mail
      (Microsoft 365 later: `smtp.office365.com`, port 587, STARTTLS, a dedicated mailbox)
- [ ] Trigger one real mail (e.g. a leave request) and confirm it arrives, not in spam
- [ ] SPF/DKIM for `infisetu.in` configured at the mail provider

## 9. Clean the sample data before real staff
- [ ] Delete employees Aarav and Diya, payslips batch `VERIFY-2026-09`
- [ ] Delete recruitments "Full Stack Developer - Hiring" and "UI UX Developer - Hiring"
- [ ] Create real employees (onboarding) and assign shifts

## 10. PDF payslips
- [ ] Download one payslip PDF on the server (the image installs wkhtmltopdf; this has not been run yet)

## 11. Pilot on one laptop
- [ ] Tracker console: add the employee, create an enrolment code
- [ ] Install the agent exe on one laptop (`Install-Agent.ps1`), enrol, work 15 minutes
- [ ] Console shows activity; HRMS "My Time" shows In / Active / Project times after the next sync
- [ ] SmartScreen/antivirus warnings are expected until the exe is code-signed

## 12. Backups and restore (before go-live)
- [ ] Cron (root): `30 2 * * * cd /opt/infisetu-mis && bash deploy/backup-hrms.sh >> /var/log/hrms-backup.log 2>&1`
- [ ] Tracker backups: installed by `install.sh` (`/var/backups/itm`)
- [ ] Copy `/var/backups/hrms` and `/var/backups/itm` off the server nightly
- [ ] Restore the HRMS dump into a scratch database once to prove it works

## 13. Microsoft sign-in (when the tenant exists)
- [ ] Follow `microsoft_sso/README.md`; Redirect URI: `https://hrms.infisetu.in/sso/callback/`
- [ ] Set `SSO_ENABLED=True` and the three `ENTRA_*` values in `.env`, `SSO_DEV_MOCK=False`, restart

## After every release
```
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d   # migrate + collectstatic run on start
docker compose ... exec web python manage.py seed_email_templates               # only adds missing templates
```

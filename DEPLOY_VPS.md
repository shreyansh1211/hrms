# Running Infisetu MIS on one small VPS

Target: **2 vCPU, 4 GB RAM, 40 GB+ SSD, 1 TB transfer** hosting the HRMS *and* the
Infi Time Manager (activity tracker). This is enough for roughly 50-150 staff.
**2 GB RAM is not enough** (see the budget below); 4 GB leaves about 1.5 GB of headroom.

## Memory budget (measured / typical)

| Service | RAM |
|---|---|
| Gunicorn, 2 workers x ~260 MB (spaCy now loads only when a resume is parsed) | ~0.55 GB |
| Scheduler (`run_scheduler`) | ~0.25 GB |
| PostgreSQL (shared_buffers 512 MB) | ~0.6 GB |
| Redis (cache, 128 MB cap) | ~0.1 GB |
| Infi Time Manager (uvicorn + SQLite) | ~0.15 GB |
| nginx / Caddy, OS | ~0.4 GB |
| **Total** | **~2.1 GB** of 4 GB |

Add a 2 GB swap file as a safety net. Resume parsing briefly adds ~200 MB in one worker.

## Layout

```
internet --443--> nginx/Caddy --> gunicorn :8000        (HRMS,  hrms.infisetu.in)
                              --> uvicorn  :8100        (Infi Time Manager, itm.infisetu.in)
HRMS scheduler  (python manage.py run_scheduler)  - exactly ONE copy
HRMS --http://127.0.0.1:8100/api/v1--> tracker (totals only, bearer key, local only)
```

* The tracker API refuses anything that did not come from the same host, so the HRMS must
  call it on `127.0.0.1`, never through the public proxy.
* Put the tracker admin console behind an IP allow-list (office/VPN) at the proxy.

## Settings (`.env`)

```
DEBUG=False
HORILLA_ENV=production
SECRET_KEY=<64 random characters>
DB_INIT_PASSWORD=<unique>
ALLOWED_HOSTS=hrms.infisetu.in
CSRF_TRUSTED_ORIGINS=https://hrms.infisetu.in
SECURE_SSL_REDIRECT=True
DATABASE_URL=postgres://horilla_user:<password>@127.0.0.1:5432/horilla_db
REDIS_URL=redis://:<password>@127.0.0.1:6379/0
GUNICORN_WORKERS=2

SSO_ENABLED=True                      # see microsoft_sso/README.md
ENTRA_TENANT_ID=...  ENTRA_CLIENT_ID=...  ENTRA_CLIENT_SECRET=...

ACTIVITY_TRACKER_URL=http://127.0.0.1:8100
ACTIVITY_TRACKER_API_KEY=itm_...
ACTIVITY_TRACKER_CONSOLE_URL=https://itm.infisetu.in
```

The application refuses to start in production with a default secret key or default
`DB_INIT_PASSWORD`, so a half-configured server fails closed.

## PostgreSQL (4 GB box)

```
max_connections = 40
shared_buffers = 512MB
effective_cache_size = 1536MB
work_mem = 8MB
maintenance_work_mem = 128MB
wal_compression = on
```

## Redis

`maxmemory 128mb`, `maxmemory-policy allkeys-lru`. It only holds cache data.

## Static and media files

* Static files are served by WhiteNoise (compressed, cached); nginx can serve `/media/` directly.
* Run `python manage.py collectstatic --noinput` on each release.

## Backups (do this before go-live)

* Nightly `pg_dump` of the HRMS database + the `media/` folder, copied off the server.
* Tracker: its `data/` folder (SQLite DB, `master.key`, screenshots). Losing `master.key`
  means every PC must re-enrol.
* Test a restore once.

## Capacity notes

* **Traffic:** the HRMS pages are server-rendered; 1 TB/month is far more than needed.
  Tracker screenshots dominate: ~100 KB x 6/hour x 8 h x 50 people is about 7 GB/month.
* **Disk:** at 30-day screenshot retention budget ~10 GB; the HRMS database stays small.
* **Disk I/O:** 100 Mbps-class storage is fine; Postgres is mostly cache-resident.

## After each deploy

```
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py seed_email_templates      # only creates missing templates
```


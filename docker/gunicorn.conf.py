# Gunicorn configuration for Infisetu MIS (sized for a 2 vCPU / 4 GB VPS)
# This file provides advanced configuration options for the WSGI server

import multiprocessing
import os

# Bind settings
# GUNICORN_BIND_HOST=127.0.0.1 is used when the container shares the host's network
# (single-VPS production), so only the local HTTPS proxy can reach it.
host = os.environ.get("GUNICORN_BIND_HOST", "0.0.0.0")
bind = f"{host}:{os.environ.get('PORT', '8000')}"
port = int(os.environ.get("PORT", "8000"))

# Worker settings
# One process is ~260 MB resident, so the classic "2 x CPUs + 1" rule would put
# five of them (1.3 GB) on a 2 vCPU box that also runs Postgres, Redis, the
# scheduler and the activity tracker. Concurrency comes from threads instead.
workers = int(
    os.environ.get("GUNICORN_WORKERS", max(2, min(multiprocessing.cpu_count(), 4)))
)
worker_class = "gthread"
threads = 4
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
# preload_app is disabled with gthread workers to avoid ORM connection issues
preload_app = False

# Timeout settings
timeout = 120
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "infisetu-mis"

# Server mechanics
pidfile = "/tmp/gunicorn.pid"
user = None  # Run as current user in container
group = None
tmp_upload_dir = None

# Development settings
reload = os.environ.get("GUNICORN_RELOAD", "false").lower() == "true"

# SSL settings (if needed)
# ssl_keyfile = os.environ.get('SSL_KEYFILE')
# ssl_certfile = os.environ.get('SSL_CERTFILE')

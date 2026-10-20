#!/usr/bin/env bash
# Nightly HRMS backup: PostgreSQL dump + uploaded media. Run from the project directory (cron).
#   30 2 * * *  cd /opt/infisetu-mis && bash deploy/backup-hrms.sh >> /var/log/hrms-backup.log 2>&1
# Copy /var/backups/hrms OFF the server (rclone/scp). A backup on the same disk is not a backup.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
set -a; . ./.env; set +a

DEST="${BACKUP_DIR:-/var/backups/hrms}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
STAMP="$(date +%F)"
umask 077
mkdir -p "$DEST"

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$COMPOSE exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner | gzip > "$DEST/hrms-db-$STAMP.sql.gz"
$COMPOSE exec -T web tar -czf - -C /app media > "$DEST/hrms-media-$STAMP.tar.gz"

find "$DEST" -type f \( -name 'hrms-db-*' -o -name 'hrms-media-*' \) -mtime +"$KEEP_DAYS" -delete
echo "hrms backup ok: $DEST"

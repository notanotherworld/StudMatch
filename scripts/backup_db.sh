#!/bin/bash
# ==============================================================================
# StudMatch PostgreSQL Backup Script with 7-Day Rotation
# ==============================================================================
# Usage:
#   chmod +x scripts/backup_db.sh
#   ./scripts/backup_db.sh
#
# Add to crontab (e.g. daily at 03:00 AM):
#   0 3 * * * /path/to/bot-univer/scripts/backup_db.sh >> /path/to/bot-univer/backups/backup.log 2>&1
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"

mkdir -p "$BACKUP_DIR"

# Load .env file if present
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs -d '\n')
fi

DB_USER="${POSTGRES_USER:-studmatch}"
DB_NAME="${POSTGRES_DB:-studmatch}"
CONTAINER_NAME="studmatch-postgres"

TIMESTAMP=$(date +"%Y-%m-%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/studmatch_backup_${TIMESTAMP}.sql.gz"

echo "=================================================="
echo "📦 [StudMatch Backup] Starting backup at $(date)..."
echo "Target: $BACKUP_FILE"

# Check if postgres container is running
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    docker exec -t "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"
else
    echo "⚠️ Container $CONTAINER_NAME is not running. Trying via docker compose..."
    cd "$PROJECT_DIR"
    docker compose exec -T postgres pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"
fi

FILESIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "✅ Backup successfully created: $BACKUP_FILE ($FILESIZE)"

# 7-Day retention policy (delete backups older than 7 days)
echo "🧹 Removing backups older than 7 days..."
find "$BACKUP_DIR" -type f -name "studmatch_backup_*.sql.gz" -mtime +7 -exec rm -f {} \;
echo "✨ Backup rotation complete. Remaining backups in $BACKUP_DIR:"
ls -lh "$BACKUP_DIR"/*.sql.gz 2>/dev/null || echo "No other backups."
echo "=================================================="

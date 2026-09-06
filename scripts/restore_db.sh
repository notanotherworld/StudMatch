#!/bin/bash
# ==============================================================================
# StudMatch PostgreSQL Restore Script
# ==============================================================================
# Usage:
#   ./scripts/restore_db.sh backups/studmatch_backup_2026-09-07_030000.sql.gz
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -z "$1" ]; then
    echo "❌ Usage: $0 <path_to_backup.sql.gz>"
    echo "Available backups in backups/:"
    ls -lh "$PROJECT_DIR/backups"/*.sql.gz 2>/dev/null || echo "No backups found."
    exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ Backup file not found: $BACKUP_FILE"
    exit 1
fi

# Load .env file if present
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs -d '\n')
fi

DB_USER="${POSTGRES_USER:-studmatch}"
DB_NAME="${POSTGRES_DB:-studmatch}"
CONTAINER_NAME="studmatch-postgres"

echo "=================================================="
echo "⚠️ WARNING: You are about to restore database '$DB_NAME' from:"
echo "   $BACKUP_FILE"
echo "All current data will be overwritten!"
echo "=================================================="
read -p "Are you sure you want to proceed? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

echo "🔄 Restoring database..."
gunzip -c "$BACKUP_FILE" | docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" "$DB_NAME"

echo "✅ Database successfully restored from $BACKUP_FILE"
echo "=================================================="

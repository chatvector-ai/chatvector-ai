#!/bin/bash
set -e

echo "========================================="
echo "ChatVector API Starting"
echo "========================================="

# Clean up any SQLite files from previous versions.
echo "Checking for old SQLite databases..."
SQLITE_FILES=$(find /app -maxdepth 1 -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" 2>/dev/null || true)

if [ -n "$SQLITE_FILES" ]; then
    echo "Found old SQLite databases:"
    echo "$SQLITE_FILES" | while read -r db_file; do
        echo "   - Removing: $(basename "$db_file")"
        rm -f "$db_file"
    done

    # Also remove journal files.
    find /app -maxdepth 1 -name "*.db-*" -exec rm -f {} \; 2>/dev/null || true
    echo "Cleanup complete"
else
    echo "No SQLite databases found (using PostgreSQL)"
fi

echo "========================================="
echo "Starting server..."
echo "========================================="

# Execute the main command.
exec "$@"

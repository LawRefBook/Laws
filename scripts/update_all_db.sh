#!/bin/bash
set -e

DLC_PATTERN="../DLC*/*"
MAIN_DB="../db.sqlite3"

update_db() {
    local db_path="$1"
    local message="$2"
    
    echo "$message"
    python database.py update "$db_path"
}

# 先更新本体：DLC 的实施关系指向本体数据库里的法规 ID
echo "=== Updating main database ==="
update_db "$MAIN_DB" "Updating main database"

echo "=== Updating DLCs ==="
for dir in $DLC_PATTERN; do
    if [ -d "$dir" ] && [ "$(basename "$dir")" != "db.sqlite3" ]; then
        update_db "$dir/db.sqlite3" "Updating $dir/db.sqlite3"
        echo "--------------"
    fi
done

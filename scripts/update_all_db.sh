#!/bin/bash

folder="../DLC"

echo "Updating DLCs"
for dir in "$folder"*/*; do
    filename=$(basename "$dir")

    if [ "$filename" != "db.sqlite3" ] && [ -d "$dir" ]; then
        echo "Updating $dir/db.sqlite3"
        python database.py update $dir/db.sqlite3
    fi
    echo "--------------"
done

echo "Updating main database"
python database.py update ../db.sqlite3
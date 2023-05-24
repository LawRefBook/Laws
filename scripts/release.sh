#!/bin/bash

function pack {

    out_path="$(pwd)/release"
    if [ "$1" != "." ]; then out_path="$out_path/DLC"; fi

    if [ ! -d "$out_path" ]; then mkdir -p "$out_path"; fi

    output_zip="$out_path/$2"

    echo "Packaging $1 to $output_zip"
    cd "$1" || exit

    find . -type f \( -name ".*" -prune \) -o \( -name "scripts" -o -name "release" -o -name ".venv" -o -name ".git*" -o -name "DLC" \) -prune -o -exec zip -q "$output_zip" {} +

    shasum -a 1 -b $output_zip | awk -F" " '{printf "%s", $1}'> $output_zip.sha1
}

cd ../
pack "." "laws.zip"
folder="./DLC"
for dir in "$folder"*/*; do
    filename=$(basename "$dir")
    if [ -d "$dir" ]; then
        pack $dir "$filename.zip"
    fi
done
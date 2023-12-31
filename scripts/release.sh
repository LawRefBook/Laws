#!/bin/bash

force=0
if [ "$1" == "-f" ]; then
    force=1
fi

if ! command -v jq >/dev/null; then
  echo "Error: 'jq' is required but not installed. Aborting."
  exit 1
fi

cd ../
current_path=$(pwd)

function pack {

    out_path="$(pwd)/release"
    output_zip_name="$2"
    output_name=${output_zip_name%.*}

    meta_file="$out_path/metadata/$output_name.meta"

    if [ "$1" != "." ]; then out_path="$out_path/DLC"; fi
    if [ ! -d "$out_path" ]; then mkdir -p "$out_path"; fi

    if [ ! -d "$(dirname "$meta_file")" ]; then mkdir -p "$(dirname "$meta_file")"; fi

    cd "$1" || exit

    _hash=$(git log -n 1 --pretty=format:"%H"  -- . ':!scripts' ':!.*' ':!DLC' | awk -F" " '{printf "%s", $1}')

    if [ -f "$meta_file" ] && [ "$force" == 0 ] ; then
        if [ "$_hash" == "$(jq -r .hash "$meta_file")" ]; then
            echo "No changes detected $1, skipping..."
            return
        fi
    fi

    find "$out_path" -name "$output_name*" -delete
    output_zip="$out_path/$output_zip_name"
    if [ "$1" != "." ]; then output_zip="$out_path/$output_name.$_hash.zip"; fi
    echo "Packaging $1 to $output_zip"

    find . -type f \( -name ".*" -prune \) -o \( -name "scripts" -o -name "release" -o -name ".venv" -o -name ".git*" -o -name "DLC" \) -prune -o -exec zip -q "$output_zip" {} +

    _at=$(git log -n 1 --pretty=format:"%at"  -- . ':!scripts' ':!.*' ':!DLC' | awk -F" " '{printf "%s", $1}')
    size=$(du -k "$output_zip" | cut -f1)

    json=$(printf '{"name":"%s","hash":"%s", "update":%s, "filesize":%s}' $output_name $_hash $_at $size)
    echo $json > $meta_file
}

function packall() {
    pack "." "laws.zip"
    folder="./DLC"
    for dir in "$folder"*/*; do
        filename=$(basename "$dir")
        if [ -d "$dir" ]; then
            pack $dir "$filename.zip"
        fi
        cd $current_path
    done
}

function genJSON() {
    # Generate dlc.txt
    cd $current_path
    OUT_JSON_FILE="./release/dlc.json"
    METADATA_PATH="./release/metadata"
    if [ -f $OUT_JSON_FILE ]; then rm $OUT_JSON_FILE; fi

    echo "[" >> $OUT_JSON_FILE

    for file in $(find ./release/DLC -name "*.zip"); do
        name=$(basename $file)
        name=${name%.*}
        name=${name%.*}
        meta=$(cat $METADATA_PATH/$name.meta)
        echo $meta"," >> $OUT_JSON_FILE
    done

    sed '$s/,$//' "$OUT_JSON_FILE" > $OUT_JSON_FILE".tmp"
    echo "]" >> $OUT_JSON_FILE".tmp"
    jq '.' $OUT_JSON_FILE".tmp" > $OUT_JSON_FILE
    rm $OUT_JSON_FILE".tmp"
}

packall
genJSON

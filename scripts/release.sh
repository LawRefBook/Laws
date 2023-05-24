#!/bin/bash

function pack {

    out_path="$(pwd)/release"
    if [ "$1" != "." ]; then out_path="$out_path/DLC"; fi

    if [ ! -d "$out_path" ]; then mkdir -p "$out_path"; fi

    output_zip="$out_path/$2"

    echo "Packaging $1 to $output_zip"
    cd "$1" || exit

    _hash=$(git log -n 1 --pretty=format:"%H"  -- . ':!scripts' ':!.*' ':!DLC' | awk -F" " '{printf "%s", $1}')
    _hash_file="$output_zip.hash"

    if [ -f $_hash_file ]; then
        if [ "$_hash" == "$(cat $_hash_file)" ]; then
            echo "No changes detected, skipping..."
            return
        fi
    fi

    find . -type f \( -name ".*" -prune \) -o \( -name "scripts" -o -name "release" -o -name ".venv" -o -name ".git*" -o -name "DLC" \) -prune -o -exec zip -q "$output_zip" {} +

    echo $_hash > $_hash_file
}

cd ../
current_path=$(pwd)
pack "." "laws.zip"
folder="./DLC"
for dir in "$folder"*/*; do
    filename=$(basename "$dir")
    if [ -d "$dir" ]; then
        pack $dir "$filename.zip"
    fi
done

# Generate dlc.txt
cd $current_path
rm ./release/dlc.txt
for file in $(find ./release/DLC -name "*.zip"); do
    echo "$(basename $file) $(cat $file.hash)" >> ./release/dlc.txt
done
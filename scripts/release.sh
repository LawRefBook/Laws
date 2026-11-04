#!/bin/bash

RELEASE_FOLDER="./.release"
RELEASE_BRANCH="release"

# -f      不比较 hash，强制重新打包
# --main  只发布本体，DLC 保持线上版本不动
# --dlc   只发布 DLC，本体保持线上版本不动
force=0
pack_main=1
pack_dlc=1
for arg in "$@"; do
    case "$arg" in
        -f) force=1 ;;
        --main) pack_dlc=0 ;;
        --dlc) pack_main=0 ;;
        *) echo "Usage: $0 [-f] [--main | --dlc]"; exit 1 ;;
    esac
done
if [ "$pack_main" == 0 ] && [ "$pack_dlc" == 0 ]; then
    echo "--main 和 --dlc 不能同时使用"
    exit 1
fi

if ! command -v jq >/dev/null; then
  echo "Error: 'jq' is required but not installed. Aborting."
  exit 1
fi

cd ../
current_path=$(pwd)

function pack {

    out_path="$(pwd)/$RELEASE_FOLDER"
    output_zip_name="$2"
    output_name=${output_zip_name%.*}

    meta_file="$out_path/metadata/$output_name.meta"

    if [ "$1" != "." ]; then out_path="$out_path/DLC"; fi
    if [ ! -d "$out_path" ]; then mkdir -p "$out_path"; fi

    if [ ! -d "$(dirname "$meta_file")" ]; then mkdir -p "$(dirname "$meta_file")"; fi

    cd "$1" || exit

    # scrape 已并入 scripts，仍排除它，否则移走 scrape 的那次提交会被算成数据变化
    _hash=$(git log -n 1 --pretty=format:"%H"  -- . ':!scripts' ':!scrape' ':!.*' ':!DLC' ':!Makefile' | awk -F" " '{printf "%s", $1}')

    if [ "$force" == 0 ] ; then
        # Check if the metadata file exists in the release branch
        if git show "$RELEASE_BRANCH:alpha/metadata/$output_name.meta" >/dev/null 2>&1; then
            old_hash=$(git show "$RELEASE_BRANCH:alpha/metadata/$output_name.meta" 2>/dev/null | jq -r .hash 2>/dev/null)
            if [ -n "$old_hash" ] && [ "$old_hash" != "null" ] && [ -n "$_hash" ] && [ "$_hash" == "$old_hash" ]; then
                echo "No changes detected $1, skipping..."
                return
            fi
        fi
    fi

    find "$out_path" -name "$output_name*" -delete
    output_zip="$out_path/$output_zip_name"
    if [ "$1" != "." ]; then output_zip="$out_path/$output_name.$_hash.zip"; fi
    echo "Packaging $1 to $output_zip"

    find . -type f \( -name ".*" -prune \) -o \( -name "scripts" -o -name "Makefile" -o -name "scrape" -o -name "release" -o -name ".venv" -o -name ".git*" -o -name "DLC" \) -prune -o -exec zip -q "$output_zip" {} +

    _at=$(git log -n 1 --pretty=format:"%at"  -- . ':!scripts' ':!scrape' ':!.*' ':!DLC' ':!Makefile' | awk -F" " '{printf "%s", $1}')
    size=$(du -k "$output_zip" | cut -f1)

    json=$(printf '{"name":"%s","hash":"%s", "update":%s, "filesize":%s}' $output_name $_hash $_at $size)
    echo $json > $meta_file
}

function packall() {
    if [ "$pack_main" == 1 ]; then pack "." "laws.zip"; fi
    if [ "$pack_dlc" == 0 ]; then return; fi
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
    OUT_JSON_FILE="$RELEASE_FOLDER/dlc.json"
    METADATA_PATH="$RELEASE_FOLDER/metadata"
    if [ -f $OUT_JSON_FILE ]; then rm $OUT_JSON_FILE; fi

    echo "[" >> $OUT_JSON_FILE

    for file in $(find $RELEASE_FOLDER/DLC -name "*.zip"); do
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

function finalize() {
    echo "Finalizing release..."
    cd "$current_path"

    _tmp_dir=$(mktemp -d)
    cp -r "$RELEASE_FOLDER"/* "$_tmp_dir/"

    _current_branch=$(git rev-parse --abbrev-ref HEAD)

    # Save current state
    _stash_out=$(git stash push -m "release_temp_stash")
    _stashed=0
    if [[ "$_stash_out" != "No local changes to save" ]]; then
        _stashed=1
    fi

    git checkout "$RELEASE_BRANCH"
    rm -rf alpha/*
    cp -r "$_tmp_dir"/* alpha/
    git add alpha
    git commit -m "release: $(date +'%Y-%m-%d %H:%M:%S')"
    git push

    git checkout "$_current_branch"
    if [ $_stashed -eq 1 ]; then
        git stash pop
    fi

    rm -rf "$_tmp_dir"
    echo "Release finalized."
}

# check out release branch alpha folder to ./release folder
rm -rf $RELEASE_FOLDER
git restore --source $RELEASE_BRANCH --worktree -- alpha
mv alpha $RELEASE_FOLDER

packall
genJSON
finalize


#!/bin/bash

RELEASE_FOLDER="./.release"
RELEASE_BRANCH="release"

# -f      不比较 hash，强制重新打包
# --main  只发布本体，DLC 保持线上版本不动
# --dlc   只发布 DLC，本体保持线上版本不动
# --channel alpha|prod  发布到哪个 channel，默认 alpha
#         alpha 在 release 分支的 alpha/ 下，prod 在 release 分支根目录
USAGE="Usage: $0 [-f] [--main | --dlc] [--channel alpha|prod]"
force=0
pack_main=1
pack_dlc=1
channel=alpha
while [ $# -gt 0 ]; do
    case "$1" in
        -f) force=1 ;;
        --main) pack_dlc=0 ;;
        --dlc) pack_main=0 ;;
        --channel) shift; channel="$1" ;;
        *) echo "$USAGE"; exit 1 ;;
    esac
    shift
done
case "$channel" in
    alpha) CHANNEL_DIR="alpha" ;;
    prod) CHANNEL_DIR="" ;;
    *) echo "$USAGE"; exit 1 ;;
esac
# channel 目录里由发布管理的文件，prod 的根目录还有 CNAME、alpha/ 等不能动
CHANNEL_PATHS=(laws.zip DLC dlc.json metadata)
CHANNEL_PREFIX="${CHANNEL_DIR:+$CHANNEL_DIR/}"
echo "Channel: $channel"
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
# 校验数据库要用装了 peewee 的 Python，优先用仓库的虚拟环境
PYTHON="$current_path/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON="python3"; fi

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
        if git show "$RELEASE_BRANCH:${CHANNEL_PREFIX}metadata/$output_name.meta" >/dev/null 2>&1; then
            old_hash=$(git show "$RELEASE_BRANCH:${CHANNEL_PREFIX}metadata/$output_name.meta" 2>/dev/null | jq -r .hash 2>/dev/null)
            if [ -n "$old_hash" ] && [ "$old_hash" != "null" ] && [ -n "$_hash" ] && [ "$_hash" == "$old_hash" ]; then
                echo "No changes detected $1, skipping..."
                return
            fi
        fi
    fi

    if [ "$1" != "." ]; then
        # 打包前校验 DLC 数据库，失败时整个发布中止，不会提交和 push
        echo "Checking $1/db.sqlite3"
        if ! "$PYTHON" "$current_path/scripts/database.py" check "db.sqlite3"; then
            echo "Check failed for $1, release aborted."
            exit 1
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
        # 仓库里已经删掉的 DLC 不再列出，zip 和 meta 留在 release 分支上，已经下载的用户不受影响
        if ! compgen -G "./DLC*/$name" >/dev/null; then
            echo "Delisting $name: no longer in the repository" >&2
            continue
        fi
        meta=$(cat $METADATA_PATH/$name.meta)
        echo $meta"," >> $OUT_JSON_FILE
    done

    sed '$s/,$//' "$OUT_JSON_FILE" > $OUT_JSON_FILE".tmp"
    echo "]" >> $OUT_JSON_FILE".tmp"
    jq '.' $OUT_JSON_FILE".tmp" > $OUT_JSON_FILE
    rm $OUT_JSON_FILE".tmp"
}

function finalize() {
    echo "Finalizing release ($channel)..."
    cd "$current_path"

    # 在临时 worktree 里提交，不用切换当前分支，也不会碰到工作区里未跟踪的文件
    _wt=$(mktemp -d)
    git worktree add -q "$_wt" "$RELEASE_BRANCH" || exit 1
    _target="$_wt/$CHANNEL_DIR"
    mkdir -p "$_target"

    _paths=()
    for p in "${CHANNEL_PATHS[@]}"; do
        rm -rf "${_target:?}/$p"
        _paths+=("$CHANNEL_PREFIX$p")
    done
    cp -R "$RELEASE_FOLDER"/. "$_target/"

    git -C "$_wt" add -A -- "${_paths[@]}"
    if git -C "$_wt" diff --cached --quiet; then
        echo "Nothing changed in $channel, nothing to release."
    else
        git -C "$_wt" commit -q -m "release($channel): $(date +'%Y-%m-%d %H:%M:%S')"
        git -C "$_wt" push || _failed=1
    fi

    git worktree remove --force "$_wt"
    if [ -n "$_failed" ]; then
        echo "Push failed. The commit stays on the local $RELEASE_BRANCH branch; push it manually."
        exit 1
    fi
    echo "Release finalized."
}

# 把 release 分支上该 channel 的现有内容取到 ./.release，作为打包的基础
rm -rf $RELEASE_FOLDER
mkdir -p $RELEASE_FOLDER
_existing=()
for p in "${CHANNEL_PATHS[@]}"; do
    if git cat-file -e "$RELEASE_BRANCH:$CHANNEL_PREFIX$p" 2>/dev/null; then _existing+=("$p"); fi
done
if [ ${#_existing[@]} -gt 0 ]; then
    git archive "$RELEASE_BRANCH:$CHANNEL_DIR" -- "${_existing[@]}" | tar -x -C $RELEASE_FOLDER || exit 1
fi

packall
# 只发布本体时 DLC 不动，沿用线上的 dlc.json
if [ "$pack_dlc" == 1 ]; then genJSON; fi
finalize


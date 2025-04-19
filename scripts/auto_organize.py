import re
from collections import defaultdict
from pathlib import Path

input_folder = Path("./__cache__/out/法律")
LOOKUP_FOLDER = Path("../")

name_regxp = re.compile(r"(.*)\((\d{4}-\d{2}-\d{2})\).md")
def find_all():
    # find all md files in LOOKUP_FOLDER,
    # file name pattern 专利法(2020-10-17).md
    # extract title and publish date
    result = defaultdict(set)
    for file_path in LOOKUP_FOLDER.glob("**/*.md"):
        # ignore if in 'scripts'
        if "scripts" in file_path.parts:
            continue
        m = name_regxp.search(file_path.name)
        # folder_name is the folder path relative to LOOKUP_FOLDER
        folder_name = file_path.relative_to(LOOKUP_FOLDER).parent
        if not m:
            continue
        title = m.group(1)
        result[title].add(folder_name)
    return result

def main():
    laws_map = find_all()
    for file_path in input_folder.glob("*.md"):
        m = name_regxp.search(file_path.name)
        if not m:
            continue
        title = m.group(1)
        if title not in laws_map:
            print("not found", title)
            continue
        folders = laws_map[title]
        if len(folders) > 1:
            print("duplicate", title, folders)
            continue
        folder = list(folders)[0]
        print("move", file_path, "to", LOOKUP_FOLDER / folder / file_path.name)
        file_path.rename(LOOKUP_FOLDER / folder / file_path.name)

if __name__ == "__main__":
    main()

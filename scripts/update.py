import json
from pathlib import Path
from functools import reduce
import re
from uuid import uuid4


def find_laws():
    bypass = ["scripts"]
    base = Path("../")
    ret = []
    for file in base.glob("**/*.md"):
        if "_index.md" == file.parts[-1]:
            continue
        file = file.relative_to("../")
        folder = "/".join(file.parts[:-1])
        if not folder:
            continue
        bypass_flag = False
        for by in bypass:
            if re.search(by, str(file)):
                bypass_flag = True
                break
        if bypass_flag:
            continue
        d = (folder, file.parts[-1].split(".")[0])
        ret.append(d)
    return ret


def check_pattern(law, name) -> bool:
    def check(key):
        return key in law and law[key] == name
    return check("name") or check("subtitle") or check("filename")


def find_difference(laws, local_laws):
    ret = []
    for ll in local_laws:
        found = False
        for law in laws:
            if check_pattern(law, ll[1]):
                found = True
                break
        if not found:
            ret.append(ll)
    return ret


def get_level(folder):
    if "/" in folder:
        folder = folder.split("/")[0]
    if folder in ["司法解释", "地方性法规", "案例", "其他", "行政法规"]:
        return folder
    return "法律"


def check_law_exists(category, law):
    folder = Path(f"../{category['folder']}")

    def check(key):
        if key not in law:
            return False
        val: str = law[key]
        path = folder / f"{val}.md"
        return path.exists()
    return check("name") or check("subtitle") or check("filename")


def main():
    with open("../data.json", "r") as f:
        data = json.load(f)
    laws = reduce(lambda x, y: x + y["laws"], data, [])
    local_laws = find_laws()

    def find_category(pattern):
        for category in data:
            if category["folder"] == pattern:
                return category
        return None

    for folder, name in find_difference(laws, local_laws):
        category = find_category(folder)
        if not category:
            print(f"category {category} not found")
            continue

        category["laws"].append({
            "name": name,
            "id": str(uuid4()),
            "level": get_level(folder)
        })

    for category in data:
        for law in category["laws"]:
            if not check_law_exists(category, law):
                print(f"不存在 {law}")

    with open("../data.json", "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    main()

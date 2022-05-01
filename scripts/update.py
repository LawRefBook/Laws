import json
from pathlib import Path
from functools import reduce
import re
import shutil
from uuid import uuid4

import request


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
        json.dump(data, f, ensure_ascii=False, indent=4, sort_keys=True)


def update_status():
    params = [
        # ('xlwj', ['02', '03', '04', '05', '06', '07', '08']),  # 法律法规
        # ("fgbt", "中华人民共和国澳门特别行政区基本法"),
        # ("fgxlwj", "xzfg"),  # 行政法规
        ('type', 'sfjs'),
        # ("zdjg", "4028814858a4d78b0158a50f344e0048&4028814858a4d78b0158a50fa2ba004c"), #北京
        # ("zdjg", "4028814858b9b8e50158bed591680061&4028814858b9b8e50158bed64efb0065"), #河南
        # ("zdjg", "4028814858b9b8e50158bec45e9a002d&4028814858b9b8e50158bec500350031"), # 上海
        # ("zdjg", "4028814858b9b8e50158bec5c28a0035&4028814858b9b8e50158bec6abbf0039"), # 江苏
        # ("zdjg", "4028814858b9b8e50158bec7c42f003d&4028814858b9b8e50158beca3c590041"), # 浙江
        # ("zdjg", "4028814858b9b8e50158bed40f6d0059&4028814858b9b8e50158bed4987a005d"),  # 山东
        # ("zdjg", "4028814858b9b8e50158bef1d72600b9&4028814858b9b8e50158bef2706800bd"), # 陕西省
    ]
    with open("../data.json", "r") as f:
        data = json.load(f)
        lawMap = {
            x: y for (x, y) in map(
                lambda x: (x["name"], x),
                reduce(lambda x, y: x + y["laws"], data, [])
            )
        }
    db = request.LawDatabase()
    db.request.searchType = "1,9"
    for param in params:
        db.request.params = [param]
        for law in db.lawList():
            title = law["title"].replace("中华人民共和国", "")
            if title in lawMap and "status" in law:
                if int(law["status"]) == 9:
                    lawMap[title]["expired"] = True

    with open("../data.json", "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=4, sort_keys=True)


def rename_files():
    base_path = Path("../")
    for folder, law in find_laws():
        clean_title = law.replace("中华人民共和国", "")
        file_path = base_path / folder / f"{law}.md"
        to_path = base_path / folder / f"{clean_title}.md"
        shutil.move(file_path, to_path)


if __name__ == "__main__":
    main()
    update_status()
    rename_files()

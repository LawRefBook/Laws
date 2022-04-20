"""
转换典型案例
"""

import re
import json

FILE_NAME = "最高法发布消费者权益保护典型.txt"
section = [
    "基本案情",
    "申请人请求",
    "原告诉讼请求",
    "裁判结果",
    "处理结果",
    "案例分析",
    "典型意义",
    "裁判要点",
    "简要案情",
    "法院裁判",
    "司法解释相关法条",
]


def isSection(line) -> bool:
    line = line.strip()
    for pattern in section:
        flag = re.search("^[【\(（]{0,1}" + pattern +"[】\)）]{0,1}$", line)
        if flag:
            return True
    return False


zh_nums = "[一二三四五六七八九十零百千万1234567890]+"
title_matcher = f"((?:^{zh_nums}、)|(?:^案例{zh_nums}))"


def isTitle(line) -> str:
    if re.match(title_matcher, line):
        return re.sub(title_matcher, "", line).strip()
    return None


def main():
    with open(f"./__cache__/{FILE_NAME}", "r") as f:
        data = f.read()

    lines = data.split("\n")
    f = None
    title_no = 0
    jsonArr = []
    info_end = False

    case_title = ""
    sub_title = ""

    lines = filter(lambda x: x, map(lambda x: x.strip(), lines))

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        title = isTitle(line)
        if title:
            print(title)
            if f:
                data = {
                    "name": case_title,
                    "level": "案例",
                }
                if sub_title:
                    data["subtitle"] = sub_title
                jsonArr.append(data)
                f.close()
            title_no = i
            f = open(f"./__cache__/out/{title}.md", "w")
            f.write(f"# {title}\n")
            case_title = title
            sub_title = ""
            info_end = False
        elif i == title_no + 1 and line.startswith("-"):
            sub_title = line.strip("-")
            f.write(f"# {sub_title}\n")
        elif f:
            if not info_end:
                f.write(f"<!-- INFO END -->")
                info_end = True
            if isSection(line):
                f.write(f"## {line.strip('【】')}")
            else:
                f.write(line)
        f.write("\n")

    print(json.dumps(jsonArr, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

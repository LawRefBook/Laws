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
]

def isSection(line) -> bool:
    for pattern in section:
        if re.match(f"^{pattern}", line):
            return True
    return False

def isTitle(line) -> str:
    if re.match(f"^{zh_nums}、", line):
        return re.sub(f"^{zh_nums}、", "", line)
    return None

zh_nums = "[一二三四五六七八九十零百千万1234567890]+"

def main():
    with open(f"./__cache__/{FILE_NAME}", "r") as f:
        data = f.read()

    lines = data.split("\n")
    f = None
    jsonArr = []

    for line in lines:
        line = line.strip()
        title = isTitle(line)
        if title:
            if f:
                f.close()
            f = open(f"./__cache__/out/{title}.md", "w")
            f.write(f"# {title}\n")
            f.write(f"<!-- INFO END -->")
            jsonArr.append({
                "name": title,
                "level": "案例",
            })
        elif isSection(line):
            f.write(f"## {line}")
        else:
            f.write(line)
        f.write("\n")

    print(json.dumps(jsonArr, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

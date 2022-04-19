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

def main():
    with open(f"./__cache__/{FILE_NAME}", "r") as f:
        data = f.read()
    cases = list(filter(lambda x: x, map(
        lambda x: x.strip(".\n "), re.split("案例\d{1,2}", data))))

    jsonArr = []
    for case in cases:
        case = list(filter(lambda x: x, map(
            lambda x: x.strip(), case.split("\n"))))
        title = case[0]
        subtitle = case[1].strip("——")
        print(title)

        with open(f"./__cache__/out/{subtitle or title}.md", "w") as f:
            title and f.write(f"# {title}\n")
            f.write("""
消费者权益保护典型案例

最高人民法院发布

2022-03-15

""")
            f.write(f"<!-- INFO END -->\n\n")
            subtitle and f.write(f"## {subtitle}\n")
            for i in range(2, len(case)):
                line = case[i]
                if isSection(line):
                    f.write(f"## {line}")
                else:
                    f.write(line)
                f.write("\n\n")

        data = {
            "name": title,
            "level": "案例",
        }

        if subtitle:
            data["subtitle"] = subtitle

        jsonArr.append(data)

    print(json.dumps(jsonArr, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

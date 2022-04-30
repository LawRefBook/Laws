"""
转换典型案例
"""

import re
import json
from typing import List
from uuid import uuid4

section = [
    "案情回顾",
    "法官解读",
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
    "裁判要旨",
    "适用解析",
    "司法解释相关法条",
]

zh_nums = "[一二三四五六七八九十零百千万1234567890]+"
title_matcher = f"((?:^{zh_nums}、)|(?:^案例{zh_nums}))"


def isSection(line) -> bool:
    line = line.strip()
    for pattern in section:
        flag = re.search("^[【\(（]{0,1}" + pattern + "[】\)）]{0,1}$", line)
        if flag:
            return True
    return False


def isTitle(line) -> str:
    if re.match(title_matcher, line):
        return re.sub(title_matcher, "", line).strip()
    return None


class Case(object):

    def __init__(self) -> None:
        self.title = None
        self.subtitle = None
        self.content: List[str] = []

    @property
    def filename(self) -> str:
        return self.subtitle or self.title

    def __repr__(self) -> str:
        return f"<Case {self.filename} {len(self.content)}>"

    __str__ = __repr__


class CasesParser(object):

    def __init__(self) -> None:
        self.filename = "./__cache__/案例.txt"

    def __slice_content(self, content: str) -> List[str]:
        ret = []

        for line in content.split("。"):
            if len(ret) == 0 or len(ret[-1]) + len(line) > 200:
                if len(ret) > 0:
                    ret[-1] += "。"
                ret.append("")

            if ret[-1]:
                ret[-1] += "。"
            ret[-1] += line

        return ret

    def parse(self) -> List[Case]:
        with open(self.filename, "r") as f:
            data = filter(
                lambda x: x,
                map(
                    lambda x: x.strip(),
                    f.readlines()
                )
            )

        cases: List[Case] = []
        title_at = 0
        for no, line in enumerate(data):
            newCase = isTitle(line)
            if len(cases) == 0 or newCase:
                cases.append(Case())
            case = cases[-1]
            if title := isTitle(line):
                case.title = title
                title_at = no
                continue
            if no == title_at + 1 and re.match(r"^[——-]", line):
                case.subtitle = line.strip("——-")
                continue

            if isSection(line):
                case.content.append(f"## {line.strip('【】')}")
            else:
                case.content += self.__slice_content(line)
        return cases

    def write(self, cases: List[Case]):
        ret_json = []
        for case in cases:
            case_json = {
                "name": case.title,
                "level": "案例",
                "id": str(uuid4()),
            }
            if case.subtitle:
                case_json["subtitle"] = case.subtitle
            ret_json.append(case_json)
            with open(f"./__cache__/out/{case.filename}.md", "w") as f:
                contents = [
                    f"# {case.title}",
                    "<!-- INFO END -->",
                ]
                if case.subtitle:
                    contents.append(f"## {case.subtitle}")
                f.write("\n\n".join(contents + case.content))
        print(json.dumps(ret_json, ensure_ascii=False, indent=4, sort_keys=True))


if __name__ == "__main__":
    parser = CasesParser()
    cases = parser.parse()
    parser.write(cases)

#!/usr/bin/env python3

import json
from uuid import uuid4
import glob
import shutil
import functools
import os
import re


def addUUID():
    with open("../data.json", "r") as f:
        data = json.load(f)
    for line in data:
        if "id" not in line:
            line["id"] = str(uuid4())
        for content in line["laws"]:
            if "id" not in content:
                content["id"] = str(uuid4())
    with open("../data.json", "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def getLevel(pattern):
    if "法" in pattern:
        return "法律"
    return "其他"


def addMissingLaw():
    with open("../data.json", "r") as f:
        data = json.load(f)

    def findTargetObj(pattern: str):
        for line in data:
            if line["category"] == pattern or (name in line and line["name"] == pattern):
                return line
        ret = dict()
        data.append(ret)
        return ret

    ignorePattern = ".+民法典|.+刑法|.+模版|.+index.md|.+README.md|.*__cache__"
    laws = functools.reduce(
        lambda a, b: a + b,
        map(
            lambda x: x["laws"],
            data
        )
    )
    allLaws = set(
        filter(lambda x: x, [
            x for y in map(
                lambda x: [x["name"], x["subtitle"] if "subtitle" in x else None,
                           x["filename"] if "filename" in x else None],
                laws
            ) for x in y
        ])
    )
    for line in glob.glob("../**/*.md", recursive=True):
        if re.match(ignorePattern, line):
            # print(line)
            continue
        name = os.path.splitext(os.path.basename(line))[0]
        if name in allLaws:
            continue
        print(line)
        folder = line.split("/")[1]
        target = findTargetObj(folder)
        level = getLevel(folder)
        if "category" not in target:
            target["category"] = folder
        if "folder" not in target:
            target["folder"] = folder
        if "laws" not in target:
            target["laws"] = []
        item = dict()
        # item["name"] = name.replace("中华人民共和国", "")
        item["name"] = re.sub("^中华人民共和国", "", name)
        item["level"] = level
        target["laws"].append(item)

    with open("../data.json", "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def renameFiles():
    for line in glob.glob("../**/*.md", recursive=True):
        newPath = line.replace("/中华人民共和国", "")
        shutil.move(line, newPath)


# 用于找到 “第x条" 或者 "第x条之一"
num = "[一二三四五六七八九十零]"
title_re = "^(第"+num+"{1,6}?条(?:之"+num+"{1,2})*\s*)"


def cleanTitle(line: str):

    def f(matched):
        return matched.group(0).strip() + " "

    return re.sub(title_re, f, line)

ignoreFiles = r"(_index|模版|README)"

def clean():
    for filename in glob.glob("../**/*.md", recursive=True):
        if re.search(ignoreFiles, filename):
            continue

        with open(filename, "r") as f:
            data = f.readlines()
        flag = False
        for i, line in enumerate(data):
            line = line.strip(" ")
            if not line.strip():
                continue
            if line.startswith("#"):
                continue
            if line.startswith("<!-- INFO END -->"):
                flag = True
                continue
            if not flag:
                continue

            if line.startswith("<!--"):
                continue

            data[i] = cleanTitle(line)

            if "../案例/" in filename and data[i].strip():
                sentenses = data[i].split("。")
                count = 0
                newLine = ""
                for sentense in sentenses:
                    sentense = sentense.strip()
                    if not sentense:
                        continue
                    count += len(sentense)
                    newLine += sentense + "。"
                    if count >= 100:
                        newLine += "\n\n"
                        count = 0
                newLine += "\n"
                data[i] = newLine
                spliced = data[i].split(" ", 1)
                if len(spliced) == 2 and " " in spliced[1]:
                    spliced[1] = spliced[1].replace(" ", "")
                    data[i] = " ".join(spliced)

        with open(filename, "w") as f:
            result = "\n".join(filter(lambda x: x.strip(), data))
            result = re.sub("\n{2,}", "\n\n", result)
            f.write(result.strip())


def test():
    assert "第一条 测试" == cleanTitle("第一条测试")
    assert "第一条 测试" == cleanTitle("第一条 测试")
    assert "第一二三四五条 测试" == cleanTitle("第一二三四五条测试")
    assert "第一条之一 测试" == cleanTitle("第一条之一测试")
    assert "第一条之一 测试" == cleanTitle("第一条之一 测试")


def main():
    test()
    renameFiles()
    addMissingLaw()
    addUUID()
    clean()


if __name__ == "__main__":
    main()

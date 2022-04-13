import glob
import json
import math
import os
import re
import shutil
import time
import urllib.request
from hashlib import sha1
from typing import List
from bs4 import BeautifulSoup

import requests
from docx import Document

headers = {
    'authority': 'flk.npc.gov.cn',
    'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Microsoft Edge";v="99"',
    'accept': 'application/json, text/javascript, */*; q=0.01',
    'x-requested-with': 'XMLHttpRequest',
    'sec-ch-ua-mobile': '?0',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36 Edg/99.0.1150.39',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-site': 'same-origin',
    'sec-fetch-mode': 'cors',
    'sec-fetch-dest': 'empty',
    'referer': 'https://flk.npc.gov.cn/fl.html',
    'accept-language': 'en-AU,en-GB;q=0.9,en;q=0.8,en-US;q=0.7,zh-CN;q=0.6,zh;q=0.5',
    'cookie': 'yfx_c_g_u_id_10006696=_ck22022520424713255117764923111; cna=NdafGk8tiAgCAd9IPxhfROag; yfx_f_l_v_t_10006696=f_t_1645792967326__r_t_1646401808964__v_t_1646401808964__r_c_5; Hm_lvt_54434aa6770b6d9fef104d146430b53b=1646407223,1646570042,1646666110,1647148584; acw_tc=75a1461516471485843844814eb808af266b8ede0e0502ec1c46ab1581; Hm_lpvt_54434aa6770b6d9fef104d146430b53b=1647148626',
}

exists = set(map(lambda x: os.path.basename(x).split(".")[
             0], glob.glob("../**/*.md", recursive=True)))


category = []
with open("./cate.txt", "r") as f:
    title = ""
    for line in f.readlines():
        line = line.strip()
        if re.match("^[一二三四五六七八九十]、", line):
            title = line
            continue
        category.append({
            "title": line,
            "category": title,
        })


def requestPage(page: int):
    # 法律
    params = (
        ('page', str(page)),
        ('type', ''),
        # ('xlwj', ['02', '03', '04', '05', '06', '07', '08']),
        # ("fgxlwj", "xzfg"), # 行政法规
        ('searchType', 'title;accurate;1'),
        ('sortTr', 'f_bbrq_s;desc'),
        ('gbrqStart', ''),
        ('gbrqEnd', ''),
        ('sxrqStart', ''),
        ('sxrqEnd', ''),
        ('size', '10'),
        ('_', '1647148625862'),
    )

    # 司法解释
    params = (
        ('type', 'sfjs'),
        # ("zdjg", "4028814858a4d78b0158a50f344e0048&4028814858a4d78b0158a50fa2ba004c"), #北京
        # ("zdjg", "4028814858b9b8e50158bed591680061&4028814858b9b8e50158bed64efb0065"), #河南
        # ("zdjg", "4028814858b9b8e50158bec45e9a002d&4028814858b9b8e50158bec500350031"), # 上海
        ('searchType', 'title;accurate;1,5'),
        ('sortTr', 'f_bbrq_s;desc'),
        ('gbrqStart', ''),
        ('gbrqEnd', ''),
        ('sxrqStart', ''),
        ('sxrqEnd', ''),
        ('sort', 'true'),
        ('page', str(page)),
        ('size', '10'),
        ('_', 1647659481879),
    )

    hash_sum = sha1(json.dumps(params).encode()).hexdigest()

    path = f"./__cache__/req_cache/{hash_sum}.json"
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)

    response = requests.get('https://flk.npc.gov.cn/api/',
                            headers=headers, params=params)

    print(f"request {page} {response.status_code}")

    ret = response.json()
    with open(path, "w") as f:
        json.dump(ret, f, ensure_ascii=False, indent=4)

    return ret


def fetchDeails(id: str):
    path = f"./__cache__/req_cache/{id}.json"
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)

    data = {
        'id': id
    }

    response = requests.post(
        'https://flk.npc.gov.cn/api/detail', headers=headers, data=data)

    print(f"request {id} {response.status_code}")

    ret = response.json()
    with open(path, "w") as f:
        json.dump(ret, f, ensure_ascii=False, indent=4)

    time.sleep(1)

    return ret


def fetchWord(path: str):
    filename = os.path.basename(path)
    if os.path.exists(f"./__cache__/words/{filename}"):
        return
    url = "https://wb.flk.npc.gov.cn" + path
    print("fetch", path)
    urllib.request.urlretrieve(url, f"./__cache__/words/{filename}")
    time.sleep(1)

spec_title = None

def parse(arr):
    for item in arr:
        page_id = item["id"]
        title = re.sub("^中华人民共和国", "", item["title"])
        if spec_title and spec_title != title:
            continue
        if title in exists:
            continue
        skip = bool(re.search(r"的(决定|复函|批复|答复|批复)$", title))
        print("T" if skip else "F",title)
        if skip:
            continue
        ret = fetchDeails(page_id)
        try:
            print("paring", title)
            parseDetails(ret)
        except Exception as e:
            print("paring error", title, e)
        if spec_title and spec_title == title:
            exit(1)

FILE_SORT_ORDER = {
    "WORD": 2,
    "HTML": 1,
}

def parseDetails(data):
    result = data["result"]
    body = result["body"]

    files = sorted(body, key=lambda x: FILE_SORT_ORDER[x["type"]] if x["type"] in FILE_SORT_ORDER else 1000)

    if len(files) == 0:
        return

    target = files[0]
    if target["type"] == "WORD":
        fetchWord(target["path"])
        path = f"./__cache__/words/{os.path.basename(target['path'])}"
        if os.path.exists(path):
            parseWord(path, result)
    elif  target["type"] == "HTML":
        if not os.path.exists("./__cache__/html/"):
            os.makedirs("./__cache__/html/")
        path = f"./__cache__/html/{os.path.basename(target['url'])}"
        if not os.path.exists(path):
            fetchHTML(target["url"], path)
        if os.path.exists(path):
            praseHTML(path)

def fetchHTML(url: str, path: str):
    response = requests.get('https://wb.flk.npc.gov.cn' + url,
                            headers=headers)
    response.encoding = "utf8"
    with open(path, "w", encoding="utf8") as f:
        f.write(response.text)
    time.sleep(1)

def praseHTML(path: str):
    print(path)
    with open(path, "r") as f:
        data = f.read()

    bs4 = BeautifulSoup(data)
    title = bs4.title.text
    parts = bs4.find("div", class_="law-content").find_all("p")
    content = map(lambda x:x.text.replace("\xa0", " ") ,parts)
    content = filter(lambda x:x.strip() and not title.startswith(x) and not title.endswith(x), content)
    content = list(content)

    parseContent(title, content[0], content[1:])

zh_nums = "[一二三四五六七八九十零百千万1234567890]+"

indnet_reg = [
    f"^第{zh_nums}编",
    f"^第{zh_nums}章",
    f"^第{zh_nums}节",
]

line_reg = indnet_reg + [
    f"^第{zh_nums}条",
    # f"^{zh_nums}、"
]

def isStartLine(line):
    for reg in line_reg:
        if re.match(reg, line):
            return True


def parseWord(path, result):
    f = open(path, 'rb')
    document = Document(f)
    f.close()
    title = result["title"].strip()

    desc = ""
    content = []
    isDesc = False

    lines = list(
        filter(
            lambda x:x,
            map(
                lambda x:x.text.strip(),
                document.paragraphs
            )
        )
    )

    hasDesc = False
    for n, line in enumerate(lines):
        # 信息行
        if re.match(r"^[（\(]\d{4,4}年\d{1,2}月\d{1,2}日", line):
            isDesc = True
            hasDesc = True

        if isDesc:
            desc += line
        elif n > 0 and hasDesc:
            content.append(line)

        # 信息行结束
        if isDesc and re.search("[）\)]$", line):
            isDesc = False
        if isDesc and re.search(r"目.*录", line):
            isDesc = False
        if isDesc and isStartLine(line):
            isDesc = False

        if not hasDesc and re.search("^法释", line):
            hasDesc = True

    parseContent(title, desc, content)


line_start = f"""^({"|".join(map(lambda x: f"({x})".replace(zh_nums, "一"), line_reg))})"""
remove_sub = [
    "^（",
    "^\(",
    "）$",
    "\)$",
    "^根据",
    "^自",
]

def parseContent(title, desc: str, content):
    simple_title = title.replace("中华人民共和国", "")
    if simple_title in exists:
        return
    subPath = ""
    for line in category:
        if simple_title in line["title"]:
            subPath = line["category"] + "/"
            break
    p = f"./__cache__/out/{subPath}"
    if not os.path.exists(p):
        os.makedirs(p)

    path = f"{p}/{simple_title}.md"
    if os.path.exists(path):
        return

    descArr = re.split("[，、　 ]", desc.strip("（）()"))
    descArr = list(filter(lambda x: x, descArr))
    for i in range(len(descArr)):
        line = descArr[i]
        for pattern in remove_sub:
            line = re.sub(pattern, "", line)
        line = re.sub("^(\d{4,4}年\d{1,2}月\d{1,2}日)",
                        lambda x: x.group(0) + " ", line)
        line = line.replace("起施行", "施行")
        descArr[i] = line
    # print(descArr)

    menu_start = False
    menu_at = -1
    pattern = ""
    filtered_content = []
    skip = False
    for i in range(len(content)):
        line = content[i]
        if menu_at >= 0 and i == menu_at + 1:
            pattern = line
            continue

        if re.match("目.*录", line):
            menu_start = True
            menu_at = i
            continue

        if line == pattern or (menu_start and re.match(line_start, line)):
            menu_start = False

        if re.match("公.*告", line):
            skip = True

        if re.match("^附", line):
            break

        if not menu_start and not skip:
            filtered_content.append(line)

        if skip and re.match("法释", line):
            skip = False

    content = filtered_content

    if spec_title:
        return
    with open(path, "w") as f:
        f.write("# " + title + "\n\n")

        for line in descArr:
            f.write(line + "\n\n")

        f.write("<!-- INFO END -->\n\n")
        regx = []
        for line in content:
            for r in indnet_reg:
                if r not in regx and re.match(r, line):
                    regx.append(r)
                    break
        for line in content:
            flag = False
            for indent, r in enumerate(regx, 2):
                if re.match(r, line):
                    f.write(("#" * indent + " ") + line + "\n\n")
                    flag = True
                    break
            if not flag:
                f.write(line + "\n\n")


def main():
    for i in range(60):
        ret = requestPage(i + 1)
        parse(ret["result"]["data"])


if __name__ == "__main__":
    main()

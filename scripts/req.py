import glob
import json
import os
import re
import time
import urllib.request
from hashlib import sha1
from typing import List

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
             0], glob.glob("./**/*.md", recursive=True)))


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
        ('xlwj', ['02', '03', '04', '05', '06', '07', '08']),
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
    # params = (
    #     ('type', 'sfjs'),
    #     ('searchType', 'title;accurate'),
    #     ('sortTr', 'f_bbrq_s;desc'),
    #     ('gbrqStart', ''),
    #     ('gbrqEnd', ''),
    #     ('sxrqStart', ''),
    #     ('sxrqEnd', ''),
    #     ('sort', 'true'),
    #     ('page', str(page)),
    #     ('size', '10'),
    #     ('_', 1647659481879),
    # )

    hash_sum = sha1(json.dumps(params).encode()).hexdigest()

    path = f"./__cache__/{hash_sum}.json"
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
    path = f"./__cache__/{id}.json"
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
    if os.path.exists(f"./__cache__/{filename}"):
        return
    url = "https://wb.flk.npc.gov.cn" + path
    print("fetch", path)
    urllib.request.urlretrieve(url, f"./__cache__/{filename}")
    time.sleep(1)


# bypass = ".*(?:刑法|民法典).*"
num = [0]


def parse(arr):
    for item in arr:
        page_id = item["id"]
        title = re.sub("^中华人民共和国", "", item["title"])
        # if re.match(bypass, title):
        # continue
        if title in exists:
            print("skip", title)
            continue
        # if len(title) > 14:
        #     continue
        num[0] += 1
        ret = fetchDeails(page_id)
        try:
            print("paring", title)
            parseDetails(ret)
        except Exception as e:
            print("paring error", title, e)


def parseDetails(data):
    result = data["result"]
    body = result["body"]
    found = False
    filename = ""
    for file in body:
        if file["type"] == "WORD":
            found = True
            filename = file["path"]
            break

    if found:
        fetchWord(file["path"])
        path = f"./__cache__/{os.path.basename(filename)}"
        if os.path.exists(path):
            parseWord(path, result)
    else:
        print("no word file found")


def parseWord(path, result):
    f = open(path, 'rb')
    document = Document(f)
    f.close()
    title = result["title"].strip()
    desc = []
    content = []
    isDesc = True
    for no, line in enumerate(filter(lambda x: x, map(lambda x: x.text.strip(), document.paragraphs))):
        if no == 0 and len(title) == 0:
            title = line
            continue
        if isDesc:
            desc.append(line)
            if re.match("（\d{4,4}年\d{1,2}月\d{1,2}日", line):
                isDesc = False
            continue
        content.append(line)
    # print(desc)
    parseContent(title, desc, content, result)


zh_nums = "[一二三四五六七八九十零]+"

indnet_reg = [
    f"第{zh_nums}编",
    f"第{zh_nums}章",
    f"第{zh_nums}节",
]


def parseContent(title, desc: List[str], content, result):
    simple_title = title.replace("中华人民共和国", "")
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

    desc = list(map(lambda x: x.strip("（）"),  desc))
    desc_arr = []
    for line in desc:
        subArr = re.split("[，、　]", line)
        if subArr:
            desc_arr += subArr
        else:
            desc_arr += [line]
    desc = desc_arr

    menu_start = False
    menu_at = -1
    pattern = ""
    filtered_content = []
    for i in range(len(content)):
        line = content[i]
        if menu_at >= 0 and i == menu_at + 1:
            pattern = line
            continue

        if re.match("目\s*录", line):
            menu_start = True
            menu_at = i

        if line == pattern or (menu_start and re.match(f"^第{zh_nums}条", line)):
            menu_start = False

        if not menu_start:
            filtered_content.append(line)

    content = filtered_content

    with open(path, "w") as f:
        f.write("# " + title + "\n\n")

        for line in desc:
            if line == title:
                continue
            line = re.sub("^根据", "", line)
            line = re.sub("^自", "", line)
            line = re.sub("^(\d{4,4}年\d{1,2}月\d{1,2}日)",
                          lambda x: x.group(0) + " ", line)
            line = line.replace("起施行", "施行")
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
    print(exists)
    print(category)
    for i in range(60):
        ret = requestPage(i + 1)
        parse(ret["result"]["data"])


if __name__ == "__main__":
    main()

import json
import logging
import os
import re
import sys
import urllib.request
from abc import ABC, abstractmethod
from enum import Enum
from hashlib import md5, sha1
from pathlib import Path
from time import sleep, time
from typing import Any, List, Tuple

import database
import requests
from bs4 import BeautifulSoup
from docx import Document
from docx.document import Document as _Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell, _Row
from docx.text.paragraph import Paragraph

# pip install python-docx
# pip install pysqlite3
# pip install peewee



logger = logging.getLogger("Law")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(message)s")

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger.addHandler(console_handler)


REQUEST_HEADER = {
    "authority": "flk.npc.gov.cn",
    "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="99", "Microsoft Edge";v="99"',
    "accept": "application/json, text/javascript, */*; q=0.01",
    "x-requested-with": "XMLHttpRequest",
    "sec-ch-ua-mobile": "?0",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36 Edg/99.0.1150.39",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
    "referer": "https://flk.npc.gov.cn/fl.html",
    "accept-language": "en-AU,en-GB;q=0.9,en;q=0.8,en-US;q=0.7,zh-CN;q=0.6,zh;q=0.5",
    "cookie": "yfx_c_g_u_id_10006696=_ck22022520424713255117764923111; cna=NdafGk8tiAgCAd9IPxhfROag; yfx_f_l_v_t_10006696=f_t_1645792967326__r_t_1646401808964__v_t_1646401808964__r_c_5; Hm_lvt_54434aa6770b6d9fef104d146430b53b=1646407223,1646570042,1646666110,1647148584; acw_tc=75a1461516471485843844814eb808af266b8ede0e0502ec1c46ab1581; Hm_lpvt_54434aa6770b6d9fef104d146430b53b=1647148626",
}


def find(f, arr: List[Any]) -> Any:
    for item in arr:
        if f(item):
            return item
    raise Exception("not found")


NUMBER_RE = "[一二三四五六七八九十零百千万1234567890]"

INDENT_RE = [
    "序言",
    f"^第{NUMBER_RE}+编",
    f"^第{NUMBER_RE}+章",
    f"^第{NUMBER_RE}+节",
    "^([一二三四五六七八九十零百千万]+、.{1,15})[^。；：]$",
]

LINE_RE = INDENT_RE + [f"^第{NUMBER_RE}+条"]


DESC_REMOVE_PATTERNS = [
    "^（",
    "^\(",
    "）$",
    "\)$",
    "^根据",
    "^自",
]

line_start = f"""^({"|".join(map(lambda x: f"({x})".replace(NUMBER_RE, "一"), filter(lambda x: "节" not in x, LINE_RE)))})"""


def isStartLine(line: str):
    for reg in LINE_RE:
        if re.match(reg, line):
            return True
    return False


class CacheType(Enum):
    WebPage = "req_cache"
    WordDocument = "words"
    HTMLDocument = "html"


class CacheManager(object):
    def __init__(self) -> None:
        self.base_path = Path("./__cache__")

    def path(self, key: str, type: CacheType, filetype=None) -> Path:
        if filetype:
            key = f"{key}.{filetype}"
        p: Path = self.base_path / type.value
        if not p.exists():
            p.mkdir()  # FileNotFoundError: [Errno 2] No such file or directory: '__cache__/req_cache'
        return p / key

    def is_exists(self, key: str, type: CacheType, filetype=None):
        full_path = self.path(key, type, filetype)
        return full_path.exists(), full_path

    def get(self, key: str, type: CacheType, filetype=None):
        full_path = self.path(key, type, filetype)
        if not full_path.exists():
            return None
        try:
            with open(full_path, "r") as f:
                if filetype == "json":
                    return json.load(f)
                return f.read()
        except Exception as e:
            logger.error(e)
        return None

    def set(self, key: str, type: CacheType, data: Any, filetype=None):
        full_path = self.path(key, type, filetype)
        with open(full_path, "w") as f:
            if filetype == "json":
                json.dump(data, f, ensure_ascii=False, indent=4)
            else:
                f.write(data if isinstance(data, str) else str(data))

    def write_law(self, path: Path, data: List[str]):
        out_path = self.base_path / "out"
        if not out_path.exists():
            out_path.mkdir()
        full_path = out_path / path
        folder_path = full_path.parents[0]
        if not folder_path.exists():
            folder_path.mkdir()
        with open(full_path, "w") as f:
            result = "\n\n".join(data)
            result = result.replace("<!-- TABLE -->\n", "<!-- TABLE -->")
            result = result.replace("\n<!-- TABLE END -->", "<!-- TABLE END -->")
            result = result.replace("|\n\n|", "|\n|")
            result = re.sub("\n{2,}", "\n\n", result)
            f.write(result)


class RequestManager(object):
    def __init__(self) -> None:
        self.cache = CacheManager()
        self.params = []
        self.req_time = 1647659481879
        self.searchType = "1,9"

    def getLawList(self, page=1):
        params = self.params + [
            ("searchType", f"title;accurate;{self.searchType}"),
            ("sortTr", "f_bbrq_s;desc"),
            ("gbrqStart", ""),
            ("gbrqEnd", ""),
            ("sxrqStart", ""),
            ("sxrqEnd", ""),
            ("sort", "true"),
            ("page", str(page)),
            ("size", "10"),
            ("_", self.req_time),
        ]

        cache_key = sha1(json.dumps(params).encode()).hexdigest()

        if cache := self.cache.get(cache_key, CacheType.WebPage, "json"):
            return cache

        response = requests.get(
            "https://flk.npc.gov.cn/api/", headers=REQUEST_HEADER, params=params
        )
        sleep(1)
        logger.debug(f"requesting [{response.status_code}] {self.params} page={page} ")

        ret = response.json()
        self.cache.set(cache_key, CacheType.WebPage, ret, "json")
        return ret

    def get_law_detail(self, law_id: str):
        if cache := self.cache.get(law_id, CacheType.WebPage, "json"):
            return cache
        logger.debug(f"getting law detail {law_id}")
        ret = requests.post(
            "https://flk.npc.gov.cn/api/detail",
            headers=REQUEST_HEADER,
            data={"id": law_id},
        )
        sleep(1)
        ret = ret.json()
        self.cache.set(law_id, CacheType.WebPage, ret, "json")
        return ret

    def get_html(self, url) -> str:
        cache_key = os.path.basename(url)
        if cache := self.cache.get(cache_key, CacheType.HTMLDocument, "html"):
            return cache
        logger.debug(f"getting law html file {url}")
        response = requests.get(
            "https://wb.flk.npc.gov.cn" + url, headers=REQUEST_HEADER
        )
        sleep(1)
        response.encoding = "utf8"
        ret = response.text
        self.cache.set(cache_key, CacheType.HTMLDocument, ret, "html")
        return ret

    def get_word(self, url) -> Document:
        filename = os.path.basename(url)
        cache_key = filename.split(".")[0]

        ok, path = self.cache.is_exists(cache_key, CacheType.WordDocument, "docx")
        if not ok:
            if not re.match(".*docx$", filename):
                return None

            logger.debug(f"getting law word file {url}")
            url = "https://wb.flk.npc.gov.cn" + url

            try:
                urllib.request.urlretrieve(url, path)
                sleep(1)
            except Exception as e:
                logger.error(e)
                return None

        with open(path, "rb") as f:
            try:
                return Document(f)
            except:
                return None


class Parser(ABC):
    def __init__(self, parse_type) -> None:
        super().__init__()
        self.request = RequestManager()
        self.parse_type = parse_type

    @abstractmethod
    def parse(self, result, detail) -> Tuple[str, str, List[str]]:
        pass

    def __eq__(self, __o: object) -> bool:
        return __o == self.parse_type


class WordParser(Parser):
    def __init__(self) -> None:
        super().__init__("WORD")

    def iter_block_items(self, parent):
        """
        Generate a reference to each paragraph and table child within *parent*,
        in document order. Each returned value is an instance of either Table or
        Paragraph. *parent* would most commonly be a reference to a main
        Document object, but also works for a _Cell object, which itself can
        contain paragraphs and tables.
        """
        if isinstance(parent, _Document):
            parent_elm = parent.element.body
        elif isinstance(parent, _Cell):
            parent_elm = parent._tc
        elif isinstance(parent, _Row):
            parent_elm = parent._tr
        else:
            raise ValueError("something's not right")
        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def parse(self, result, detail) -> Tuple[str, str, List[str]]:
        document = self.request.get_word(detail["path"])
        if not document:
            logger.warning(f"document {detail['path']} not exists")
            return

        title = result["title"].strip()

        desc = ""
        content = []
        isDesc = False

        lines = list(filter(lambda x: x, self.iter_block_items(document)))

        def write_row(row):
            arr = ["| "]
            for cell in row.cells:
                text = "\n".join([p.text for p in cell.paragraphs])
                arr.append(f"{text}  |")
            content.append("".join(arr))
            return len(arr) - 1

        hasDesc = False
        for n, line in enumerate(lines):
            if isinstance(line, Table):
                content.append("<!-- TABLE -->")
                table = line

                size = write_row(table.rows[0])
                content.append("".join(["|"] + ["-----|"] * size))

                """
                | Item         | Price     | # In stock |
                |--------------|-----------|------------|
                | Juicy Apples | 1.99      | *7*        |
                | Bananas      | **1.89**  | 5234       |
                """

                for row in table.rows[1:]:
                    write_row(row)
                content.append("<!-- TABLE END -->")
                continue

            if isinstance(line, Paragraph):
                line = line.text.strip()

            # 信息行
            if re.match(r"[（\(]\d{4,4}年\d{1,2}月\d{1,2}日", line):
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

        return title, desc, content


class HTMLParser(Parser):
    def __init__(self) -> None:
        super().__init__("HTML")

    def parse(self, result, detail) -> Tuple[str, str, List[str]]:
        html_data = self.request.get_html(detail["url"])
        if not html_data:
            return

        bs4 = BeautifulSoup(html_data, features="lxml")
        title = bs4.title.text
        parts = bs4.find("div", class_="law-content").find_all("p")
        content = map(lambda x: x.text.replace("\xa0", " ").strip(), parts)
        content = filter(lambda x: x, content)
        content = filter(
            lambda x: not title.startswith(x) and not title.endswith(x), content
        )
        content = list(content)
        if not title and re.match("^中华人民共和国", content[0]):
            title = content[0]
            content = content[1:]
        return title, content[0], content[1:]


class ContentParser(object):
    def __filter_content(self, content: List[str]) -> List[str]:
        menu_start = False
        menu_at = -1
        pattern = ""
        filtered_content = []
        skip = False
        pattern_re = None

        for i in range(len(content)):
            line = content[i].replace("\u3000", " ").replace("　", " ")
            line = re.sub("\s+", " ", line)
            if menu_at >= 0 and i == menu_at + 1:
                pattern = line

                for r in INDENT_RE:
                    if re.match(r, line):
                        pattern_re = r.replace(NUMBER_RE, "一")
                        break
                continue

            if re.match("目.*录", line):
                menu_start = True
                menu_at = i
                continue

            if line == pattern:
                menu_start = False

            if menu_start and pattern_re:
                if re.match(pattern_re, line):
                    menu_start = False
            elif menu_start and not pattern_re:
                if re.match(line_start, line):
                    menu_start = False

            if i < 40 and re.match("公\s*告", line):
                skip = True

            # if re.match("^附", line):
            #     break
            if not menu_start and not skip:
                content_line = re.sub(
                    f"^(第{NUMBER_RE}{{1,6}}[条章节篇](?:之{NUMBER_RE}{{1,2}})*)\s*",
                    lambda x: x.group(0).strip() + " ",
                    line.strip(),
                )
                filtered_content.append(content_line)

            if skip and re.match("法释", line):
                skip = False

        return filtered_content

    def __filter_desc(self, desc: str) -> List[str]:
        desc_arr = re.findall(
            r"(\d{4}年\d{1,2}月\d{1,2}日.*?(?:(?:根据)|(?:通过)|(?:公布)|(?:施行)|(?:）)|(?:　)))",
            desc,
        )
        desc_arr = map(
            lambda line: re.sub(
                "^(\d{4,4}年\d{1,2}月\d{1,2}日)", lambda x: x.group(0) + " ", line
            ),
            desc_arr,
        )
        desc_arr = map(lambda x: x.replace("起施行", "施行"), desc_arr)
        return list(desc_arr)

    def __get_indents(self, content: List[str]) -> List[str]:
        ret = []
        for line in content:
            for r in INDENT_RE:
                if r not in ret and re.match(r, line):
                    ret.append(r)
                    break
        return ret

    def parse(self, result, title, desc, content: List[str]) -> List[str]:
        desc = self.__filter_desc(desc)
        content = self.__filter_content(content)
        if len(content) == 0:
            logger.warning(f"{title} has no content")
            return

        indents = self.__get_indents(content)

        ret = []

        ret.append(f"# {title}")
        ret += desc
        ret.append(f"<!-- INFO END -->")

        for line in content:
            flag = False
            for indent, r in enumerate(indents, 2):
                if re.match(r, line):
                    ret.append(f"{'#' * indent} {line}")
                    flag = True
                    break
            if not flag:
                ret.append(line)
        return ret


class LawParser(object):
    def __init__(self) -> None:
        self.request = RequestManager()
        self.spec_title = None
        self.parser = [
            HTMLParser(),
            WordParser(),
        ]
        self.content_parser = ContentParser()
        self.cache = CacheManager()
        self.categories = []
        # self.db = database.Database()
        self.__init()

    def __init(self):
        categories = []
        with open("./cate.txt", "r") as f:
            title = ""
            for line in f.readlines():
                line = line.strip()
                if re.match("^[一二三四五六七八九十]、", line):
                    title = line.split("、")[1]
                    continue
                categories.append(
                    {
                        "title": line,
                        "category": title,
                    }
                )
        self.categories = categories

    def __reorder_files(self, files):
        # 必须有 parser
        files = list(
            filter(
                lambda x: x["type"] in self.parser,
                files,
            )
        )

        if len(files) == 0:
            return []

        if len(files) > 1:
            # 按照 parser 的位置排序， 优先使用级别
            files = sorted(files, key=lambda x: self.parser.index(x["type"]))

        return files

    def is_bypassed_law(self, item) -> bool:
        title = item["title"].replace("中华人民共和国", "")
        if self.spec_title and title in self.spec_title:
            return False
        if re.search(r"的(决定|复函|批复|答复|批复)$", title):
            return True
        # laws = self.db.get_laws(title, item["publish"])
        # laws = list(laws)
        # if laws:
        #     return True
        return False

    def parse_law(self, item):
        detail = self.request.get_law_detail(item["id"])
        result = detail["result"]
        title = result["title"]
        files = self.__reorder_files(result["body"])
        logger.debug(f"parsing {title}")
        if len(files) == 0:
            return

        for target_file in files:
            parser: Parser = find(lambda x: x == target_file["type"], self.parser)

            ret = parser.parse(result, target_file)
            if not ret:
                logger.error(f"parsing {title} error")
                continue
            _, desc, content = ret

            filedata = self.content_parser.parse(result, title, desc, content)
            if not filedata:
                continue

            output_path = self.__get_law_output_path(title, item["publish"])
            logger.debug(f"parsing {title} success")
            self.cache.write_law(output_path, filedata)

    def parse_file(self, file_path, publish_at=None):
        result = {}
        with open(file_path, "r") as f:
            data = list(filter(lambda x: x, map(lambda x: x.strip(), f.readlines())))
        title = data[0]
        filedata = self.content_parser.parse(result, title, data[1], data[2:])
        if not filedata:
            return
        output_path = self.__get_law_output_path(title, publish_at)
        logger.debug(f"parsing {title} success")
        self.cache.write_law(output_path, filedata)

    def get_file_hash(self, title, publish_at=None) -> str:
        _hash = md5()
        _hash.update(title.encode("utf8"))
        if publish_at:
            _hash.update(publish_at.encode("utf8"))
        return _hash.digest().hex()[0:8]

    def __get_law_output_path(self, title, publish_at: str) -> Path:
        title = title.replace("中华人民共和国", "")
        ret = Path(".")
        for category in self.categories:
            if title in category["title"]:
                ret = ret / category["category"]
                break
        # hash_hex = self.get_file_hash(title, publish_at)
        if publish_at:
            output_name = f"{title}({publish_at}).md"
        else:
            output_name = f"{title}.md"
        return ret / output_name

    def lawList(self):
        for i in range(1, 60):
            ret = self.request.getLawList(i)
            arr = ret["result"]["data"]
            if len(arr) == 0:
                break
            yield from arr

    def run(self):
        for i in range(1, 20):
            ret = self.request.getLawList(i)
            arr = ret["result"]["data"]
            if len(arr) == 0:
                break
            for item in arr:
                if "publish" in item and item["publish"]:
                    item["publish"] = item["publish"].split(" ")[0]
                if self.is_bypassed_law(item):
                    continue
                # if item["status"] == "9":
                # continue
                self.parse_law(item)
                if self.spec_title is not None:
                    exit(1)


def main():
    req = LawParser()

    args = sys.argv[1:]
    if args:
        req.parse_file(args[0], args[1])
        return
    req.request.searchType = "1,3"
    req.request.params = [
        # ("type", "公安部规章")
        # ('xlwj', ['02', '03', '04', '05', '06', '07', '08']),  # 法律法规
        #  ("fgbt", "最高人民法院、最高人民检察院关于执行《中华人民共和国刑法》确定罪名"),
        # ("fgxlwj", "xzfg"),  # 行政法规
        # ('type', 'sfjs'),
        # ("zdjg", "4028814858a4d78b0158a50f344e0048&4028814858a4d78b0158a50fa2ba004c"), #北京
        # ("zdjg", "4028814858b9b8e50158bed591680061&4028814858b9b8e50158bed64efb0065"), #河南
        # ("zdjg", "4028814858b9b8e50158bec45e9a002d&4028814858b9b8e50158bec500350031"), # 上海
        # ("zdjg", "4028814858b9b8e50158bec5c28a0035&4028814858b9b8e50158bec6abbf0039"), # 江苏
        # ("zdjg", "4028814858b9b8e50158bec7c42f003d&4028814858b9b8e50158beca3c590041"), # 浙江
        # ("zdjg", "4028814858b9b8e50158bed40f6d0059&4028814858b9b8e50158bed4987a005d"),  # 山东
        # ("zdjg", "4028814858b9b8e50158bef1d72600b9&4028814858b9b8e50158bef2706800bd"), # 陕西省
        # (
        #     "zdjg",
        #     "4028814858b9b8e50158beda43a50079&4028814858b9b8e50158bedab7ea007d",
        # ),  # 广东
        (
            "zdjg",
            "4028814858b9b8e50158bee5863c0091&4028814858b9b8e50158bee9a3aa0095"
        ) # 重庆
    ]
    # req.request.req_time = 1647659481879
    req.request.req_time = int(time() * 1000)
    # req.spec_title = "反有组织犯罪法"
    req.run()


if __name__ == "__main__":
    main()

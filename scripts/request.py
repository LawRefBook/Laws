import logging
import os
import re
import sys
from hashlib import md5
from pathlib import Path
from time import time
from typing import Any, List

from common import LINE_RE
from manager import CacheManager, RequestManager
from parsers import ContentParser, HTMLParser, Parser, WordParser

logger = logging.getLogger("Law")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(message)s")

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger.addHandler(console_handler)


def find(f, arr: List[Any]) -> Any:
    for item in arr:
        if f(item):
            return item
    raise Exception("not found")


def isStartLine(line: str):
    for reg in LINE_RE:
        if re.match(reg, line):
            return True
    return False


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
        for i in range(1, 5):
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

    def remove_duplicates(self):
        p = self.cache.OUTPUT_PATH
        lookup = Path("../")
        for file_path in p.glob("*.md"):
            lookup_files = lookup.glob(f"**/**/{file_path.name}")
            lookup_files = filter(lambda x: "scripts" not in x.parts, lookup_files)
            lookup_files = list(lookup_files)
            if len(lookup_files) > 0:
                os.remove(file_path)
                print(f"remove {file_path}")


def main():
    req = LawParser()
    args = sys.argv[1:]
    if args:
        req.parse_file(args[0], args[1])
        return
    req.request.searchType = "1,3"
    req.request.params = [
        # ("type", "公安部规章")
        ("xlwj", ["02", "03", "04", "05", "06", "07", "08"]),  # 法律法规
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
        # (
        #     "zdjg",
        #     "4028814858b9b8e50158bee5863c0091&4028814858b9b8e50158bee9a3aa0095",
        # )  # 重庆
    ]
    # req.request.req_time = 1647659481879
    req.request.req_time = int(time() * 1000)
    # req.spec_title = "反有组织犯罪法"
    try:
        req.run()
    except KeyboardInterrupt:
        logger.info("keyboard interrupt")
    finally:
        req.remove_duplicates()


if __name__ == "__main__":
    main()

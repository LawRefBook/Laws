import logging
import re
from typing import List

from common import INDENT_RE, LINE_START, NUMBER_RE

logger = logging.getLogger(__name__)


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
                if re.match(LINE_START, line):
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

    def parse(self, result, title: str, desc, content: List[str]) -> List[str]:
        desc = self.__filter_desc(desc)
        content = self.__filter_content(content)
        if len(content) == 0:
            logger.warning(f"{title} has no content")
            return

        # if title exists in first then line of content, remove it
        if title.strip() in content[:10]:
            content.remove(title.strip())

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

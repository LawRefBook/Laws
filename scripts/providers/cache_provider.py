import logging
import re
import urllib.parse
from enum import Enum
from pathlib import Path
from typing import Dict, List, Set

from common import CACHE_DIR
from providers import net

logger = logging.getLogger(__name__)


class CacheType(Enum):
    WordDocument = "words"
    HtmlPage = "html"
    Epub = "epub"


class CacheManager(object):
    """下载的 Word 原文按 URL 文件名缓存，解析结果写到 out/。列表接口不缓存，否则看不到新法规。"""

    def __init__(self, base_path: Path = CACHE_DIR) -> None:
        self.base_path = base_path

    @property
    def out_path(self) -> Path:
        return self.base_path / "out"

    async def download_binary(self, url: str, type: CacheType, headers=None, filename: str = None) -> Path:
        # https://flkoss.obs-bj2.cucloud.cn/prod/20251128/5f98d6b9eca7456aa8e53a9f73ef7c7e.docx
        # 取 URL 里的文件名 `5f98d6b9eca7456aa8e53a9f73ef7c7e.docx`；URL 里没有文件名时由调用方给
        filename = filename or urllib.parse.urlparse(url).path.split("/")[-1]
        path = self.__get_path(filename, type)
        if path.exists():
            return path
        await net.download(url, path, headers=headers)
        return path

    def __get_path(self, key: str, type: CacheType) -> Path:
        p: Path = self.base_path / type.value
        p.mkdir(parents=True, exist_ok=True)
        return p / key

    def get_all_laws(self) -> Dict[str, Set[str]]:
        """out/ 里已经解析过的法规：{名称: {发布日期}}。"""
        r = re.compile(r"(.+)\((\d{4}-\d{2}-\d{2})\)\.md")
        normalized_laws: Dict[str, Set[str]] = {}
        for f in self.out_path.glob("**/*.md"):
            match = r.match(f.name)
            if match:
                normalized_laws.setdefault(match.group(1), set()).add(match.group(2))
        return normalized_laws

    def write_law(self, path: Path, data: List[str]) -> Path:
        full_path = self.out_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        result = "\n\n".join(data)
        result = result.replace("<!-- TABLE -->\n", "<!-- TABLE -->")
        result = result.replace("\n<!-- TABLE END -->", "<!-- TABLE END -->")
        result = result.replace("|\n\n|", "|\n|")
        result = re.sub("\n{2,}", "\n\n", result)
        full_path.write_text(result, encoding="utf-8")
        return full_path

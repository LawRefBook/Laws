import urllib.parse
from enum import Enum
from pathlib import Path

from lawref.fetch import net
from lawref.paths import CACHE_DIR


class CacheType(Enum):
    """原文按类型放在缓存目录下的子目录里。"""
    WORD = "words"
    HTML = "html"
    EPUB = "epub"


class DownloadCache:
    """下载的原文按文件名缓存，已经下载过的不再下载。列表接口不缓存，否则看不到新法规。"""

    def __init__(self, base_path: Path = CACHE_DIR) -> None:
        self.base_path = base_path

    async def download(self, url: str, kind: CacheType, headers: dict | None = None,
                       filename: str | None = None) -> Path:
        """filename 不传时取 URL 里的文件名，如 https://…/prod/20251128/5f98d6b9….docx 的 `5f98d6b9….docx`。"""
        filename = filename or urllib.parse.urlparse(url).path.split("/")[-1]
        folder = self.base_path / kind.value
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / filename
        if not path.exists():
            await net.download(url, path, headers=headers)
        return path

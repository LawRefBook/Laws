import json
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Any, List

logger = logging.getLogger(__name__)


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
            p.mkdir(parents=True)
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

    @property
    def OUTPUT_PATH(self):
        p = self.base_path / "out"
        if not p.exists():
            p.mkdir(parents=True)
        return p

    def write_law(self, path: Path, data: List[str]):
        full_path = self.OUTPUT_PATH / path
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

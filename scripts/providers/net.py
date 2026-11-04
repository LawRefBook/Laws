import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT = (10, 60)  # 连接、读取，秒


class Session(requests.Session):
    """默认带超时，并对网络错误和 429、5xx 重试。"""

    def __init__(self) -> None:
        super().__init__()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=None,  # POST 的列表查询也重试
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.mount("https://", adapter)
        self.mount("http://", adapter)

    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        return super().request(*args, **kwargs)


session = Session()

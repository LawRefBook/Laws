import json
import os
import re
import urllib.request
from hashlib import sha1
from time import sleep
import logging
import requests
from docx import Document
from manager.cache import CacheManager, CacheType


logger = logging.getLogger(__name__)

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

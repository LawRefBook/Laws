import hashlib
import re

import bs4
from model.law import FetchedDocumentResponse, FetchedLawResponse, LawListItem

from .base import Provider
from .cache_provider import CacheType
from .net import session


class CultureAndTourismDatabaseProvider(Provider):
    BASE_URL = "https://zwgk.mct.gov.cn/zfxxgkml/zcfg/bmgz"
    HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    }

    def fetch(self, page_num=1) -> FetchedLawResponse:
        response = self.__fetch(page_num=page_num)
        soup = bs4.BeautifulSoup(response, "html.parser")
        rows = soup.select("ul.r_content_2022 > li")
        items = []
        pattern = re.compile(r'href="(.*?\.docx?)"')
        for row in rows:
            match = pattern.search(str(row))
            if not match:
                print(f"Cannot find docx link in row: {row}")
                continue
            link = match.group(1)
            title = row.select_one("p.p1 > a").text.strip()
            title_md5 = hashlib.md5(title.encode("utf-8")).hexdigest()
            items.append(
                LawListItem(
                    id=title_md5,
                    title=title,
                    released_by="文化与旅游部",
                    type="部门规章",
                    file_link=link,
                )
            )
        return FetchedLawResponse(
            total=0,
            items=items,
        )

    def fetch_document(self, law: LawListItem) -> FetchedDocumentResponse:
        download_url = f"{self.BASE_URL}/{law.file_link}"
        path = self.cache_manager.download_binary(
            download_url,
            CacheType.WordDocument,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Pragma": "no-cache",
                "Referer": "https://zwgk.mct.gov.cn/zfxxgkml/zcfg/bmgz/index.html",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                "sec-ch-ua": "\"Not:A-Brand\";v=\"99\", \"Google Chrome\";v=\"145\", \"Chromium\";v=\"145\"",
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": "\"macOS\"",
            }
        )
        return FetchedDocumentResponse(law=law, path_to_file=path)

    def __fetch(self, page_num=1) -> str:
        path = f"index_{page_num}.html" if page_num > 1 else "index.html"
        url = self.BASE_URL + "/" + path
        response = session.get(url, headers=self.HEADERS)
        response.encoding = "utf-8"
        response.raise_for_status()
        return response.text

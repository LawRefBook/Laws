"""aiohttp 封装：默认带超时，对网络错误和 429、5xx 重试。

ClientSession 要在事件循环里创建，所以在 `async with client():` 里用 get_json、download：

    async with client():
        data = await get_json("POST", url, json=payload)
"""
import asyncio
import contextlib
import contextvars
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

import aiohttp
import tqdm
from yarl import URL

TIMEOUT = aiohttp.ClientTimeout(sock_connect=10, sock_read=60)
RETRIES = 4          # 第一次失败后再试几次
BACKOFF = 1          # 网络错误依次等 1、2、4、8 秒
# 被限流时整个站点暂停，依次 5、10、20、40 秒。flk.npc.gov.cn 前面有网站防火墙（响应头 WZWS-RAY），
# 请求太快时返回状态码 200 的 HTML 验证页，过一会儿自动解除
BLOCKED_BACKOFF = 5
RETRY_STATUS = {429, 500, 502, 503, 504}
BLOCKED_STATUS = {429}


class BadResponse(aiohttp.ClientError):
    """状态码正常但内容不对，比如被限流时返回空白或 HTML 页面。当作被限流，暂停后重试。"""


# 各站点暂停到什么时候（time.monotonic()）。并发的请求共用一个 IP，一个被限流时都要停
_paused_until: dict = {}


async def _wait_if_paused(host: str) -> None:
    while (delay := _paused_until.get(host, 0) - time.monotonic()) > 0:
        await asyncio.sleep(delay)


def _pause(host: str, delay: float, reason: str) -> None:
    until = time.monotonic() + delay
    if until > _paused_until.get(host, 0):
        _paused_until[host] = until
        tqdm.tqdm.write(f"{host} {reason}，暂停 {delay:g} 秒", file=sys.stderr)


# 网络出错时抛的异常，调用方统一捕获它
NetworkError = (aiohttp.ClientError, asyncio.TimeoutError)
HTTPError = aiohttp.ClientResponseError

_session: contextvars.ContextVar[aiohttp.ClientSession] = contextvars.ContextVar("session")


@contextlib.asynccontextmanager
async def client(limit: int = 16):
    """limit：同时打开的连接数上限。"""
    async with aiohttp.ClientSession(timeout=TIMEOUT, connector=aiohttp.TCPConnector(limit=limit)) as session:
        token = _session.set(session)
        try:
            yield session
        finally:
            _session.reset(token)


def session() -> aiohttp.ClientSession:
    try:
        return _session.get()
    except LookupError:
        raise RuntimeError("要在 `async with net.client():` 里发请求") from None


async def _request(method: str, url: str, handle, **kwargs) -> Any:
    """发请求并用 handle(response) 读取结果。读取到一半断开也算失败，一起重试。"""
    host = URL(url).host or ""
    for attempt in range(RETRIES + 1):
        last = attempt == RETRIES
        await _wait_if_paused(host)
        try:
            async with session().request(method, url, **kwargs) as response:
                if response.status in RETRY_STATUS and not last:
                    retry_after = response.headers.get("Retry-After", "")
                    if response.status in BLOCKED_STATUS:
                        delay = float(retry_after) if retry_after.isdigit() else BLOCKED_BACKOFF * 2 ** attempt
                        _pause(host, delay, f"返回 {response.status}")
                    else:
                        await asyncio.sleep(float(retry_after) if retry_after.isdigit() else BACKOFF * 2 ** attempt)
                    continue
                response.raise_for_status()
                return await handle(response)
        except HTTPError:
            raise
        except BadResponse:
            if last:
                raise
            _pause(host, BLOCKED_BACKOFF * 2 ** attempt, "返回了验证页，可能被限流")
        except NetworkError:
            if last:
                raise
            await asyncio.sleep(BACKOFF * 2 ** attempt)
    raise AssertionError("unreachable")


async def _read_json(response: aiohttp.ClientResponse) -> Any:
    # 有的接口返回 JSON 时 Content-Type 不对，不检查它，直接按内容解析
    text = await response.text()
    try:
        return json.loads(text)
    except ValueError:
        raise BadResponse(f"{response.url} 返回的不是 JSON：{text[:80]!r}") from None


async def get_json(method: str, url: str, **kwargs) -> Any:
    return await _request(method, url, _read_json, **kwargs)


async def download(url: str, path: Path, headers: Optional[dict] = None) -> None:
    """下载到 path。先写临时文件，中断时不会留下半个文件被当成缓存。"""
    tmp = path.with_name(f"{path.name}.{id(asyncio.current_task())}.part")

    async def save(response: aiohttp.ClientResponse):
        with open(tmp, "wb") as f:
            async for chunk in response.content.iter_chunked(65536):
                f.write(chunk)

    try:
        await _request("GET", url, save, headers=headers)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)

"""公开源 HTTP 取数的有限重试，只用于 GET。

取数是幂等的：同一个 GET 重复发出不改变源端，所以重试是安全的。这与“提交结果未知不重试”无关。
那条规则只管数据库写入，写入路径不经过本模块。

只重试两类失败：连接错误与超时（``ConnectionError``、``Timeout``），以及 429、500、502、503、504。
其余状态码（如 400、401、403、404）是请求本身的问题，重试只会重复同样的错误，所以立即原样返回，
由调用方按原逻辑报错。

日志只记主机与路径、第几次、原因，不记查询参数：FRED 的 ``api_key`` 就放在查询参数里。
被抛出的异常消息仍由 requests 生成，带完整 URL。调用方要自行脱敏，不得把它带进错误信息或日志。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import requests

from quantagent.platform.logging.setup import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

logger = get_logger(__name__)

RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def get_with_retry(
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    timeout: float,
    attempts: int = 3,
    backoff_seconds: Sequence[float] = (5, 20),
    sleep: Callable[[float], None] = time.sleep,
    get: Callable[..., requests.Response] = requests.get,
) -> requests.Response:
    """发出 GET，失败时最多尝试 ``attempts`` 次。

    第 n 次失败后等待 ``backoff_seconds[n-1]`` 秒。用尽后：异常类失败抛出最后一次的异常，
    状态码失败返回最后一次的响应，由调用方判断。
    ``get`` 与 ``sleep`` 可注入，便于测试。调用方若需要 monkeypatch ``requests.get``，
    应在调用时传入 ``get=requests.get``，否则默认值在导入时就已绑定。
    """
    if attempts < 1:
        raise ValueError(f"attempts 必须为正整数: {attempts}")
    if len(backoff_seconds) < attempts - 1:
        raise ValueError(f"backoff_seconds 至少需要 {attempts - 1} 个元素: {backoff_seconds!r}")
    host_path = _host_path(url)
    last_error: requests.RequestException | None = None
    last_response: requests.Response | None = None
    for attempt in range(1, attempts + 1):
        last_error = None
        last_response = None
        try:
            response = get(url, params=params, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            # 只记异常类名。异常消息里有完整 URL，会带出查询参数。
            reason = type(exc).__name__
            last_error = exc
        else:
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response
            reason = f"HTTP {response.status_code}"
            last_response = response
        if attempt == attempts:
            logger.warning(
                "GET %s 第 %d/%d 次失败（%s），已用尽重试次数", host_path, attempt, attempts, reason
            )
            break
        wait = backoff_seconds[attempt - 1]
        logger.warning(
            "GET %s 第 %d/%d 次失败（%s），%g 秒后重试", host_path, attempt, attempts, reason, wait
        )
        sleep(wait)
    if last_error is not None:
        raise last_error
    if last_response is None:
        raise RuntimeError("get_with_retry 内部错误：没有任何响应")
    return last_response


def _host_path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.hostname or ''}{parts.path}"

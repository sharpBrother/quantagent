"""公开源 HTTP 取数的有限重试：可重试的错误、立即返回的状态码、用尽后的结果、日志脱敏。零网络。"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
import requests

from quantagent.ingest.sources.http import get_with_retry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_URL = "https://api.example.org/fred/series/observations"
_SECRET = "SECRET-KEY-123"


class ScriptedGet:
    """按脚本依次返回：异常类实例抛出，``int`` 当作状态码返回，其余原样返回。记录每次调用的参数。"""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, int):
            return SimpleNamespace(status_code=item, text="")
        return item


def _ok() -> SimpleNamespace:
    return SimpleNamespace(status_code=200, text="{}")


@pytest.fixture
def warning_messages() -> Iterator[list[str]]:
    """收集 http 模块 logger 的 WARNING 文本。直接挂在 logger 上，不依赖 caplog。

    ``configure_logging`` 会把 ``quantagent`` 的 propagate 设为 False，其他测试跑过它之后，
    caplog 的根 handler 就收不到记录。
    """
    messages: list[str] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    logger = logging.getLogger("quantagent.ingest.sources.http")
    handler = _Collect(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)


def _sleeps() -> tuple[list[float], Callable[[float], None]]:
    recorded: list[float] = []
    return recorded, recorded.append


@pytest.mark.unit
def test_timeout_then_success_returns_the_success_after_one_wait() -> None:
    get = ScriptedGet([requests.ReadTimeout("read timed out"), _ok()])
    waits, sleep = _sleeps()

    response = get_with_retry(_URL, timeout=30, sleep=sleep, get=get)

    assert response.status_code == 200
    assert len(get.calls) == 2
    assert waits == [5]


@pytest.mark.unit
def test_connection_error_then_success_returns_the_success() -> None:
    get = ScriptedGet([requests.ConnectionError("reset"), _ok()])
    waits, sleep = _sleeps()

    response = get_with_retry(_URL, timeout=30, sleep=sleep, get=get)

    assert response.status_code == 200
    assert waits == [5]


@pytest.mark.unit
def test_502_then_success_returns_the_success_after_one_wait() -> None:
    get = ScriptedGet([502, _ok()])
    waits, sleep = _sleeps()

    response = get_with_retry(_URL, timeout=30, sleep=sleep, get=get)

    assert response.status_code == 200
    assert len(get.calls) == 2
    assert waits == [5]


@pytest.mark.unit
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_status_codes_are_retried(status: int) -> None:
    get = ScriptedGet([status, _ok()])
    _, sleep = _sleeps()

    assert get_with_retry(_URL, timeout=30, sleep=sleep, get=get).status_code == 200
    assert len(get.calls) == 2


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_other_status_codes_return_immediately_without_retry(status: int) -> None:
    get = ScriptedGet([status])
    waits, sleep = _sleeps()

    response = get_with_retry(_URL, timeout=30, sleep=sleep, get=get)

    assert response.status_code == status
    assert len(get.calls) == 1
    assert waits == []


@pytest.mark.unit
def test_exhausted_exceptions_raise_the_last_one_with_backoff_between_attempts() -> None:
    first = requests.ReadTimeout("first")
    last = requests.ConnectionError("last")
    get = ScriptedGet([first, requests.ReadTimeout("second"), last])
    waits, sleep = _sleeps()

    with pytest.raises(requests.ConnectionError) as caught:
        get_with_retry(_URL, timeout=30, sleep=sleep, get=get)

    assert caught.value is last
    assert len(get.calls) == 3
    assert waits == [5, 20]


@pytest.mark.unit
def test_exhausted_status_codes_return_the_last_response() -> None:
    get = ScriptedGet([503, 503, 504])
    waits, sleep = _sleeps()

    response = get_with_retry(_URL, timeout=30, sleep=sleep, get=get)

    assert response.status_code == 504
    assert len(get.calls) == 3
    assert waits == [5, 20]


@pytest.mark.unit
def test_non_retryable_exception_propagates_without_retry() -> None:
    get = ScriptedGet([requests.exceptions.InvalidURL("bad")])
    waits, sleep = _sleeps()

    with pytest.raises(requests.exceptions.InvalidURL):
        get_with_retry(_URL, timeout=30, sleep=sleep, get=get)

    assert len(get.calls) == 1
    assert waits == []


@pytest.mark.unit
def test_params_and_timeout_are_passed_on_every_attempt() -> None:
    get = ScriptedGet([502, _ok()])
    _, sleep = _sleeps()

    get_with_retry(_URL, params={"series_id": "CPIAUCSL"}, timeout=12.5, sleep=sleep, get=get)

    assert all(call["params"] == {"series_id": "CPIAUCSL"} for call in get.calls)
    assert all(call["timeout"] == 12.5 for call in get.calls)


@pytest.mark.unit
def test_attempts_of_one_never_waits() -> None:
    get = ScriptedGet([requests.ConnectionError("down")])
    waits, sleep = _sleeps()

    with pytest.raises(requests.ConnectionError):
        get_with_retry(_URL, timeout=30, attempts=1, sleep=sleep, get=get)

    assert waits == []


@pytest.mark.unit
def test_backoff_shorter_than_attempts_is_rejected() -> None:
    with pytest.raises(ValueError, match="backoff_seconds"):
        get_with_retry(_URL, timeout=30, attempts=3, backoff_seconds=(5,), get=ScriptedGet([]))


@pytest.mark.unit
def test_logs_show_host_path_attempt_and_reason_but_never_the_query_string(
    warning_messages: list[str],
) -> None:
    # 模拟 requests 的异常消息：带完整 URL，也就带上查询参数里的 key。
    leaked = requests.ConnectionError(f"Max retries exceeded with url: {_URL}?api_key={_SECRET}")
    get = ScriptedGet([leaked, leaked, leaked])
    _, sleep = _sleeps()

    with pytest.raises(requests.ConnectionError):
        get_with_retry(
            f"{_URL}?api_key={_SECRET}",
            params={"api_key": _SECRET},
            timeout=30,
            sleep=sleep,
            get=get,
        )

    messages = warning_messages
    assert any("api.example.org" in m and "/fred/series/observations" in m for m in messages)
    assert any("第 1/3 次" in m and "ConnectionError" in m for m in messages)
    assert any("第 3/3 次" in m and "已用尽" in m for m in messages)
    joined = "\n".join(messages)
    assert _SECRET not in joined
    assert "api_key" not in joined


@pytest.mark.unit
def test_status_retry_logs_do_not_show_the_query_string(warning_messages: list[str]) -> None:
    get = ScriptedGet([503, _ok()])
    _, sleep = _sleeps()

    get_with_retry(f"{_URL}?api_key={_SECRET}", timeout=30, sleep=sleep, get=get)

    joined = "\n".join(warning_messages)
    assert "HTTP 503" in joined
    assert _SECRET not in joined

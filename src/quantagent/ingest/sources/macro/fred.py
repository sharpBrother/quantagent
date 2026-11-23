"""FRED ``series/observations`` 带版本拉取，即 ALFRED 的全部历史版本。

单次请求的 ``realtime_start=1776-07-04``、``realtime_end=9999-12-31`` 会返回每个观测期的全部版本。
但 FRED 单次请求最多接受 2000 个 vintage date（DFII10 有 5134 个，整段请求返回 400）。
所以这里分三步拉取：

1. ``fred/series/vintagedates`` 取该序列全部 vintage date。
2. 每 2000 个 vintage date 切成一片。第 k 片的窗口是 ``[片内第一个 vintage, 下一片第一个 vintage 的前一天]``，
   最后一片的终点是 ``9999-12-31``。每片请求一次 ``series/observations``（按 ``offset`` 分页取完）。
   片内返回的区间会被窗口截断：``realtime_start`` 被抬到窗口起点，``realtime_end`` 被压到窗口终点。
3. 相邻片里同一版本的两段被窗口切开，``merge_vintage_fragments`` 把它们接回去；合并后
   ``check_vintage_invariants`` 核对三条不变量，任一不满足即抛 ``SourceFetchError``，不写库。

另外再不带 realtime 参数请求一次当前值，作为不变量 (c) 的独立核对。

``value`` 是字符串。``"."`` 或空串是源端"该日无发布值"，记 NULL 并保留该行，与旧仓
``fred_observation_etl.py`` 一致；缺行与缺值不是一回事。其余值按 ``Decimal`` 解析，超过 8 位小数直接报错，
不四舍五入，否则同一份源数据可能悄悄改变下游读到的数值。
API key 只放在请求参数里。requests 的异常消息含完整 URL，也就含 api_key，所以在 adapter 里
把异常转成只带异常类名的 ``SourceFetchError``，并且不用 ``raise ... from`` 链住原异常。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any, NamedTuple, Protocol

import requests

from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.sources.http import get_with_retry

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_VINTAGE_DATES_URL = "https://api.stlouisfed.org/fred/series/vintagedates"

# 迁移与日更的全部序列。新增序列要先确认它的 PIT 口径与 visibility 规则。
# CPALTT01CNM659N 是 OECD MEI 中国 CPI 同比（月频），作中国实际利率的通胀代理（2026-11-23
# 负责人同意，见 docs/research/erp-rate-anchor.md）。可见日仍取 ALFRED 首个 realtime_start；
# 该序列 ALFRED 版本从 2013-06 起，源端停在 2025-04。
# 德国、日本 10 年期（IRLTLT01DEM156N、IRLTLT01JPM156N）有超过 8 位小数的值，待裁定后再加。
FRED_SERIES: tuple[str, ...] = ("DFII10", "T10YIE", "CPIAUCSL", "CPALTT01CNM659N")

# 与 0018_macro_source_tables.sql 的 source 列配套。契约 yaml 的 source 描述已与此一致。
SOURCE_LABEL = "fred.series_observations"

REALTIME_START = "1776-07-04"
REALTIME_END = "9999-12-31"
# 开放区间的终点：当前仍有效的版本。与 REALTIME_END 是同一个日期的两种表示。
OPEN_END = date(9999, 12, 31)
_ONE_DAY = timedelta(days=1)

# FRED 对单次 observations 请求能接受的 vintage date 上限。超过即 400。
VINTAGE_SHARD_SIZE = 2000
VINTAGE_DATES_PAGE_LIMIT = 10_000
PAGE_LIMIT = 100_000

# FRED 对单个 key 有请求频率限制。两次请求的起点至少相隔 1 秒，干跑与日更共用这一条底线。
MIN_REQUEST_INTERVAL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30.0

_VALUE_QUANTUM = Decimal("0.00000001")
# DECIMAL(18,8)：整数部分最多 10 位，绝对值必须严格小于 10^10。
_VALUE_ABS_LIMIT = Decimal("10000000000")
_MISSING_VALUES = frozenset({"", "."})
_ISO_LEN = 10
_HTTP_OK = 200


class FredHttpResponse(NamedTuple):
    status_code: int
    body: str


class FredHttp(Protocol):
    """HTTP 端口。测试注入假实现；真实实现见 ``RequestsFredHttp``。"""

    def get(self, url: str, params: Mapping[str, str]) -> FredHttpResponse: ...


class RequestsFredHttp:
    """真实 HTTP 适配器，两次请求之间强制至少 ``MIN_REQUEST_INTERVAL_SECONDS`` 秒。
    瞬时失败按 ``get_with_retry`` 重试，重试等待不计入上面的节流间隔。
    ``sleep`` 与 ``clock`` 用于节流，``retry_sleep`` 用于重试等待，都可注入，便于测试而不真等。
    """

    def __init__(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._sleep = sleep
        self._clock = clock
        self._retry_sleep = retry_sleep
        self._last_started: float | None = None

    def get(self, url: str, params: Mapping[str, str]) -> FredHttpResponse:
        if self._last_started is not None:
            wait = MIN_REQUEST_INTERVAL_SECONDS - (self._clock() - self._last_started)
            if wait > 0:
                self._sleep(wait)
        self._last_started = self._clock()
        try:
            # get=requests.get 在调用时取值，测试 monkeypatch requests.get 才能生效。
            response = get_with_retry(
                url,
                params=dict(params),
                timeout=REQUEST_TIMEOUT_SECONDS,
                sleep=self._retry_sleep,
                get=requests.get,
            )
        except requests.RequestException as exc:
            failure = type(exc).__name__
        else:
            return FredHttpResponse(status_code=response.status_code, body=response.text)
        # 在 except 之外抛出，不带原异常的 __context__，原异常里的 URL 不会进入任何 traceback。
        raise SourceFetchError(f"FRED 请求失败: {failure}")


@dataclass(frozen=True)
class VintageWindow:
    """一片的 realtime 窗口，两端都含。"""

    start: date
    end: date


class VintageFragment(NamedTuple):
    """片内返回的一段区间。``shard`` 是它所在窗口在 ``plan_vintage_windows`` 结果里的下标。"""

    shard: int
    row: Mapping[str, object]


@dataclass(frozen=True)
class FredVintageFetch:
    """一个序列的全部版本。``rows`` 不含 ``ingested_at``，由作业在同一采集时刻补上。

    ``pages`` 是各片 ``series/observations`` 的页数合计，不含当前值核对请求。
    ``requests`` 是本序列全部 HTTP 请求次数：vintagedates、各片分页、当前值核对分页。
    ``fragments`` 是合并前的片内区间行数，``rows`` 是合并后的行数。
    """

    series_id: str
    vintage_dates: int
    shards: int
    pages: int
    requests: int
    fragments: int
    rows: tuple[dict[str, object], ...]


def fetch_observation_vintages(
    series_id: str,
    *,
    api_key: str,
    http: FredHttp,
    page_limit: int = PAGE_LIMIT,
    shard_size: int = VINTAGE_SHARD_SIZE,
) -> FredVintageFetch:
    """拉取一个序列的全部历史版本：分片取数、合并区间、校验不变量。任一步失败都不返回部分结果。

    ``shard_size`` 默认是 FRED 的上限，只用于测试：调小它可以在短序列上验证合并逻辑。
    """
    sid = _require_series(series_id)
    key = api_key.strip()
    vintages, vintage_requests = _fetch_vintage_dates(sid, api_key=key, http=http)
    windows = plan_vintage_windows(vintages, shard_size=shard_size)
    fragments: list[VintageFragment] = []
    observation_requests = 0
    for index, window in enumerate(windows):
        paged = _fetch_paged(
            http,
            url=FRED_OBSERVATIONS_URL,
            params=_observation_params(sid, api_key=key, window=window),
            api_key=key,
            item_key="observations",
            page_limit=page_limit,
            label=f"{sid} observations",
        )
        observation_requests += paged.requests
        fragments.extend(
            VintageFragment(shard=index, row=_to_row(item, series_id=sid)) for item in paged.items
        )
    current = _fetch_paged(
        http,
        url=FRED_OBSERVATIONS_URL,
        params=_observation_params(sid, api_key=key, window=None),
        api_key=key,
        item_key="observations",
        page_limit=page_limit,
        label=f"{sid} current",
    )
    current_values = _current_values(current.items, series_id=sid)
    rows = merge_vintage_fragments(fragments, windows)
    check_vintage_invariants(rows, current_values)
    return FredVintageFetch(
        series_id=sid,
        vintage_dates=len(vintages),
        shards=len(windows),
        pages=observation_requests,
        requests=vintage_requests + observation_requests + current.requests,
        fragments=len(fragments),
        rows=tuple(rows),
    )


def plan_vintage_windows(
    vintages: Sequence[date],
    *,
    shard_size: int = VINTAGE_SHARD_SIZE,
) -> tuple[VintageWindow, ...]:
    """把有序、不重复的 vintage date 切成片，每片最多 ``shard_size`` 个。纯函数。

    第 k 片的窗口起点是它的第一个 vintage，终点是下一片第一个 vintage 的前一天。
    最后一片的终点是 ``9999-12-31``。这样每个版本的 ``realtime_start`` 都落在它自己那一片里。
    """
    if not vintages:
        raise SourceFetchError("FRED 没有 vintage date，无法分片")
    if shard_size < 1:
        raise ValueError(f"shard_size 必须为正整数: {shard_size}")
    if any(later <= earlier for earlier, later in pairwise(vintages)):
        raise SourceFetchError("FRED vintage date 必须严格递增")
    starts = list(vintages[::shard_size])
    windows: list[VintageWindow] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] - _ONE_DAY if index + 1 < len(starts) else OPEN_END
        windows.append(VintageWindow(start=start, end=end))
    return tuple(windows)


def merge_vintage_fragments(
    fragments: Sequence[VintageFragment],
    windows: Sequence[VintageWindow],
) -> list[dict[str, object]]:
    """把被窗口切开的同一版本接回去。纯函数，不做任何网络访问。

    同一 ``(series_id, observation_date)`` 的两段 ``a``、``b``，按 ``realtime_start`` 排序后相邻，
    且同时满足以下条件时合并成 ``(a.realtime_start, b.realtime_end)``：

    - ``b`` 恰好在 ``a`` 的下一片；
    - ``a.realtime_end`` 等于 ``a`` 所在窗口的终点，``b.realtime_start`` 等于 ``b`` 所在窗口的起点，
      即两段都是在窗口边界上被截断的；
    - 两段的 ``value`` 相等（``None`` 与 ``None`` 也算相等）。

    合并结果继续与下一片比较，所以跨多片的版本能接成一段。
    不满足条件的段原样保留。这里只看窗口与值，不能证明两段确实是同一版本，
    这一点由 ``check_vintage_invariants`` 与按整段一次请求的对拍共同兜底。
    """
    ordered = sorted(fragments, key=_fragment_order)
    merged: list[VintageFragment] = []
    for fragment in ordered:
        if merged and _continues(merged[-1], fragment, windows):
            last = merged[-1]
            merged[-1] = VintageFragment(
                shard=fragment.shard,
                row={**last.row, "realtime_end": fragment.row["realtime_end"]},
            )
        else:
            merged.append(fragment)
    return [dict(fragment.row) for fragment in merged]


def check_vintage_invariants(
    rows: Sequence[Mapping[str, object]],
    current: Mapping[tuple[str, date], object],
) -> None:
    """合并后的三条不变量。任一不满足即抛 ``SourceFetchError``，调用方不得写库。

    (a) 同一 ``(series_id, observation_date)`` 的区间按 ``realtime_start`` 排序后首尾相接、不重叠：
        下一段的 ``realtime_start`` 等于上一段的 ``realtime_end`` 加一天，且每段 ``start <= end``。
    (b) 每个观测日的最后一段 ``realtime_end`` 是 ``9999-12-31``，且只有一段是开放的。
    (c) 每个观测日开放那一段的 ``value``，等于不带 realtime 参数请求得到的当前值；
        两边的观测日集合也必须相同。
    """
    groups: dict[tuple[str, date], list[Mapping[str, object]]] = {}
    for row in rows:
        groups.setdefault((str(row["series_id"]), _as_date(row["observation_date"])), []).append(
            row
        )
    for group_key, segments in groups.items():
        segments.sort(key=lambda row: _as_date(row["realtime_start"]))
        where = f"{group_key[0]}/{group_key[1]:%Y-%m-%d}"
        for previous, following in pairwise(segments):
            if (
                _as_date(following["realtime_start"])
                != _as_date(previous["realtime_end"]) + _ONE_DAY
            ):
                raise SourceFetchError(f"FRED 版本区间不首尾相接或重叠: {where}")
        for segment in segments:
            if _as_date(segment["realtime_start"]) > _as_date(segment["realtime_end"]):
                raise SourceFetchError(f"FRED 版本区间起点晚于终点: {where}")
        open_segments = [s for s in segments if _as_date(s["realtime_end"]) == OPEN_END]
        if _as_date(segments[-1]["realtime_end"]) != OPEN_END or len(open_segments) != 1:
            raise SourceFetchError(f"FRED 最后一段 realtime_end 不是 9999-12-31: {where}")
        if group_key not in current:
            raise SourceFetchError(f"FRED 当前值请求缺少观测日: {where}")
        if open_segments[0]["value"] != current[group_key]:
            raise SourceFetchError(f"FRED 当前版本值与不带 realtime 的当前值不一致: {where}")
    if set(groups) != set(current):
        raise SourceFetchError("FRED 版本区间与当前值请求的观测日集合不一致")


def _fragment_order(fragment: VintageFragment) -> tuple[str, date, date]:
    row = fragment.row
    return (
        str(row["series_id"]),
        _as_date(row["observation_date"]),
        _as_date(row["realtime_start"]),
    )


def _continues(
    left: VintageFragment,
    right: VintageFragment,
    windows: Sequence[VintageWindow],
) -> bool:
    if right.shard != left.shard + 1:
        return False
    if (left.row["series_id"], left.row["observation_date"]) != (
        right.row["series_id"],
        right.row["observation_date"],
    ):
        return False
    if _as_date(left.row["realtime_end"]) != windows[left.shard].end:
        return False
    if _as_date(right.row["realtime_start"]) != windows[right.shard].start:
        return False
    return left.row["value"] == right.row["value"]


def _as_date(value: object) -> date:
    if not isinstance(value, date):
        raise SourceFetchError(f"内部错误：期望日期字段，实际为 {type(value).__name__}")
    return value


def _require_series(series_id: str) -> str:
    if series_id not in FRED_SERIES:
        raise SourceFetchError(f"FRED 序列只允许 {'、'.join(FRED_SERIES)}: {series_id!r}")
    return series_id


class _Paged(NamedTuple):
    items: list[Any]
    requests: int


def _fetch_vintage_dates(
    series_id: str,
    *,
    api_key: str,
    http: FredHttp,
) -> tuple[list[date], int]:
    paged = _fetch_paged(
        http,
        url=FRED_VINTAGE_DATES_URL,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "realtime_start": REALTIME_START,
            "realtime_end": REALTIME_END,
        },
        api_key=api_key,
        item_key="vintage_dates",
        page_limit=VINTAGE_DATES_PAGE_LIMIT,
        label=f"{series_id} vintagedates",
    )
    dates = [_iso_date(item, field="vintage_date") for item in paged.items]
    if len(set(dates)) != len(dates):
        raise SourceFetchError(f"FRED {series_id} vintage date 有重复")
    if not dates:
        raise SourceFetchError(f"FRED {series_id} 没有 vintage date")
    return sorted(dates), paged.requests


def _observation_params(
    series_id: str,
    *,
    api_key: str,
    window: VintageWindow | None,
) -> dict[str, str]:
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json"}
    if window is not None:
        params["realtime_start"] = window.start.isoformat()
        params["realtime_end"] = window.end.isoformat()
    return params


def _fetch_paged(
    http: FredHttp,
    *,
    url: str,
    params: Mapping[str, str],
    api_key: str,
    item_key: str,
    page_limit: int,
    label: str,
) -> _Paged:
    """按 ``offset`` 分页取完 ``item_key`` 数组。分页中途 ``count`` 变了说明源端有新写入，偏移量已错位，直接失败。"""
    collected: list[Any] = []
    offset = 0
    requests = 0
    expected_count: int | None = None
    while True:
        page_params = {**params, "limit": str(page_limit), "offset": str(offset)}
        body = _decode_body(http.get(url, page_params), api_key=api_key)
        requests += 1
        count = body.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise SourceFetchError(f"FRED {label} count 非法")
        items = body.get(item_key)
        if not isinstance(items, list):
            raise SourceFetchError(f"FRED {label} 缺少 {item_key} 数组")
        if len(items) > page_limit:
            raise SourceFetchError(f"FRED {label} 单页行数超过 limit")
        echoed_offset = body.get("offset")
        if echoed_offset is not None and echoed_offset != offset:
            # 接口回显的 offset 与请求不同，说明没有按请求分页，继续拼接会错位。
            raise SourceFetchError(f"FRED 回显 offset={echoed_offset}，与请求的 {offset} 不一致")
        if expected_count is None:
            expected_count = count
        elif count != expected_count:
            raise SourceFetchError(
                f"FRED {label} 分页期间 count 由 {expected_count} 变为 {count}，结果不一致，请重跑"
            )
        if not items and offset < count:
            raise SourceFetchError(f"FRED {label} 为空但 count={count} 未取完")
        collected.extend(items)
        offset += len(items)
        if offset >= count:
            break
    if len(collected) != expected_count:
        raise SourceFetchError(
            f"FRED {label} 取到 {len(collected)} 行，count 为 {expected_count}，不一致"
        )
    return _Paged(items=collected, requests=requests)


def _current_values(
    items: Sequence[Any],
    *,
    series_id: str,
) -> dict[tuple[str, date], object]:
    """不带 realtime 参数的当前值。同一观测日出现两次即失败，不猜测取哪个。"""
    current: dict[tuple[str, date], object] = {}
    for item in items:
        row = _to_row(item, series_id=series_id)
        key = (series_id, _as_date(row["observation_date"]))
        if key in current:
            raise SourceFetchError(f"FRED 当前值请求出现重复观测日: {key[1]:%Y-%m-%d}")
        current[key] = row["value"]
    return current


def _decode_body(response: FredHttpResponse, *, api_key: str) -> dict[str, Any]:
    try:
        body: object = json.loads(response.body)
    except ValueError:
        body = None
    if response.status_code != _HTTP_OK or (isinstance(body, dict) and "error_code" in body):
        # 非 JSON 的错误体可能是 HTML 或回显请求，一律不引用，只取 error_message 并脱敏。
        raw = body.get("error_message") if isinstance(body, dict) else None
        message = "无 error_message" if raw is None else str(raw)
        if api_key:
            message = message.replace(api_key, "***")
        raise SourceFetchError(f"FRED API 返回错误 HTTP {response.status_code}: {message}")
    if not isinstance(body, dict):
        raise SourceFetchError("FRED 响应必须是 JSON 对象")
    return body


def _to_row(item: object, *, series_id: str) -> dict[str, object]:
    if not isinstance(item, Mapping):
        raise SourceFetchError("FRED observation 必须是对象")
    return {
        "series_id": series_id,
        "observation_date": _iso_date(item.get("date"), field="date"),
        "realtime_start": _iso_date(item.get("realtime_start"), field="realtime_start"),
        "realtime_end": _iso_date(item.get("realtime_end"), field="realtime_end"),
        "value": _parse_value(item.get("value")),
        "source": SOURCE_LABEL,
    }


def _iso_date(raw: object, *, field: str) -> date:
    if not isinstance(raw, str) or len(raw) != _ISO_LEN or raw[4] != "-" or raw[7] != "-":
        raise SourceFetchError(f"FRED {field} 必须是 YYYY-MM-DD: {raw!r}")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SourceFetchError(f"FRED {field} 不是合法日期: {raw!r}") from exc


def _parse_value(raw: object) -> Decimal | None:
    """``"."`` 与空串记 NULL；其余必须是有限值、不超过 8 位小数、在 DECIMAL(18,8) 范围内。"""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise SourceFetchError("FRED value 必须是字符串")
    text = raw.strip()
    if text in _MISSING_VALUES:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        raise SourceFetchError(f"FRED value 不是有效数值: {text!r}") from None
    if not parsed.is_finite():
        raise SourceFetchError(f"FRED value 必须是有限值: {text!r}")
    try:
        quantized = parsed.quantize(_VALUE_QUANTUM)
    except InvalidOperation:
        raise SourceFetchError(f"FRED value 超出 DECIMAL(18,8): {text!r}") from None
    if quantized != parsed:
        # 不四舍五入。超精度说明源端格式变了，停下来看，而不是静默截断。
        raise SourceFetchError(f"FRED value 超过 8 位小数: {text!r}")
    if quantized.copy_abs() >= _VALUE_ABS_LIMIT:
        raise SourceFetchError(f"FRED value 超出 DECIMAL(18,8): {text!r}")
    return quantized

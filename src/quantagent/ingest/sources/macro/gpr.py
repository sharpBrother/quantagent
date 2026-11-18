"""Iacoviello 地缘政治风险指数（GPR）日频文件：下载、解析、宽转长。

源文件是 Stata ``.dta``，一行一个日期，``DAY`` 为 ``YYYYMMDD`` 字符串，其余数值列各是一个指数序列。
入库时每个数值列展开成一个 ``series_id``，列名原样大写，只换形不改值。

文件没有版本号与发布日期。``file_vintage`` 取文件内最大的 ``DAY``，这是由数据推出的近似，
所以契约等级标 C。它与旧仓 ``gold_timing/pit.py`` 的口径一致。

``event`` 是文本列，不入库。``date`` 与 ``DAY`` 是同一日期的另一种表示，也不作为序列。
"""

from __future__ import annotations

import hashlib
import io
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from math import isnan

import pandas as pd

from quantagent.ingest.errors import SourceFetchError

GPR_DAILY_RECENT_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.dta"

# 写入 source 列的来源标记。版本身份由 file_vintage 与 file_sha256 表达，这里不带版本号。
SOURCE_LABEL = "iacoviello.gpr_daily_recent"

_DAY_COLUMN = "DAY"
_NON_SERIES_COLUMNS: frozenset[str] = frozenset({"DAY", "date", "event"})
_DAY_FORMAT = "%Y%m%d"
_DAY_LEN = 8

# numeric(18,8)：8 位小数，整数位最多 10 位。超出即拒绝，不截断。
_VALUE_QUANTUM = Decimal("0.00000001")
_VALUE_LIMIT = Decimal("10000000000")

_HTTP_TIMEOUT_SECONDS = 60
_HTTP_USER_AGENT = "QuantAgent gpr-daily ingest"


@dataclass(frozen=True)
class GprPoint:
    """一个序列在一个观测日的值。``value`` 已量化到 8 位小数。缺失值不生成这一条。"""

    series_id: str
    observation_date: date
    value: Decimal


@dataclass(frozen=True)
class GprDailyFile:
    file_sha256: str
    # 文件内最大的 DAY。这是近似的版本日，不是源端发布日。
    file_vintage: date
    observation_min: date
    observation_max: date
    series_ids: tuple[str, ...]
    points: tuple[GprPoint, ...]


def fetch_gpr_daily_dta(url: str = GPR_DAILY_RECENT_URL) -> bytes:
    """下载原始字节。哈希与解析都基于这份字节，所以这里不做任何转码。"""
    request = urllib.request.Request(url, headers={"User-Agent": _HTTP_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            payload: bytes = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceFetchError(f"GPR 文件下载失败 {url}: {exc}") from exc
    if not payload:
        raise SourceFetchError(f"GPR 文件为空 {url}")
    return payload


def parse_gpr_daily_dta(payload: bytes) -> GprDailyFile:
    """解析 ``.dta`` 字节。任何不符合预期的形状都停止，不猜测、不跳过。"""
    if not payload:
        raise SourceFetchError("GPR dta 为空")
    try:
        frame = pd.read_stata(io.BytesIO(payload))
    except (ValueError, TypeError, OSError) as exc:
        raise SourceFetchError(f"无法解析 Stata dta: {exc}") from exc
    if frame.empty:
        raise SourceFetchError("GPR dta 没有观测行")
    if _DAY_COLUMN not in frame.columns:
        raise SourceFetchError(f"GPR dta 缺少 {_DAY_COLUMN} 列")

    observation_dates = [_parse_day(raw) for raw in frame[_DAY_COLUMN].tolist()]
    if len(set(observation_dates)) != len(observation_dates):
        raise SourceFetchError("GPR dta 的 DAY 有重复")

    series_columns = _series_columns(frame)
    points: list[GprPoint] = []
    for source_name, series_id in series_columns:
        # float32 无损加宽到 float64，与 wx2 历史值的口径一致（见 _quantize）。
        column_values = frame[source_name].to_numpy(dtype="float64")
        for observation_date, raw in zip(observation_dates, column_values, strict=True):
            value = _quantize(raw, series_id=series_id, observation_date=observation_date)
            if value is None:
                continue
            points.append(
                GprPoint(series_id=series_id, observation_date=observation_date, value=value)
            )
    points.sort(key=lambda point: (point.observation_date, point.series_id))

    return GprDailyFile(
        file_sha256=hashlib.sha256(payload).hexdigest(),
        # 版本取文件内最大的 DAY，与旧仓 gold_timing/pit.py 一致（见模块文档）。
        file_vintage=max(observation_dates),
        observation_min=min(observation_dates),
        observation_max=max(observation_dates),
        series_ids=tuple(series_id for _, series_id in series_columns),
        points=tuple(points),
    )


def _series_columns(frame: pd.DataFrame) -> list[tuple[str, str]]:
    """返回 ``(源列名, series_id)``。除 DAY、date、event 外的每一列都是序列。

    数值列照常入库，所以文件新增数值列时会自动进入。新增的文本或日期列直接报错，
    让采集停下来等人确认，不静默丢弃。
    """
    columns: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_name in frame.columns:
        name = str(raw_name)
        if name in _NON_SERIES_COLUMNS:
            continue
        series_id = name.upper()
        if series_id in seen:
            raise SourceFetchError(f"GPR 序列名大小写冲突: {series_id}")
        seen.add(series_id)
        dtype = frame[name].dtype
        if pd.api.types.is_bool_dtype(dtype) or not pd.api.types.is_numeric_dtype(dtype):
            raise SourceFetchError(f"GPR dta 出现未知非数值列 {name}（dtype={dtype}），拒绝入库")
        columns.append((name, series_id))
    if not columns:
        raise SourceFetchError("GPR dta 没有任何数值序列列")
    return columns


def _parse_day(raw: object) -> date:
    if not isinstance(raw, str):
        raise SourceFetchError(f"DAY 必须是 YYYYMMDD 字符串，实际为 {type(raw).__name__}: {raw!r}")
    text = raw.strip()
    if len(text) != _DAY_LEN or not text.isdigit():
        raise SourceFetchError(f"DAY 必须是 YYYYMMDD: {raw!r}")
    try:
        return datetime.strptime(text, _DAY_FORMAT).date()
    except ValueError as exc:
        raise SourceFetchError(f"DAY 不是合法日期: {raw!r}") from exc


def _quantize(raw: float, *, series_id: str, observation_date: date) -> Decimal | None:
    """缺失返回 None，不补 0、不补前值。非有限值与超出 numeric(18,8) 的值直接拒绝。

    ``raw`` 是 float64。wx2 历史值是 float32 加宽到 float64 后量化的结果（如 275.19760132，
    而不是 float32 最短串 275.1976），与之对拍必须用同一路径。
    """
    if isnan(raw):
        return None
    where = f"{series_id}/{observation_date:%Y%m%d}"
    try:
        decimal_value = Decimal(repr(float(raw)))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SourceFetchError(f"GPR 值不是有效数值 {where}: {raw!r}") from exc
    if not decimal_value.is_finite():
        raise SourceFetchError(f"GPR 值必须是有限值 {where}: {raw!r}")
    quantized = decimal_value.quantize(_VALUE_QUANTUM, rounding=ROUND_HALF_EVEN)
    if abs(quantized) >= _VALUE_LIMIT:
        raise SourceFetchError(f"GPR 值超过 numeric(18,8) 上限 {where}: {raw!r}")
    return quantized

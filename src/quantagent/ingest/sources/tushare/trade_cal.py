"""Tushare ``trade_cal`` 拉取。字段名与语义保持源端原样。"""

from __future__ import annotations

from datetime import datetime
from importlib import import_module
from math import isnan
from typing import TYPE_CHECKING, Any, Protocol

import pandas as pd

from quantagent.ingest.errors import EmptyPayloadError, SourceFetchError
from quantagent.platform.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_EXCHANGES: tuple[str, ...] = ("SSE", "SZSE")
_YMD_LEN = 8


class TradeCalClient(Protocol):
    def trade_cal(
        self,
        *,
        exchange: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame: ...


class ProTradeCalClient:
    def __init__(self, pro: Any) -> None:
        self._pro = pro

    def trade_cal(
        self,
        *,
        exchange: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        frame = self._pro.trade_cal(exchange=exchange, start_date=start_date, end_date=end_date)
        if frame is None:
            raise SourceFetchError("tushare.trade_cal 返回 None")
        if not isinstance(frame, pd.DataFrame):
            raise SourceFetchError(f"tushare.trade_cal 返回了非 DataFrame: {type(frame)!r}")
        return frame


def open_tushare_client(token: str) -> TradeCalClient:
    stripped = token.strip()
    if not stripped:
        raise ConfigError("QUANTAGENT_TUSHARE_TOKEN 未配置")
    try:
        ts = import_module("tushare")
    except ImportError as exc:
        raise ConfigError("未安装 tushare，请安装 sources 依赖组") from exc
    return ProTradeCalClient(ts.pro_api(stripped))


def fetch_trade_cal(
    client: TradeCalClient,
    *,
    start_date: str,
    end_date: str,
    exchanges: Sequence[str] = DEFAULT_EXCHANGES,
) -> list[dict[str, object]]:
    _assert_ymd(start_date, field="start_date")
    _assert_ymd(end_date, field="end_date")
    if start_date > end_date:
        raise SourceFetchError("start_date 晚于 end_date")
    unique_exchanges = tuple(dict.fromkeys(item.strip() for item in exchanges))
    if not unique_exchanges or any(not item for item in unique_exchanges):
        raise SourceFetchError("exchange 列表为空")
    rows: list[dict[str, object]] = []
    for exchange in unique_exchanges:
        frame = client.trade_cal(exchange=exchange, start_date=start_date, end_date=end_date)
        rows.extend(normalize_trade_cal_frame(frame, requested_exchange=exchange))
    if not rows:
        raise EmptyPayloadError("tushare.trade_cal 为空")
    rows.sort(key=lambda row: (str(row["exchange"]), str(row["cal_date"])))
    return rows


def normalize_trade_cal_frame(
    frame: pd.DataFrame,
    *,
    requested_exchange: str,
) -> list[dict[str, object]]:
    if frame.empty:
        return []
    missing = [name for name in ("cal_date", "is_open") if name not in frame.columns]
    if missing:
        raise SourceFetchError(f"tushare.trade_cal 缺列: {missing}")
    rows: list[dict[str, object]] = []
    for raw in frame.to_dict(orient="records"):
        exchange = raw.get("exchange", requested_exchange)
        rows.append(
            {
                "exchange": _require_text(exchange, field="exchange"),
                "cal_date": _ymd(raw.get("cal_date"), field="cal_date", nullable=False),
                "is_open": _is_open(raw.get("is_open")),
                "pretrade_date": _ymd(
                    raw.get("pretrade_date"),
                    field="pretrade_date",
                    nullable=True,
                ),
            }
        )
    return rows


def _require_text(value: object, *, field: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise SourceFetchError(f"{field} 为空")
    return text


def _ymd(value: object, *, field: str, nullable: bool) -> str | None:
    if _is_missing(value):
        if nullable:
            return None
        raise SourceFetchError(f"{field} 为空")
    strftime = getattr(value, "strftime", None)
    if callable(strftime):
        try:
            formatted = strftime("%Y%m%d")
        except (ValueError, TypeError) as exc:
            raise SourceFetchError(f"{field} 无法格式化为 YYYYMMDD: {value!r}") from exc
        if not isinstance(formatted, str):
            raise SourceFetchError(f"{field} strftime 未返回字符串: {formatted!r}")
        _assert_ymd(formatted, field=field)
        return formatted
    compact = str(value).strip().replace("-", "")
    if compact in {"", "None", "nan", "NaT"}:
        if nullable:
            return None
        raise SourceFetchError(f"{field} 为空")
    _assert_ymd(compact, field=field)
    return compact


def _assert_ymd(value: str, *, field: str) -> None:
    if len(value) != _YMD_LEN or not value.isdigit():
        raise SourceFetchError(f"{field} 必须是 YYYYMMDD: {value!r}")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise SourceFetchError(f"{field} 不是合法日期: {value!r}") from exc


def _is_open(value: object) -> int | None:
    if _is_missing(value):
        return None
    raw: object = value
    item = getattr(raw, "item", None)
    if callable(item):
        raw = item()
    if isinstance(raw, bool):
        number = int(raw)
    elif isinstance(raw, int):
        number = raw
    elif isinstance(raw, float) and raw in {0.0, 1.0}:
        number = int(raw)
    elif isinstance(raw, str) and raw.strip() in {"0", "1"}:
        number = int(raw.strip())
    else:
        raise SourceFetchError(f"is_open 无法转为 0/1: {value!r}")
    if number not in {0, 1}:
        raise SourceFetchError(f"is_open 必须是 0 或 1: {value!r}")
    return number


def _is_missing(value: object) -> bool:
    if value is None or type(value).__name__ in {"NAType", "NaTType"}:
        return True
    if isinstance(value, (str, bytes, int, bool, datetime)):
        return False
    if isinstance(value, float):
        return isnan(value)
    item = getattr(value, "item", None)
    if not callable(item):
        return False
    try:
        inner = item()
    except (TypeError, ValueError):
        return False
    return inner is not value and _is_missing(inner)

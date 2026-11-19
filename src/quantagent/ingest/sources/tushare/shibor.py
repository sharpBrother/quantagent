"""Tushare ``shibor`` 拉取与宽转长。字段名与期限取值保持源端原样。

``pro.shibor`` 返回一行一个日期，期限列在宽表里。入库时逐期限展开成一行，与源端一一对应，
只换形不改值。期限取值与旧仓 wx2 ``dbo.macro_shibor.maturity`` 实际出现的取值相同
（``on``、``1w``、``2w``、``1m``、``3m``、``6m``、``9m``、``1y``），不另起名字。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from importlib import import_module
from math import isnan
from typing import Any, Protocol

import pandas as pd

from quantagent.ingest.errors import SourceFetchError
from quantagent.platform.errors import ConfigError

SOURCE_LABEL = "tushare.shibor"

# 宽表的期限列，顺序与 pro.shibor 返回一致。列名即入库的 maturity 取值。
SHIBOR_MATURITIES: tuple[str, ...] = ("on", "1w", "2w", "1m", "3m", "6m", "9m", "1y")

# 利率在 src_tushare.shibor 中是 numeric(18,4)。超过四位小数的源值直接拒绝，不截断、不四舍五入，
# 否则同一份源数据可能悄悄改变下游读到的数值。
_RATE_QUANTUM = Decimal("0.0001")
_YMD_LEN = 8


class ShiborClient(Protocol):
    def shibor(self, *, start_date: str, end_date: str) -> pd.DataFrame: ...


class ProShiborClient:
    def __init__(self, pro: Any) -> None:
        self._pro = pro

    def shibor(self, *, start_date: str, end_date: str) -> pd.DataFrame:
        frame = self._pro.shibor(start_date=start_date, end_date=end_date)
        if frame is None:
            raise SourceFetchError("tushare.shibor 返回 None")
        if not isinstance(frame, pd.DataFrame):
            raise SourceFetchError(f"tushare.shibor 返回了非 DataFrame: {type(frame)!r}")
        return frame


def open_shibor_client(token: str) -> ShiborClient:
    stripped = token.strip()
    if not stripped:
        raise ConfigError("QUANTAGENT_TUSHARE_TOKEN 未配置")
    try:
        ts = import_module("tushare")
    except ImportError as exc:
        raise ConfigError("未安装 tushare，请安装 sources 依赖组") from exc
    return ProShiborClient(ts.pro_api(stripped))


def shibor_wide_to_long(
    frame: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    ingested_at: datetime,
) -> list[dict[str, object]]:
    """宽表展开为 ``(trade_date, maturity)`` 长表。空期限不落行，不填充。

    ``ingested_at`` 必须是 naive UTC，与写入时 ``_ingested_at`` 同一时刻。它只是采集记录，
    不作可见日（AGENTS.md §7.4）。
    """
    if frame.empty:
        return []
    missing_columns = [name for name in ("date", *SHIBOR_MATURITIES) if name not in frame.columns]
    if missing_columns:
        # 缺列说明源端接口变了。缺期限不是缺数据，必须停下，不能当成该期限全部为空。
        raise SourceFetchError(f"tushare.shibor 缺列: {missing_columns}")
    rows: list[dict[str, object]] = []
    seen_dates: set[str] = set()
    for raw in frame.to_dict(orient="records"):
        trade_date = _trade_date(raw.get("date"))
        if trade_date in seen_dates:
            raise SourceFetchError(f"tushare.shibor 返回重复 date: {trade_date}")
        seen_dates.add(trade_date)
        if not start_date <= trade_date <= end_date:
            raise SourceFetchError(f"tushare.shibor 返回了请求区间之外的 date: {trade_date}")
        for maturity in SHIBOR_MATURITIES:
            value = raw.get(maturity)
            if _is_missing(value):
                continue
            rows.append(
                {
                    "trade_date": trade_date,
                    "maturity": maturity,
                    "rate": _rate(value, maturity=maturity, trade_date=trade_date),
                    "source": SOURCE_LABEL,
                    "ingested_at": ingested_at,
                }
            )
    rows.sort(
        key=lambda row: (str(row["trade_date"]), SHIBOR_MATURITIES.index(str(row["maturity"])))
    )
    return rows


def _trade_date(value: object) -> str:
    if _is_missing(value):
        raise SourceFetchError("tushare.shibor date 为空")
    strftime = getattr(value, "strftime", None)
    text = strftime("%Y%m%d") if callable(strftime) else str(value).strip().replace("-", "")
    if not isinstance(text, str) or len(text) != _YMD_LEN or not text.isdigit():
        raise SourceFetchError(f"tushare.shibor date 必须是 YYYYMMDD: {value!r}")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise SourceFetchError(f"tushare.shibor date 不是合法日期: {value!r}") from exc
    return text


def _rate(value: object, *, maturity: str, trade_date: str) -> Decimal:
    where = f"{trade_date}/{maturity}"
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SourceFetchError(f"shibor 利率不是有效数值 {where}: {value!r}") from exc
    if not decimal_value.is_finite():
        raise SourceFetchError(f"shibor 利率必须是有限值 {where}: {value!r}")
    quantized = decimal_value.quantize(_RATE_QUANTUM)
    if decimal_value != quantized:
        raise SourceFetchError(f"shibor 利率超过 4 位小数 {where}: {value!r}")
    return quantized


def _is_missing(value: object) -> bool:
    if value is None or type(value).__name__ in {"NAType", "NaTType"}:
        return True
    if isinstance(value, str):
        return value.strip() in {"", "None", "nan", "NaT"}
    # numpy 的 float64 是 float 的子类，DataFrame 里的缺失值落在这一支。
    if isinstance(value, float):
        return isnan(value)
    return False

"""东方财富当日分钟线：只取原值，不猜测缺失行情。"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.sources.http import get_with_retry

if TYPE_CHECKING:
    from datetime import date

_URL = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_CODE = re.compile(r"([0-9]{6})\.(SH|SZ|BJ)\Z")
_ROW_WIDTH = 8
_PAGE_SIZE = 200


def list_stocks() -> tuple[str, ...]:
    """取东财沪深京股票列表，分页总数或代码冲突时停止。"""
    result: list[str] = []
    expected: int | None = None
    page = 1
    while expected is None or len(result) < expected:
        response = get_with_retry(
            _LIST_URL,
            params={
                "pn": str(page),
                "pz": str(_PAGE_SIZE),
                "po": "1",
                "np": "1",
                "fid": "f12",
                "fields": "f12,f13",
                "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            },
            timeout=15,
        )
        response.raise_for_status()
        try:
            data = response.json()["data"]
            total, rows = int(data["total"]), data["diff"]
            if total <= 0 or not isinstance(rows, list) or not rows:
                raise ValueError("股票列表为空")
            if expected is not None and total != expected:
                raise ValueError("股票总数在分页时变化")
            expected = total
            for row in rows:
                code, market = row["f12"], row["f13"]
                if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
                    raise ValueError("股票代码非法")
                if market == 1 and code.startswith("6"):
                    suffix = "SH"
                elif market == 0 and code.startswith(("4", "8", "92")):
                    suffix = "BJ"
                elif market == 0 and code.startswith(("0", "3")):
                    suffix = "SZ"
                else:
                    raise ValueError(f"未知市场代码: {code}")
                result.append(f"{code}.{suffix}")
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceFetchError(f"东财股票列表无效: {exc}") from exc
        if len(result) > expected or len(set(result)) != len(result):
            raise SourceFetchError("东财股票列表分页重复或超过总数")
        page += 1
    return tuple(sorted(result))


def fetch_day(code: str, *, trade_date: date) -> list[tuple[Any, ...]]:
    """按证券取当日快照；非当天数据直接拒绝，不能把上一交易日当今天。"""
    match = _CODE.fullmatch(code)
    if match is None:
        raise SourceFetchError(f"东财证券代码非法: {code!r}")
    market = 1 if match.group(2) == "SH" else 0
    response = get_with_retry(
        _URL,
        params={
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "ndays": "1",
            "iscr": "0",
            "secid": f"{market}.{match.group(1)}",
        },
        timeout=15,
    )
    response.raise_for_status()
    try:
        data = response.json()["data"]
        if not isinstance(data, dict) or str(data["code"]) != match.group(1):
            raise ValueError("响应代码不符")
        if data["market"] != market or not isinstance(data["trends"], list):
            raise ValueError("响应市场或数据格式不符")
        rows = data["trends"]
        if not rows:
            raise ValueError("无分钟行情")
        result = []
        for row in rows:
            fields = row.split(",")
            if len(fields) != _ROW_WIDTH:
                raise ValueError("分钟行情字段数不符")
            stamp = datetime.strptime(fields[0], "%Y-%m-%d %H:%M")
            if stamp.date() != trade_date:
                raise ValueError("响应日期不是目标交易日")
            o, c, h, low, volume, amount = (Decimal(value) for value in fields[1:7])
            result.append((code, stamp, o, h, low, c, volume, amount))
        return result
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError) as exc:
        raise SourceFetchError(f"东财分钟行情无效: {code}: {exc}") from exc

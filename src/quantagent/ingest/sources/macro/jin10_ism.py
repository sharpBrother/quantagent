"""解析金十 ISM 制造业 PMI 详情接口。

发现机制：详情自身带 ``next_public_time``（下一期北京时间），且近期 event ID 密集连排、
已排期的未来事件（``actual`` 为空）也能按 ID 读到。因此新一期可以通过"上一期 ID 之后、
按序扫描 datanameId=129 的记录"发现，不依赖月历 CDN、历史列表或加密的 WebSocket。
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo

import requests

from quantagent.ingest.errors import SourceFetchError
from quantagent.ingest.sources.http import get_with_retry

INDICATOR_ID = 129
_SUCCESS_STATUS = 200
_NOT_FOUND_STATUS = 404
_MONTHS_PER_YEAR = 12
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DETAIL_URL = "https://e0430d16720e4211b5e072c26205c890.z3c.jin10.com/web/data/jiedu"
_HEADERS = {
    "user-agent": "Mozilla/5.0",
    "x-app-id": "sKKYe29sFuJaeOCJ",
    "x-version": "2.0",
    "handleError": "false",
}


@dataclass(frozen=True)
class Jin10IsmDetail:
    data_id: int
    published_at: datetime
    publish_date: date
    period_end: date
    time_period: str
    actual_value: Decimal | None
    forecast_value: Decimal | None
    previous_value: Decimal | None
    revised_value: Decimal | None
    # 下一期发布的北京时间。ISM 每月一次，发现新事件靠它决定何时开始扫描；
    # 源端缺失或格式异常时为 None，调用方此时不得扫描，按未到发布日处理。
    next_public_at: datetime | None


def parse_jin10_next_public_time(value: object) -> datetime | None:
    """解析 ``next_public_time``（北京时间）。缺失返回 None，格式异常抛错。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise SourceFetchError("金十下一期发布时间类型无效")
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_SHANGHAI)
    except ValueError:
        raise SourceFetchError("金十下一期发布时间格式无效") from None
    return parsed


def fetch_jin10_raw_detail(event_id: int) -> dict[str, Any]:
    """读取原始详情载荷。扫描需要先看 ``datanameId`` 再决定是否按 ISM 校验。

    事件不存在时返回空 dict（接口 200 但 ``data`` 为 null），不当作错误。
    """
    if event_id <= 0:
        raise SourceFetchError("金十事件 ID 必须为正整数")
    try:
        response = get_with_retry(
            _DETAIL_URL,
            params={"id": str(event_id)},
            timeout=30,
            get=partial(requests.get, headers=_HEADERS),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SourceFetchError(f"金十详情读取失败: {type(exc).__name__}") from None
    if not isinstance(payload, dict):
        raise SourceFetchError("金十详情响应无效")
    status = payload.get("status")
    data: Any = payload.get("data")
    # 跳空或下架的事件返回 HTTP 200 但业务 status=404、data=null。这是扫描的正常
    # 情况（ID 空间不连续），返回空 dict 让扫描跳过，不当作源端异常。
    if status == _NOT_FOUND_STATUS and data is None:
        return {}
    if status != _SUCCESS_STATUS:
        raise SourceFetchError(f"金十详情响应状态异常: {status!r}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SourceFetchError("金十详情 data 类型无效")
    return {"status": payload["status"], "data": data}


def fetch_jin10_ism_detail(event_id: int) -> Jin10IsmDetail:
    """读取并按 ISM 身份校验已知事件；非本指标或不存在即报错。"""
    payload = fetch_jin10_raw_detail(event_id)
    if not payload:
        raise SourceFetchError(f"金十事件不存在或已下架: id={event_id}")
    return parse_jin10_ism_detail(payload, requested_id=event_id)


def _decimal(value: object, field: str) -> Decimal | None:
    if value is None or value in ("", "-", "--", "—"):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise SourceFetchError(f"金十 {field} 不是数值") from None
    if not number.is_finite():
        raise SourceFetchError(f"金十 {field} 不是有限值")
    return number


def parse_jin10_ism_detail(payload: object, *, requested_id: int) -> Jin10IsmDetail:
    """验证源事件身份与发布时间，统计期按详情的月份文本确定。"""
    if (
        requested_id <= 0
        or not isinstance(payload, dict)
        or payload.get("status") != _SUCCESS_STATUS
    ):
        raise SourceFetchError("金十详情请求或响应无效")
    data: Any = payload.get("data")
    if not isinstance(data, dict):
        raise SourceFetchError("金十详情缺少 data")
    if data.get("dataId") != requested_id or data.get("datanameId") != INDICATOR_ID:
        raise SourceFetchError("金十事件 ID 或指标 ID 不匹配")
    raw_time = data.get("pub_time")
    if not isinstance(raw_time, str):
        raise SourceFetchError("金十详情缺少源发布时间")
    try:
        published = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    except ValueError:
        raise SourceFetchError("金十源发布时间格式无效") from None
    if published.tzinfo is None or published.utcoffset() is None:
        raise SourceFetchError("金十源发布时间缺少时区")
    published = published.astimezone(UTC)
    local_date = published.astimezone(_SHANGHAI).date()
    local_text = data.get("public_time")
    if not isinstance(local_text, str):
        raise SourceFetchError("金十详情缺少北京时间")
    try:
        local_time = datetime.strptime(local_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_SHANGHAI)
    except ValueError:
        raise SourceFetchError("金十北京时间格式无效") from None
    if local_time.astimezone(UTC) != published:
        raise SourceFetchError("金十 UTC 时间与北京时间不一致")
    period_text = data.get("time_period")
    if not isinstance(period_text, str):
        raise SourceFetchError("金十详情统计月份无效")
    match = re.fullmatch(r"(\d{1,2})月", period_text)
    if not match or not 1 <= int(match[1]) <= _MONTHS_PER_YEAR:
        raise SourceFetchError("金十详情统计月份无效")
    month = int(match[1])
    year = local_date.year
    period_end = date(year, month, calendar.monthrange(year, month)[1])
    if period_end >= local_date:
        year -= 1
        period_end = date(year, month, calendar.monthrange(year, month)[1])
    return Jin10IsmDetail(
        data_id=requested_id,
        published_at=published,
        publish_date=local_date,
        period_end=period_end,
        time_period=period_text,
        actual_value=_decimal(data.get("actual"), "actual"),
        forecast_value=_decimal(data.get("consensus"), "consensus"),
        previous_value=_decimal(data.get("previous"), "previous"),
        revised_value=_decimal(data.get("revised"), "revised"),
        next_public_at=parse_jin10_next_public_time(data.get("next_public_time")),
    )

"""旧仓 ``MarketDataService.get_trade_calendar`` 与新仓 ``CalendarRepository.list_days`` 的开市日对拍。

快照 ``trade_calendar_wx2.json`` 是 wx2 ``dbo.trade_cal`` 中全部 ``is_open = 1`` 的日期，
抓取 SQL 与来源写在文件 provenance 里。旧方法不过滤 exchange，而该表只含 ``SSE``，
所以新端口用 ``exchange="SSE"``。

比对窗口：本地 lake 只物化到 ``as_of + 7`` 天，窗口上界取快照与 lake 都覆盖的最晚日期。
快照里更晚的日期不算失败，只打印出来。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.domain.calendar import open_dates
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

_FIXTURE = Path(__file__).parent / "market_data" / "trade_calendar_wx2.json"
_EXCHANGE = "SSE"
_FILE_LIMIT_BYTES = 512 * 1024
_LIST_LIMIT = 20


def _payload() -> dict[str, object]:
    loaded = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _snapshot_dates(payload: dict[str, object]) -> tuple[date, ...]:
    raw = payload["open_dates"]
    assert isinstance(raw, list)
    return tuple(_parse_ymd(str(item)) for item in raw)


def _parse_ymd(text: str) -> date:
    return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))


@pytest.mark.golden
def test_trade_calendar_fixture_shape_and_size() -> None:
    assert _FIXTURE.stat().st_size < _FILE_LIMIT_BYTES
    payload = _payload()
    provenance = payload["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["captured_on"] == "2026-11-22"
    dates = _snapshot_dates(payload)
    assert provenance["row_count"] == len(dates) == 9011
    assert list(dates) == sorted(set(dates))
    assert dates[0] == date(1990, 12, 19)
    assert dates[-1] == date(2027, 11, 22)


@pytest.mark.golden
@pytest.mark.integration
def test_trade_calendar_open_dates_match_wx2_over_covered_window() -> None:
    snapshot = _snapshot_dates(_payload())
    snap_min, snap_max = snapshot[0], snapshot[-1]

    paths = resolve_var_paths(get_settings(), repo_root=detect_repo_root())
    repo = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")

    # 先探测 lake 实际覆盖到哪天；as_of 取快照末日，只为拿到全部已物化行。
    probe = repo.list_days(as_of=snap_max, exchange=_EXCHANGE, start=snap_min, end=snap_max)
    covered_end = max(day.cal_dt for day in probe)
    window_end = min(snap_max, covered_end)

    days = repo.list_days(as_of=window_end, exchange=_EXCHANGE, start=snap_min, end=window_end)
    local = set(open_dates(days))
    expected = {d for d in snapshot if d <= window_end}
    tail = [d for d in snapshot if d > window_end]

    print(
        f"\n交易日历对拍：窗口 {snap_min.isoformat()}..{window_end.isoformat()}，"
        f"wx2 开市日 {len(expected)} 天，新端口开市日 {len(local)} 天，"
        f"一致 {len(expected & local)} 天。"
    )
    if tail:
        print(
            f"未比对（快照晚于 lake 覆盖）：{len(tail)} 天，"
            f"{tail[0].isoformat()}..{tail[-1].isoformat()}，lake 覆盖至 {covered_end.isoformat()}。"
        )

    only_wx2 = sorted(expected - local)
    only_lake = sorted(local - expected)
    assert not only_wx2 and not only_lake, (
        f"开市日不一致：wx2 独有 {len(only_wx2)} 天 {_fmt(only_wx2)}；"
        f"lake 独有 {len(only_lake)} 天 {_fmt(only_lake)}"
    )


def _fmt(values: list[date]) -> str:
    shown = [d.isoformat() for d in values[:_LIST_LIMIT]]
    suffix = "" if len(values) <= _LIST_LIMIT else f" ...共{len(values)}天"
    return "[" + ", ".join(shown) + "]" + suffix

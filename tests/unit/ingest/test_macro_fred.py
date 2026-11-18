"""FRED／ALFRED 带版本采集：分片取数、区间合并、不变量、值解析、错误脱敏、请求间隔与作业写入语义。不联网。

``FakeFred`` 按 FRED 的 realtime 语义回放：vintagedates 返回全部版本起点；带 realtime 窗口的
observations 只返回与窗口相交的版本区间，并把区间截断到窗口；不带 realtime 的请求返回当前值。
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
import requests
from pydantic import SecretStr

from quantagent.adapters.postgres.src_targets import FRED_OBSERVATION_VINTAGE
from quantagent.ingest.errors import IngestError, SourceFetchError
from quantagent.ingest.jobs.macro_fred import ingest_macro_fred
from quantagent.ingest.sources.macro.fred import (
    FRED_OBSERVATIONS_URL,
    FRED_SERIES,
    FRED_VINTAGE_DATES_URL,
    SOURCE_LABEL,
    FredHttpResponse,
    RequestsFredHttp,
    VintageFragment,
    VintageWindow,
    check_vintage_invariants,
    fetch_observation_vintages,
    merge_vintage_fragments,
    plan_vintage_windows,
)
from quantagent.ingest.writers.src_follow import fingerprint_columns
from quantagent.ingest.writers.src_insert import row_hash
from quantagent.platform.config import Settings
from quantagent.platform.errors import ConfigError, WriteGateError
from quantagent.platform.storage.paths import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

# 合成的假 key，只用于断言脱敏。不是真实凭据。
_KEY = "0123456789abcdef0123456789abcdef"
_INGESTED = datetime(2026, 1, 2, 11, 0, tzinfo=UTC)
_OPEN = date(9999, 12, 31)


class Segment(NamedTuple):
    """一个版本区间：观测日、realtime_start、realtime_end、源端原始 value 字符串。"""

    observed: date
    start: date
    end: date
    value: str


def seg(observed: str, start: str, end: str, value: str) -> Segment:
    return Segment(
        date.fromisoformat(observed),
        date.fromisoformat(start),
        date.fromisoformat(end),
        value,
    )


def _page(
    items: list[object], *, key: str, offset: int, limit: int, count: int
) -> FredHttpResponse:
    body = {"count": count, "offset": offset, "limit": limit, key: items[offset : offset + limit]}
    return FredHttpResponse(200, json.dumps(body))


class FakeFred:
    """按 FRED 语义回放版本区间。``override`` 返回非 None 时优先用它的响应，用来注入错误与分页异常。"""

    def __init__(
        self,
        segments: Sequence[Segment],
        *,
        override: Callable[[str, dict[str, str]], FredHttpResponse | None] | None = None,
    ) -> None:
        self.segments = list(segments)
        self.override = override
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: Mapping[str, str]) -> FredHttpResponse:
        self.calls.append((url, dict(params)))
        if self.override is not None:
            injected = self.override(url, dict(params))
            if injected is not None:
                return injected
        limit = int(params.get("limit", "100000"))
        offset = int(params.get("offset", "0"))
        if url == FRED_VINTAGE_DATES_URL:
            vintages = sorted({s.start for s in self.segments})
            items: list[object] = [v.isoformat() for v in vintages]
            return _page(items, key="vintage_dates", offset=offset, limit=limit, count=len(items))
        if url != FRED_OBSERVATIONS_URL:
            raise AssertionError(f"未知 URL: {url}")
        if "realtime_start" in params:
            window_start = date.fromisoformat(params["realtime_start"])
            window_end = date.fromisoformat(params["realtime_end"])
            rows = [
                (o, max(s, window_start), min(e, window_end), v)
                for o, s, e, v in self.segments
                if s <= window_end and e >= window_start
            ]
        else:
            rows = [(o, s, e, v) for o, s, e, v in self.segments if e == _OPEN]
        rows.sort(key=lambda r: (r[0], r[1]))
        items = [
            {
                "date": o.isoformat(),
                "realtime_start": s.isoformat(),
                "realtime_end": e.isoformat(),
                "value": v,
            }
            for o, s, e, v in rows
        ]
        return _page(items, key="observations", offset=offset, limit=limit, count=len(items))

    def observation_calls(self) -> list[dict[str, str]]:
        return [
            p for url, p in self.calls if url == FRED_OBSERVATIONS_URL and "realtime_start" in p
        ]


def _raw(body: dict[str, Any]) -> FredHttpResponse:
    return FredHttpResponse(200, json.dumps(body))


def _settings(tmp_path: Path, *, key: str = _KEY, allow_db_write: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        var_root=tmp_path / "var",
        allow_db_write=allow_db_write,
        fred_api_key=SecretStr(key),
    )


def _run_logs(tmp_path: Path, settings: Settings) -> list[dict[str, Any]]:
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(paths.runs.glob("*.json"))]


# 五个 vintage date，切两片时窗口为 [01-02, 01-09]、[01-10, 01-19]、[01-20, 9999-12-31]。
# 数据覆盖三类情形：单段跨三片的开放版本、被边界切开且值不变的版本、值变化的相邻版本。
_SHARDED_DATASET = [
    seg("2024-01-01", "2024-01-02", "2024-01-09", "1.0"),
    seg("2024-01-01", "2024-01-10", "9999-12-31", "1.5"),
    seg("2024-01-02", "2024-01-02", "9999-12-31", "2.0"),
    seg("2024-01-03", "2024-01-05", "2024-01-14", "3.0"),
    seg("2024-01-03", "2024-01-15", "9999-12-31", "3.1"),
    seg("2024-01-04", "2024-01-20", "9999-12-31", "."),
]


# ---- 分页与请求参数 ----


@pytest.mark.unit
def test_pagination_pages_each_window_and_sends_realtime_bounds() -> None:
    fred = FakeFred(
        [
            seg("2024-01-01", "2024-01-02", "9999-12-31", "1.1"),
            seg("2024-01-02", "2024-01-02", "9999-12-31", "1.2"),
            seg("2024-01-03", "2024-01-03", "9999-12-31", "2.2"),
        ]
    )
    fetched = fetch_observation_vintages("DFII10", api_key=_KEY, http=fred, page_limit=2)
    assert fetched.shards == 1
    assert fetched.pages == 2
    assert fetched.requests == 1 + 2 + 2  # vintagedates、窗口两页、当前值两页
    vintage_call = fred.calls[0][1]
    assert fred.calls[0][0] == FRED_VINTAGE_DATES_URL
    assert vintage_call["realtime_start"] == "1776-07-04"
    assert vintage_call["realtime_end"] == "9999-12-31"
    windows = fred.observation_calls()
    assert [c["realtime_start"] for c in windows] == ["2024-01-02", "2024-01-02"]
    assert [c["realtime_end"] for c in windows] == ["9999-12-31", "9999-12-31"]
    assert [c["offset"] for c in windows] == ["0", "2"]
    assert all(c["limit"] == "2" for c in windows)
    assert len(fetched.rows) == 3


@pytest.mark.unit
def test_each_vintage_shard_gets_its_own_window_request() -> None:
    fred = FakeFred(_SHARDED_DATASET)
    fetched = fetch_observation_vintages("CPIAUCSL", api_key=_KEY, http=fred, shard_size=2)
    assert fetched.vintage_dates == 5
    assert fetched.shards == 3
    windows = [(c["realtime_start"], c["realtime_end"]) for c in fred.observation_calls()]
    assert windows == [
        ("2024-01-02", "2024-01-09"),
        ("2024-01-10", "2024-01-19"),
        ("2024-01-20", "9999-12-31"),
    ]


@pytest.mark.unit
def test_sharded_fetch_is_row_for_row_equal_to_a_single_request() -> None:
    # 分片加合并的结果必须与整段一次请求逐行一致。整段一次请求在真实 FRED 上可用时即为基准。
    sharded = fetch_observation_vintages(
        "CPIAUCSL", api_key=_KEY, http=FakeFred(_SHARDED_DATASET), shard_size=2
    )
    single = fetch_observation_vintages(
        "CPIAUCSL", api_key=_KEY, http=FakeFred(_SHARDED_DATASET), shard_size=5000
    )
    assert single.shards == 1
    assert sharded.rows == single.rows
    assert sharded.fragments > len(sharded.rows)
    # 合并把 01-01 的 1.5 版本（跨两片）、01-03 的 3.0 版本（跨边界）、01-02 的开放版本（跨三片）接回去。
    spans = {
        (row["observation_date"], row["realtime_start"]): row["realtime_end"]
        for row in sharded.rows
    }
    assert spans[(date(2024, 1, 2), date(2024, 1, 2))] == _OPEN
    assert spans[(date(2024, 1, 3), date(2024, 1, 5))] == date(2024, 1, 14)
    assert spans[(date(2024, 1, 1), date(2024, 1, 10))] == _OPEN


@pytest.mark.unit
def test_count_change_between_pages_fails_instead_of_splicing() -> None:
    def override(url: str, params: dict[str, str]) -> FredHttpResponse | None:
        if url == FRED_OBSERVATIONS_URL and "realtime_start" in params and params["offset"] == "2":
            return _raw({"count": 4, "offset": 2, "observations": []})
        return None

    fred = FakeFred(_SHARDED_DATASET[:3], override=override)
    # 拉取途中源端新增了版本，偏移量已经错位，不能拼接。
    with pytest.raises(SourceFetchError, match="count 由 3 变为 4"):
        fetch_observation_vintages("DFII10", api_key=_KEY, http=fred, page_limit=2)


@pytest.mark.unit
def test_empty_page_before_count_is_reached_fails() -> None:
    def override(url: str, params: dict[str, str]) -> FredHttpResponse | None:
        if url == FRED_OBSERVATIONS_URL and "realtime_start" in params:
            return _raw({"count": 2, "offset": 0, "observations": []})
        return None

    fred = FakeFred([seg("2024-01-01", "2024-01-02", "9999-12-31", "1")], override=override)
    with pytest.raises(SourceFetchError, match="为空但 count=2 未取完"):
        fetch_observation_vintages("DFII10", api_key=_KEY, http=fred)


@pytest.mark.unit
def test_echoed_offset_mismatch_fails() -> None:
    def override(url: str, params: dict[str, str]) -> FredHttpResponse | None:
        if url == FRED_OBSERVATIONS_URL and "realtime_start" in params:
            return _raw({"count": 1, "offset": 5, "observations": []})
        return None

    fred = FakeFred([seg("2024-01-01", "2024-01-02", "9999-12-31", "1")], override=override)
    with pytest.raises(SourceFetchError, match="回显 offset=5"):
        fetch_observation_vintages("DFII10", api_key=_KEY, http=fred)


@pytest.mark.unit
def test_unknown_series_is_rejected_before_any_request() -> None:
    fred = FakeFred([])
    with pytest.raises(SourceFetchError, match="FRED 序列只允许"):
        fetch_observation_vintages("GPR", api_key=_KEY, http=fred)
    assert fred.calls == []


# ---- 分片与合并（纯函数） ----


@pytest.mark.unit
def test_plan_windows_cuts_vintages_into_chunks_with_day_before_next_start() -> None:
    vintages = [date(2024, 1, d) for d in (2, 5, 10, 15, 20)]
    assert plan_vintage_windows(vintages, shard_size=2) == (
        VintageWindow(date(2024, 1, 2), date(2024, 1, 9)),
        VintageWindow(date(2024, 1, 10), date(2024, 1, 19)),
        VintageWindow(date(2024, 1, 20), _OPEN),
    )
    assert plan_vintage_windows(vintages) == (VintageWindow(date(2024, 1, 2), _OPEN),)


@pytest.mark.unit
def test_plan_windows_rejects_empty_unsorted_or_bad_shard_size() -> None:
    with pytest.raises(SourceFetchError, match="没有 vintage date"):
        plan_vintage_windows([])
    with pytest.raises(SourceFetchError, match="严格递增"):
        plan_vintage_windows([date(2024, 1, 5), date(2024, 1, 2)])
    with pytest.raises(ValueError, match="shard_size"):
        plan_vintage_windows([date(2024, 1, 2)], shard_size=0)


_WINDOWS = (
    VintageWindow(date(2024, 1, 2), date(2024, 1, 9)),
    VintageWindow(date(2024, 1, 10), date(2024, 1, 19)),
    VintageWindow(date(2024, 1, 20), _OPEN),
)


def _fragment(shard: int, observed: str, start: str, end: str, value: str) -> VintageFragment:
    row = {
        "series_id": "CPIAUCSL",
        "observation_date": date.fromisoformat(observed),
        "realtime_start": date.fromisoformat(start),
        "realtime_end": date.fromisoformat(end),
        "value": Decimal(value) if value != "." else None,
        "source": SOURCE_LABEL,
    }
    return VintageFragment(shard=shard, row=row)


@pytest.mark.unit
def test_merge_joins_same_value_cut_at_a_window_edge() -> None:
    merged = merge_vintage_fragments(
        [
            _fragment(0, "2024-01-01", "2024-01-02", "2024-01-09", "1.0"),
            _fragment(1, "2024-01-01", "2024-01-10", "2024-01-19", "1.5"),
        ],
        _WINDOWS,
    )
    # 值不同：边界两侧是两个版本，不能接。
    assert [(r["realtime_start"], r["realtime_end"]) for r in merged] == [
        (date(2024, 1, 2), date(2024, 1, 9)),
        (date(2024, 1, 10), date(2024, 1, 19)),
    ]
    joined = merge_vintage_fragments(
        [
            _fragment(1, "2024-01-01", "2024-01-10", "2024-01-19", "1.5"),
            _fragment(2, "2024-01-01", "2024-01-20", "9999-12-31", "1.5"),
        ],
        _WINDOWS,
    )
    assert joined == [
        {
            "series_id": "CPIAUCSL",
            "observation_date": date(2024, 1, 1),
            "realtime_start": date(2024, 1, 10),
            "realtime_end": _OPEN,
            "value": Decimal("1.5"),
            "source": SOURCE_LABEL,
        }
    ]


@pytest.mark.unit
def test_merge_chains_a_version_across_three_windows() -> None:
    merged = merge_vintage_fragments(
        [
            _fragment(0, "2024-01-01", "2024-01-02", "2024-01-09", "7"),
            _fragment(1, "2024-01-01", "2024-01-10", "2024-01-19", "7"),
            _fragment(2, "2024-01-01", "2024-01-20", "9999-12-31", "7"),
        ],
        _WINDOWS,
    )
    assert [(r["realtime_start"], r["realtime_end"]) for r in merged] == [(date(2024, 1, 2), _OPEN)]


@pytest.mark.unit
def test_merge_requires_the_left_piece_to_end_exactly_at_the_window_edge() -> None:
    # 左段在 01-08 结束，不是窗口终点 01-09，说明它不是被窗口截断的：不能合并。
    merged = merge_vintage_fragments(
        [
            _fragment(0, "2024-01-01", "2024-01-02", "2024-01-08", "7"),
            _fragment(1, "2024-01-01", "2024-01-10", "2024-01-19", "7"),
        ],
        _WINDOWS,
    )
    assert len(merged) == 2


@pytest.mark.unit
def test_merge_requires_the_right_piece_to_start_at_the_window_edge() -> None:
    merged = merge_vintage_fragments(
        [
            _fragment(0, "2024-01-01", "2024-01-02", "2024-01-09", "7"),
            _fragment(1, "2024-01-01", "2024-01-11", "2024-01-19", "7"),
        ],
        _WINDOWS,
    )
    assert len(merged) == 2


@pytest.mark.unit
def test_merge_does_not_join_non_adjacent_shards_or_other_observation_dates() -> None:
    skipped = merge_vintage_fragments(
        [
            _fragment(0, "2024-01-01", "2024-01-02", "2024-01-09", "7"),
            _fragment(2, "2024-01-01", "2024-01-20", "9999-12-31", "7"),
        ],
        _WINDOWS,
    )
    assert len(skipped) == 2
    other_date = merge_vintage_fragments(
        [
            _fragment(0, "2024-01-01", "2024-01-02", "2024-01-09", "7"),
            _fragment(1, "2024-01-02", "2024-01-10", "2024-01-19", "7"),
        ],
        _WINDOWS,
    )
    assert len(other_date) == 2


def _row(observed: str, start: str, end: str, value: str | None) -> dict[str, object]:
    return {
        "series_id": "CPIAUCSL",
        "observation_date": date.fromisoformat(observed),
        "realtime_start": date.fromisoformat(start),
        "realtime_end": date.fromisoformat(end),
        "value": None if value is None else Decimal(value),
        "source": SOURCE_LABEL,
    }


@pytest.mark.unit
def test_invariants_pass_on_a_contiguous_history_matching_current_values() -> None:
    rows = [
        _row("2024-01-01", "2024-01-02", "2024-01-05", "1"),
        _row("2024-01-01", "2024-01-06", "9999-12-31", "2"),
        _row("2024-01-02", "2024-01-02", "9999-12-31", None),
    ]
    current = {
        ("CPIAUCSL", date(2024, 1, 1)): Decimal("2"),
        ("CPIAUCSL", date(2024, 1, 2)): None,
    }
    check_vintage_invariants(rows, current)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("rows", "message"),
    [
        # (a) 中间缺一天：下一段起点不等于上一段终点加一天。
        (
            [
                _row("2024-01-01", "2024-01-02", "2024-01-05", "1"),
                _row("2024-01-01", "2024-01-07", "9999-12-31", "2"),
            ],
            "首尾相接或重叠",
        ),
        # (a) 重叠。
        (
            [
                _row("2024-01-01", "2024-01-02", "2024-01-06", "1"),
                _row("2024-01-01", "2024-01-06", "9999-12-31", "2"),
            ],
            "首尾相接或重叠",
        ),
        # (b) 最后一段不是开放的。
        (
            [_row("2024-01-01", "2024-01-02", "2024-01-30", "1")],
            "最后一段 realtime_end 不是 9999-12-31",
        ),
    ],
)
def test_invariants_reject_gaps_overlaps_and_closed_tails(
    rows: list[dict[str, object]], message: str
) -> None:
    current = {("CPIAUCSL", date(2024, 1, 1)): Decimal("1")}
    with pytest.raises(SourceFetchError, match=message):
        check_vintage_invariants(rows, current)


@pytest.mark.unit
def test_invariant_c_rejects_open_value_that_differs_from_current_request() -> None:
    rows = [_row("2024-01-01", "2024-01-02", "9999-12-31", "2")]
    with pytest.raises(SourceFetchError, match="不带 realtime 的当前值不一致"):
        check_vintage_invariants(rows, {("CPIAUCSL", date(2024, 1, 1)): Decimal("3")})


@pytest.mark.unit
def test_invariant_c_rejects_different_observation_date_sets() -> None:
    rows = [_row("2024-01-01", "2024-01-02", "9999-12-31", "2")]
    current = {
        ("CPIAUCSL", date(2024, 1, 1)): Decimal("2"),
        ("CPIAUCSL", date(2024, 1, 2)): Decimal("5"),
    }
    with pytest.raises(SourceFetchError, match="观测日集合不一致"):
        check_vintage_invariants(rows, current)


# ---- 值解析 ----


@pytest.mark.unit
def test_dot_and_empty_values_become_null_and_row_is_kept() -> None:
    fred = FakeFred(
        [
            seg("2024-01-01", "2024-01-02", "9999-12-31", "."),
            seg("2024-01-02", "2024-01-02", "9999-12-31", ""),
            seg("2024-01-03", "2024-01-02", "9999-12-31", "0"),
        ]
    )
    rows = fetch_observation_vintages("DFII10", api_key=_KEY, http=fred).rows
    assert [row["value"] for row in rows] == [None, None, Decimal("0.00000000")]


@pytest.mark.unit
def test_value_is_quantized_to_eight_places_for_stable_digest() -> None:
    fred = FakeFred([seg("2024-01-01", "2024-01-02", "9999-12-31", "1.5")])
    value = fetch_observation_vintages("DFII10", api_key=_KEY, http=fred).rows[0]["value"]
    assert value == Decimal("1.5")
    assert str(value) == "1.50000000"


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["1.123456789", "10000000000", "NaN", "Infinity", "abc"])
def test_invalid_values_fail_without_rounding(raw: str) -> None:
    fred = FakeFred([seg("2024-01-01", "2024-01-02", "9999-12-31", raw)])
    with pytest.raises(SourceFetchError):
        fetch_observation_vintages("DFII10", api_key=_KEY, http=fred)


@pytest.mark.unit
def test_largest_allowed_value_is_kept() -> None:
    # DECIMAL(18,8) 的上界之内：整数部分 10 位减一。
    fred = FakeFred([seg("2024-01-01", "2024-01-02", "9999-12-31", "9999999999")])
    value = fetch_observation_vintages("DFII10", api_key=_KEY, http=fred).rows[0]["value"]
    assert value == Decimal("9999999999.00000000")


# ---- 错误体与脱敏 ----


@pytest.mark.unit
def test_error_body_raises_with_error_message_and_no_api_key() -> None:
    body = json.dumps({"error_code": 400, "error_message": "Bad Request. vintage dates too many"})
    fred = FakeFred([], override=lambda _u, _p: FredHttpResponse(400, body))
    with pytest.raises(SourceFetchError) as caught:
        fetch_observation_vintages("DFII10", api_key=_KEY, http=fred)
    assert "vintage dates too many" in str(caught.value)
    assert _KEY not in str(caught.value)


@pytest.mark.unit
def test_api_key_echoed_in_error_message_is_redacted() -> None:
    body = json.dumps({"error_code": 400, "error_message": f"bad api_key={_KEY}"})
    fred = FakeFred([], override=lambda _u, _p: FredHttpResponse(400, body))
    with pytest.raises(SourceFetchError) as caught:
        fetch_observation_vintages("DFII10", api_key=_KEY, http=fred)
    assert _KEY not in str(caught.value)
    assert "***" in str(caught.value)


@pytest.mark.unit
def test_non_json_error_body_is_not_echoed() -> None:
    html = f"<html>api_key={_KEY}</html>"
    fred = FakeFred([], override=lambda _u, _p: FredHttpResponse(500, html))
    with pytest.raises(SourceFetchError) as caught:
        fetch_observation_vintages("DFII10", api_key=_KEY, http=fred)
    assert _KEY not in str(caught.value)
    assert "无 error_message" in str(caught.value)


@pytest.mark.unit
def test_transport_error_hides_url_with_key_and_does_not_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(url: str, **_: object) -> None:
        # requests 的异常消息会带完整 URL，也就带上 api_key。
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}?api_key={_KEY}")

    monkeypatch.setattr(requests, "get", _boom)
    with pytest.raises(SourceFetchError) as caught:
        fetch_observation_vintages(
            "DFII10",
            api_key=_KEY,
            http=RequestsFredHttp(sleep=lambda _: None, retry_sleep=lambda _: None),
        )
    assert "ConnectionError" in str(caught.value)
    assert _KEY not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


# ---- 请求间隔 ----


@pytest.mark.unit
def test_real_adapter_waits_until_one_second_since_previous_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **_: SimpleNamespace(status_code=200, text="{}"),
    )
    sleeps: list[float] = []
    # 第一次请求起点 0.0（第一次不等待）；第二次请求前时钟读到 0.2，所以还需等待 0.8 秒。
    ticks = iter([0.0, 0.2, 0.2])
    adapter = RequestsFredHttp(sleep=sleeps.append, clock=lambda: next(ticks))
    adapter.get(FRED_OBSERVATIONS_URL, {"series_id": "DFII10"})
    adapter.get(FRED_OBSERVATIONS_URL, {"series_id": "DFII10"})
    assert sleeps == [pytest.approx(0.8)]


# ---- 列映射 ----


@pytest.mark.unit
def test_row_maps_to_native_columns_with_dates_decimals_and_source_label() -> None:
    fred = FakeFred([seg("1947-01-01", "1994-02-17", "9999-12-31", "21.48")])
    row = fetch_observation_vintages("CPIAUCSL", api_key=_KEY, http=fred).rows[0]
    # 0018 起的表没有原生 ingested_at 列，行内也不带它。
    assert set(row) == set(FRED_OBSERVATION_VINTAGE.native_columns)
    assert "ingested_at" not in FRED_OBSERVATION_VINTAGE.native_columns
    assert row == {
        "series_id": "CPIAUCSL",
        "observation_date": date(1947, 1, 1),
        "realtime_start": date(1994, 2, 17),
        "realtime_end": date(9999, 12, 31),
        "value": Decimal("21.48000000"),
        "source": SOURCE_LABEL,
    }


@pytest.mark.unit
def test_spec_keys_are_series_date_and_realtime_start() -> None:
    assert FRED_OBSERVATION_VINTAGE.keys == ("series_id", "observation_date", "realtime_start")
    assert FRED_SERIES == ("DFII10", "T10YIE", "CPIAUCSL")
    assert FRED_OBSERVATION_VINTAGE.dataset == "src.macro.fred_observation_vintage"


# ---- 作业：干跑与写入语义 ----


class _FakeFredStore:
    """模拟 ``PostgresSrcStore`` 的 insert-only 语义，只实现 ``write_src_follow`` 用到的方法。
    ``state`` 是可见数据，``committed`` 是最近一次成功提交的快照，``rollback`` 恢复快照。
    """

    def __init__(self) -> None:
        self.state: dict[tuple[object, ...], dict[str, Any]] = {}
        self.committed: dict[tuple[object, ...], dict[str, Any]] = {}
        self.batches: list[int] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self._next_batch = 1
        self._business = ("realtime_end", "value")

    def existing_hashes(self, spec: object, keys: Sequence[tuple[object, ...]]) -> dict[Any, str]:
        return {key: self.state[key]["hash"] for key in keys if key in self.state}

    def existing_values(
        self, spec: object, keys: Sequence[tuple[object, ...]], columns: Sequence[str]
    ) -> dict[Any, tuple[object, ...]]:
        return {
            key: tuple(self.state[key]["row"][name] for name in columns)
            for key in keys
            if key in self.state
        }

    def existing_keys(
        self, spec: object, keys: Sequence[tuple[object, ...]]
    ) -> set[tuple[object, ...]]:
        return {key for key in keys if key in self.state}

    def latest_source_cursor(self, spec: object) -> str | None:
        return None

    def insert_batch(self, **kwargs: Any) -> int:
        batch_id = self._next_batch
        self._next_batch += 1
        self.batches.append(batch_id)
        return batch_id

    def delete_keys(self, spec: object, keys: Sequence[tuple[object, ...]]) -> None:
        for key in keys:
            self.state.pop(key, None)

    def insert_rows(
        self,
        spec: object,
        rows: Sequence[Mapping[str, object]],
        *,
        hashes: Sequence[str],
        batch_id: int,
        ingested_at: datetime,
    ) -> None:
        for row, digest in zip(rows, hashes, strict=True):
            key = (row["series_id"], row["observation_date"], row["realtime_start"])
            self.state[key] = {"hash": digest, "row": dict(row), "batch": batch_id}

    def readback_hashes(
        self, spec: object, batch_id: int, keys: Sequence[tuple[object, ...]]
    ) -> list[str]:
        return [
            self.state[key]["hash"]
            for key in keys
            if key in self.state and self.state[key]["batch"] == batch_id
        ]

    def mismatched_rows(
        self, spec: object, batch_id: int, rows: Sequence[Mapping[str, object]]
    ) -> list[tuple[object, ...]]:
        bad: list[tuple[object, ...]] = []
        for row in rows:
            key = (row["series_id"], row["observation_date"], row["realtime_start"])
            stored = self.state.get(key)
            if stored is None or any(stored["row"][c] != row[c] for c in self._business):
                bad.append(key)
        return bad

    def commit(self) -> None:
        self.commit_calls += 1
        self.committed = copy.deepcopy(self.state)

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.state = copy.deepcopy(self.committed)


@pytest.mark.unit
def test_dry_run_fetches_and_counts_without_touching_store(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    fred = FakeFred(
        [
            seg("2024-01-01", "2024-01-02", "9999-12-31", "1.1"),
            seg("2024-01-02", "2024-01-03", "9999-12-31", "."),
        ]
    )
    result = ingest_macro_fred(
        settings=settings,
        paths=resolve_var_paths(settings, repo_root=tmp_path),
        series_ids=["CPIAUCSL"],
        http=fred,
        now=lambda: _INGESTED,
    )
    assert result.written is False
    assert result.row_count == 2
    assert result.series[0].pages == 1
    assert result.dml_count == 0
    logs = _run_logs(tmp_path, settings)
    assert len(logs) == 1
    assert logs[0]["status"] == "success"
    # run log 与异常都不得含 api_key。
    assert _KEY not in json.dumps(logs)


@pytest.mark.unit
def test_write_inserts_then_skips_unchanged_then_replaces_on_realtime_end_change(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, allow_db_write=True)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    store = _FakeFredStore()

    def run(segments: list[Segment]) -> Any:
        return ingest_macro_fred(
            settings=settings,
            paths=paths,
            write_db=True,
            series_ids=["CPIAUCSL"],
            http=FakeFred(segments),
            store=store,
            now=lambda: _INGESTED,
        )

    first = run([seg("2024-01-01", "2024-01-02", "9999-12-31", "1.1")])
    assert first.inserted == 1
    assert first.dml_count == 2
    assert store.commit_calls == 1
    # 同一份数据再跑：指纹相同，跳过。
    again = run([seg("2024-01-01", "2024-01-02", "9999-12-31", "1.1")])
    assert (again.inserted, again.skipped, again.replaced) == (0, 1, 0)
    # 源端某版本被新版本取代：旧版本 realtime_end 从 9999-12-31 变成具体日期（同键替换），
    # 新版本是新键（插入）。
    changed = run(
        [
            seg("2024-01-01", "2024-01-02", "2024-06-30", "1.1"),
            seg("2024-01-01", "2024-07-01", "9999-12-31", "1.2"),
        ]
    )
    assert (changed.replaced, changed.inserted) == (1, 1)
    old_key = ("CPIAUCSL", date(2024, 1, 1), date(2024, 1, 2))
    assert store.state[old_key]["row"]["realtime_end"] == date(2024, 6, 30)
    assert len(store.state) == 2
    assert len(_run_logs(tmp_path, settings)) == 3


@pytest.mark.unit
def test_invariant_failure_writes_nothing_and_logs_the_failure(tmp_path: Path) -> None:
    settings = _settings(tmp_path, allow_db_write=True)
    store = _FakeFredStore()

    def stale_current(url: str, params: dict[str, str]) -> FredHttpResponse | None:
        # 不带 realtime 的当前值与版本区间的开放段对不上：不变量 (c) 失败，不得写库。
        if url == FRED_OBSERVATIONS_URL and "realtime_start" not in params:
            body = {
                "count": 1,
                "offset": 0,
                "observations": [
                    {
                        "date": "2024-01-01",
                        "realtime_start": "2024-01-02",
                        "realtime_end": "9999-12-31",
                        "value": "9.9",
                    }
                ],
            }
            return _raw(body)
        return None

    with pytest.raises(SourceFetchError, match="不带 realtime 的当前值不一致"):
        ingest_macro_fred(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            write_db=True,
            series_ids=["CPIAUCSL"],
            http=FakeFred(
                [seg("2024-01-01", "2024-01-02", "9999-12-31", "1.1")],
                override=stale_current,
            ),
            store=store,
            now=lambda: _INGESTED,
        )
    assert store.state == {}
    assert store.commit_calls == 0
    logs = _run_logs(tmp_path, settings)
    assert logs[0]["status"] == "failure"


@pytest.mark.unit
def test_fingerprint_helper_excludes_source_and_ingested_at() -> None:
    # 指纹只覆盖键与业务列。realtime_end 变化会改指纹，source 与 ingested_at 不会。
    base = {
        "series_id": "CPIAUCSL",
        "observation_date": date(2024, 1, 1),
        "realtime_start": date(2024, 1, 2),
        "realtime_end": date(9999, 12, 31),
        "value": Decimal("1.00000000"),
        "source": SOURCE_LABEL,
    }
    columns = fingerprint_columns(FRED_OBSERVATION_VINTAGE)
    assert "source" not in columns
    assert "ingested_at" not in columns
    later = {**base, "source": "other"}
    assert row_hash(base, columns) == row_hash(later, columns)


@pytest.mark.unit
def test_missing_api_key_is_a_config_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path, key="")
    with pytest.raises(ConfigError, match="QUANTAGENT_FRED_API_KEY"):
        ingest_macro_fred(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            http=FakeFred([]),
        )


@pytest.mark.unit
def test_unknown_or_duplicate_series_are_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    with pytest.raises(IngestError, match="只允许"):
        ingest_macro_fred(settings=settings, paths=paths, series_ids=["GPR"], http=FakeFred([]))
    with pytest.raises(IngestError, match="重复"):
        ingest_macro_fred(
            settings=settings,
            paths=paths,
            series_ids=["DFII10", "DFII10"],
            http=FakeFred([]),
        )


@pytest.mark.unit
def test_write_gate_blocks_real_write_before_any_commit(tmp_path: Path) -> None:
    settings = _settings(tmp_path, allow_db_write=False)
    store = _FakeFredStore()
    with pytest.raises(WriteGateError, match="QUANTAGENT_ALLOW_DB_WRITE"):
        ingest_macro_fred(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            write_db=True,
            series_ids=["CPIAUCSL"],
            http=FakeFred([seg("2024-01-01", "2024-01-02", "9999-12-31", "1")]),
            store=store,
            now=lambda: _INGESTED,
        )
    assert store.commit_calls == 0
    assert store.state == {}


@pytest.mark.unit
def test_office_profile_is_rejected_even_for_dry_run(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        var_root=tmp_path / "var",
        profile="office",
        fred_api_key=SecretStr(_KEY),
    )
    with pytest.raises(IngestError, match="profile=office"):
        ingest_macro_fred(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            series_ids=["CPIAUCSL"],
            http=FakeFred([seg("2024-01-01", "2024-01-02", "9999-12-31", "1")]),
        )

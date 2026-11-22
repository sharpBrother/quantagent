"""前瞻收益 open2open（5D/10D）与 wx2 旧表 ``alpha_factory_forward_return_d`` 对拍（比对域 all_a(T)）。

数据来源：
- ``tests/golden/market_data/forward_return_wx2.json``：各 (信号日 T, horizon) 的旧表 digest、停牌列表、
  all_a 范围内的 digest，以及两个样本日的逐行旧值（``full_rows_5d``）。抓取 SQL 与 digest 规则写在 provenance 里。
- ``tests/golden/market_data/forward_return_wx2_explained.json``：本地与 wx2 有差异、且已给出解释的行，
  每行带 wx2 两端 adj_open / open / adj_factor / 状态码 与旧值。

新链路走正式读取路径：``PostgresUniverseRepository``（all_a 股票池）、``PostgresDailyPriceRepository``
（本地 PG 只读）、``LakeCalendarRepository``（SSE），再交给 ``build_forward_returns``。不写任何存储。

比对规则（每个 (T,h) 都要过）：

(a) 旧 valid 且 wx2 端点停牌（状态码 0）的代码，新链路不产，这是已裁定的口径。测试先核实本地端点同样停牌，
    再把这些代码的旧值并回去还原旧集合。
(e1) 源价差：本地端点 adj_open 与 wx2 不同。测试用 fixture 的 wx2 价调用 ``build_forward_returns``，
    算出的值必须与旧值在 1e-9 内一致。这一步同时是口径对拍：旧值 = 新公式 + wx2 输入价。
(e2) 旧表陈旧：本地端点 adj_open 与 wx2 相同。用 wx2 价算出的值必须等于本地结果，且与旧值不一致。
(e3) 本地缺行：all_a(T) 内，旧 valid，本地端点无行。本批次为 0 行，测试仍检查这条路径。
(e4) 其余差异，必须为 0。

逐行的 digest 只能覆盖 e1/e2/e3 之外的行。方法：把 (a)、(e1)、(e2)、(e3) 的代码按旧值还原，再与
旧表 all_a digest 比。还原前，(e1)(e2)(e3) 的代码已分别核实了解释。digest 相等即说明其余行逐一相等。
精度：旧表以 10 位小数存储，新值先按同样精度取整（ROUND_HALF_UP）再做 1e-6 量化。
用 1e-6 量化 digest 而不是逐行，是因为 wx2 旧值只有 digest 存档。两天的逐行明细见下方第二个测试。
"""

from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from quantagent.adapters.lake.trade_calendar import LakeCalendarRepository
from quantagent.adapters.postgres.daily_prices import (
    PostgresDailyPriceRepository,
    load_price_visibility,
)
from quantagent.adapters.postgres.universe import PostgresUniverseRepository
from quantagent.domain.forward_return import build_forward_returns, forward_return_read_window
from quantagent.domain.prices.types import DailyPrice
from quantagent.domain.universe.all_a import ALL_A_UNIVERSE_ID
from quantagent.platform.config import get_settings
from quantagent.platform.pg import connect
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from quantagent.contracts.spec import VisibilityContract
    from quantagent.domain.calendar.types import CalendarDay
    from quantagent.domain.forward_return import ForwardReturn

_GOLDEN = Path(__file__).parents[1] / "golden" / "market_data"
_FIXTURE = _GOLDEN / "forward_return_wx2.json"
_EXPLAINED = _GOLDEN / "forward_return_wx2_explained.json"
_AS_OF = date(2026, 11, 6)
_HORIZONS = ("5d", "10d")
_Q6 = Decimal("0.000001")
_Q10 = Decimal("0.0000000001")
_VALUE_TOL = 1e-9
_MISSING = "missing"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _q6(value: Decimal) -> Decimal:
    return value.quantize(_Q6, rounding=ROUND_HALF_UP)


def _stored(value: Decimal) -> Decimal:
    """旧表以 10 位小数存储。新值先按同样精度取整，再进入 1e-6 比对。"""
    return value.quantize(_Q10, rounding=ROUND_HALF_UP)


def _new_q6(value: float) -> Decimal:
    return _q6(_stored(Decimal(repr(value))))


def _pairs_digest(pairs: Sequence[tuple[str, Decimal]]) -> str:
    text = "\n".join(f"{code}|{format(value, 'f')}" for code, value in sorted(pairs))
    return sha256(text.encode("utf-8")).hexdigest()


def _codes_digest(codes: Sequence[str]) -> str:
    return sha256("\n".join(sorted(codes)).encode("utf-8")).hexdigest()


def _ymd_to_date(value: str) -> date:
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def _wx2_price(code: str, dt: date, rec: Mapping[str, Any]) -> DailyPrice:
    """把 fixture 的 wx2 端点价放进 ``DailyPrice``，让 domain 函数直接计算。其余字段对本计算无用。"""
    return DailyPrice(
        trade_dt=dt,
        wind_code=code,
        open=None,
        high=None,
        low=None,
        close=None,
        volume=None,
        amount=None,
        pct_change=None,
        adj_open=Decimal(str(rec["adj_open"])),
        trade_status_code=int(rec["status"]),
    )


def _domain_value(
    entry: Mapping[str, Any],
    *,
    days: Sequence[CalendarDay],
    contract: VisibilityContract,
    horizon: str,
) -> float:
    """用 fixture 的 wx2 端点价调用 ``build_forward_returns``，返回算出的值。不在测试里重写公式。"""
    code = str(entry["code"])
    signal = date.fromisoformat(str(entry["signal_dt"]))
    prices = [
        _wx2_price(code, _ymd_to_date(str(entry["start_dt"])), entry["wx2_start"]),
        _wx2_price(code, _ymd_to_date(str(entry["end_dt"])), entry["wx2_end"]),
    ]
    out = build_forward_returns(
        prices,
        days,
        signal_dates=(signal,),
        contract=contract,
        as_of=_AS_OF,
        horizons=(horizon,),
    )
    assert len(out) == 1, f"wx2 价按新函数算不出值: {code} {signal} {horizon}"
    return out[0].value


def _explained_index(payload: Mapping[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in payload["explained_differences"]:
        index.setdefault((str(entry["signal_dt"]), str(entry["horizon"])), []).append(entry)
    return index


def _check_explained(
    entry: Mapping[str, Any],
    *,
    days: Sequence[CalendarDay],
    contract: VisibilityContract,
    rows: Mapping[tuple[str, date], DailyPrice],
    local: Mapping[str, ForwardReturn],
    horizon: str,
) -> list[str]:
    """核实一条解释行。返回问题列表，空即通过。"""
    code = str(entry["code"])
    cls = str(entry["class"])
    start = _ymd_to_date(str(entry["start_dt"]))
    end = _ymd_to_date(str(entry["end_dt"]))
    local_start = rows.get((code, start))
    local_end = rows.get((code, end))
    problems: list[str] = []
    if cls == "e3":
        if local_start is not None and local_end is not None and code in local:
            problems.append(f"(e3) 本地端点齐全且已产出，不是缺行: {code}")
        return problems
    if local_start is None or local_end is None:
        return [f"({cls}) 本地端点缺行，不能按 {cls} 解释: {code}"]
    wx_start = Decimal(str(entry["wx2_start"]["adj_open"]))
    wx_end = Decimal(str(entry["wx2_end"]["adj_open"]))
    local_same = local_start.adj_open == wx_start and local_end.adj_open == wx_end
    value = _domain_value(entry, days=days, contract=contract, horizon=horizon)
    old = Decimal(str(entry["old_value"]))
    if cls == "e1":
        if local_same:
            problems.append(f"(e1) 本地端点 adj_open 与 wx2 相同，不符合源价差: {code}")
        if abs(Decimal(repr(value)) - old) > Decimal(str(_VALUE_TOL)):
            problems.append(f"(e1) wx2 价算出 {value!r} 与旧值 {old} 差超过 1e-9: {code}")
        if code not in local:
            problems.append(f"(e1) 本地未产出该行: {code}")
    elif cls == "e2":
        if not local_same:
            problems.append(f"(e2) 本地端点 adj_open 与 wx2 不同，应归 e1: {code}")
        if code not in local or abs(local[code].value - value) > 1e-12:
            problems.append(f"(e2) wx2 价算出 {value!r} 与本地结果不一致: {code}")
        if abs(Decimal(repr(value)) - old) <= Decimal(str(_VALUE_TOL)):
            problems.append(f"(e2) wx2 价算出值与旧值一致，旧表不陈旧: {code}")
    else:
        problems.append(f"未知解释类别 {cls}: {code}")
    return problems


def _check_horizon(
    *,
    signal: date,
    horizon: str,
    block: Mapping[str, Any],
    all_a: frozenset[str],
    rows: Mapping[tuple[str, date], DailyPrice],
    local: Mapping[str, ForwardReturn],
    explained: Sequence[Mapping[str, Any]],
    days: Sequence[CalendarDay],
    contract: VisibilityContract,
    suspended: Sequence[tuple[str, str]],
    start_dt: date,
    end_dt: date,
) -> tuple[dict[str, int], list[str]]:
    problems: list[str] = []
    counts: dict[str, int] = {}

    # (a)：旧 valid 且 wx2 端点停牌，并且代码在 all_a(T) 内。本地端点必须同样停牌。
    a_pairs = [(code, Decimal(value)) for code, value in suspended if code in all_a]
    a_verified: list[tuple[str, Decimal]] = []
    for code, value in a_pairs:
        if code in local:
            problems.append(f"(a) 停牌代码本地仍产出: {code}")
            continue
        statuses = [
            rows[(code, start_dt)].trade_status_code if (code, start_dt) in rows else _MISSING,
            rows[(code, end_dt)].trade_status_code if (code, end_dt) in rows else _MISSING,
        ]
        if 0 in statuses:
            a_verified.append((code, value))
        else:
            problems.append(f"(a) 本地端点未见停牌，不能豁免: {code} statuses={statuses}")
    counts["a"] = len(a_pairs)
    counts["a_verified"] = len(a_verified)

    # 解释行：逐条核实，再把旧值还原进集合。
    replaced: dict[str, Decimal] = {}
    counts["e1"] = counts["e2"] = counts["e3"] = 0
    for entry in explained:
        cls = str(entry["class"])
        counts[cls] = counts.get(cls, 0) + 1
        problems.extend(
            _check_explained(
                entry,
                days=days,
                contract=contract,
                rows=rows,
                local=local,
                horizon=horizon,
            )
        )
        code = str(entry["code"])
        if code not in all_a:
            problems.append(f"解释行不在 all_a(T) 内: {code}")
        replaced[code] = Decimal(str(entry["old_value"]))

    # 还原：本地产出（未被解释的）用新值，解释行与 (a) 用旧值，e3 缺行也用旧值。
    actual: list[tuple[str, Decimal]] = [
        (code, _new_q6(fr.value)) for code, fr in local.items() if code not in replaced
    ]
    actual.extend((code, _q6(value)) for code, value in replaced.items())
    actual.extend((code, _q6(value)) for code, value in a_verified)
    counts["new"] = len(local)
    counts["restored"] = len(actual)
    counts["old_valid_all_a"] = int(block["valid_count"])
    counts["old_valid_outside_all_a"] = int(block["valid_outside_all_a_count"])
    counts["old_incomplete_all_a"] = len(block["incomplete_codes"])

    expect_digest = str(block["valid_digest"])
    expect_codes = str(block["valid_codes_digest"])
    got_codes = [code for code, _ in actual]
    if (
        len(actual) != counts["old_valid_all_a"]
        or _pairs_digest(actual) != expect_digest
        or _codes_digest(got_codes) != expect_codes
    ):
        problems.append(
            f"(e4) 还原后与旧表 all_a digest 不一致: 还原 {len(actual)} 行，"
            f"旧表 {counts['old_valid_all_a']} 行。旧表侧只存 digest，逐行明细见 test_full_rows_match。"
        )

    # 旧 incomplete 不应产出；本地产出的 incomplete 代码记为问题。
    inc_produced = sorted(code for code in block["incomplete_codes"] if code in local)
    if inc_produced:
        problems.append(f"旧 incomplete 而新产出: {inc_produced[:5]}")
    return counts, problems


@pytest.mark.integration
def test_all_a_forward_return_matches_wx2_with_explained_differences() -> None:
    payload = _load(_FIXTURE)
    explained = _explained_index(_load(_EXPLAINED))
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    contract = load_price_visibility()
    conn = connect(settings, "src")
    conn.read_only = True
    failures: list[str] = []
    try:
        universe = PostgresUniverseRepository(conn)
        prices_repo = PostgresDailyPriceRepository(conn, contract=contract)
        for sample in payload["samples"]:
            signal = str(sample["signal_dt"])
            t = date.fromisoformat(signal)
            days = calendar.list_days(as_of=_AS_OF, exchange="SSE", start=t, end=_AS_OF)
            members = universe.members_at(as_of=_AS_OF, dt=t, universe_id=ALL_A_UNIVERSE_ID)
            all_a = frozenset(member.asset_id for member in members)
            assert len(all_a) == sample["all_a_count"], f"{signal} all_a 成员数与 fixture 不同"
            window = forward_return_read_window(
                days, signal_dates=(t,), horizons=_HORIZONS, as_of=_AS_OF
            )
            assert window is not None, signal
            rows_list = prices_repo.list_prices(
                as_of=_AS_OF,
                start=window[0],
                end=window[1],
                wind_codes=tuple(sorted(all_a)),
            )
            rows = {(p.wind_code, p.trade_dt): p for p in rows_list}
            produced = build_forward_returns(
                rows_list,
                days,
                signal_dates=(t,),
                contract=contract,
                as_of=_AS_OF,
                horizons=_HORIZONS,
            )
            for horizon in _HORIZONS:
                info = sample["horizons"][horizon]
                start_dt = _ymd_to_date(str(info["source_start_date"]))
                end_dt = _ymd_to_date(str(info["source_end_date"]))
                local = {r.asset_id: r for r in produced if r.horizon == horizon}
                counts, problems = _check_horizon(
                    signal=t,
                    horizon=horizon,
                    block=info["all_a"],
                    all_a=all_a,
                    rows=rows,
                    local=local,
                    explained=explained.get((signal, horizon), []),
                    days=days,
                    contract=contract,
                    suspended=[(str(c), str(v)) for c, v in info["suspended_endpoint_valid"]],
                    start_dt=start_dt,
                    end_dt=end_dt,
                )
                print(
                    f"{signal} {horizon}: all_a={len(all_a)} 旧 valid(all_a)={counts['old_valid_all_a']} "
                    f"旧 valid(all_a 外，不比)={counts['old_valid_outside_all_a']} 新产出={counts['new']} "
                    f"(a) {counts['a_verified']}/{counts['a']} "
                    f"e1={counts['e1']} e2={counts['e2']} e3={counts['e3']} "
                    f"问题={len(problems)}"
                )
                failures.extend(f"{signal} {horizon}: {p}" for p in problems)
    finally:
        conn.close()
    assert not failures, "all_a 对拍失败，不得豁免:\n" + "\n".join(failures[:80])


@pytest.mark.integration
def test_full_rows_match_wx2_row_by_row() -> None:
    """两个样本日的 5D 逐行比对（all_a 范围）：valid 逐行一致；旧 incomplete 不产；解释行按 explained 文件核实。"""
    payload = _load(_FIXTURE)
    explained = _explained_index(_load(_EXPLAINED))
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    calendar = LakeCalendarRepository(paths.lake / "std" / "trade_calendar")
    contract = load_price_visibility()
    conn = connect(settings, "src")
    conn.read_only = True
    try:
        universe = PostgresUniverseRepository(conn)
        prices_repo = PostgresDailyPriceRepository(conn, contract=contract)
        for signal, block in payload["full_rows_5d"].items():
            t = date.fromisoformat(signal)
            days = calendar.list_days(as_of=_AS_OF, exchange="SSE", start=t, end=_AS_OF)
            all_a = frozenset(
                member.asset_id
                for member in universe.members_at(as_of=_AS_OF, dt=t, universe_id=ALL_A_UNIVERSE_ID)
            )
            window = forward_return_read_window(
                days, signal_dates=(t,), horizons=("5d",), as_of=_AS_OF
            )
            assert window is not None
            rows_list = prices_repo.list_prices(
                as_of=_AS_OF,
                start=window[0],
                end=window[1],
                wind_codes=tuple(sorted(all_a)),
            )
            rows = {(p.wind_code, p.trade_dt): p for p in rows_list}
            produced = {
                r.asset_id: r
                for r in build_forward_returns(
                    rows_list,
                    days,
                    signal_dates=(t,),
                    contract=contract,
                    as_of=_AS_OF,
                    horizons=("5d",),
                )
            }
            start_dt = _ymd_to_date(str(block["source_start_date"]))
            end_dt = _ymd_to_date(str(block["source_end_date"]))
            explained_codes = {str(e["code"]) for e in explained.get((signal, "5d"), [])}
            problems: list[str] = []
            wx_valid: dict[str, Decimal] = {}
            for code, fr, label in block["rows"]:
                if label == "valid" and code in all_a:
                    wx_valid[code] = _q6(Decimal(fr))
            for code, row in produced.items():
                if code not in wx_valid and code not in explained_codes:
                    problems.append(f"新产出而旧表非 valid: {code}")
                elif (
                    code in wx_valid
                    and code not in explained_codes
                    and _new_q6(row.value) != wx_valid[code]
                ):
                    problems.append(f"值不一致: {code} 新={row.value!r} 旧={wx_valid[code]}")
            for code, value in wx_valid.items():
                if code in produced or code in explained_codes:
                    continue
                st = (
                    rows[(code, start_dt)].trade_status_code
                    if (code, start_dt) in rows
                    else _MISSING,
                    rows[(code, end_dt)].trade_status_code if (code, end_dt) in rows else _MISSING,
                )
                if 0 not in st:
                    problems.append(f"新缺且非停牌: {code} value={value} status={st}")
            print(
                f"{signal} 5d 逐行: all_a 内旧 valid={len(wx_valid)} 新产出={len(produced)} 问题={len(problems)}"
            )
            assert not problems, f"{signal} 5D 逐行差异:\n" + "\n".join(problems[:50])
    finally:
        conn.close()

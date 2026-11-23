"""PostgreSQL 宏观读取：过滤值与旧仓一致，截止按各自契约，版本走 domain 规则。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from quantagent.adapters.postgres.macro import PostgresMacroRepository, load_macro_visibilities
from quantagent.contracts.loader import load_bundle
from quantagent.domain.errors import MacroLookupError, PitUnsupportedError


def _repo(rows: list[tuple[object, ...]]) -> tuple[PostgresMacroRepository, MagicMock]:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = rows
    return PostgresMacroRepository(conn), cur


@pytest.mark.unit
def test_cgb_10y_uses_legacy_curve_filter_and_same_day_cutoff() -> None:
    repo, cur = _repo([("20240102", Decimal("2.5500"))])
    rows = repo.list_observations(
        as_of=date(2024, 1, 3),
        start=date(2024, 1, 2),
        end=date(2024, 1, 31),
        series_ids=("cn_cgb_10y",),
    )
    statement, params = cur.execute.call_args.args
    assert '"src_wind"."CBONDCURVECNBD"' in statement
    # 与旧仓 get_china_cgb_10y_yield_curve 相同：1232 / 到期收益率 / 10 年。
    assert params == ("20240102", "20240103", 1232, "2", Decimal(10))
    assert [(r.observation_date, r.value, r.knowledge_dt) for r in rows] == [
        (date(2024, 1, 2), Decimal("2.5500"), date(2024, 1, 2))
    ]


@pytest.mark.unit
def test_us_treasury_reads_10y_maturity_visible_next_day() -> None:
    # 美债按美国交易日，严格早于 as_of 才可见：as_of=01-02 只能看到 01-01 及以前。
    repo, cur = _repo([("20240101", Decimal("3.95"))])
    repo.list_observations(
        as_of=date(2024, 1, 2),
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
        series_ids=("us_ust_10y",),
    )
    statement, params = cur.execute.call_args.args
    assert '"src_tushare"."us_treasury_yield"' in statement
    assert params == ("20240101", "20240101", "10y")


@pytest.mark.unit
def test_tips_uses_strict_vintage_cutoff() -> None:
    repo, cur = _repo(
        [
            (date(2024, 1, 2), date(2024, 1, 2), date(2024, 1, 3), Decimal("1.70")),
            (date(2024, 1, 2), date(2024, 1, 4), date(9999, 12, 31), Decimal("1.72")),
        ]
    )
    rows = repo.list_observations(
        as_of=date(2024, 1, 4),
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        series_ids=("us_tips_10y",),
    )
    _statement, params = cur.execute.call_args.args
    # strict：realtime_start 必须早于 as_of，即不晚于 as_of 前一天。
    assert params == (date(2024, 1, 1), date(2024, 1, 31), date(2024, 1, 3), "DFII10")
    assert [(r.value, r.knowledge_dt) for r in rows] == [(Decimal("1.70"), date(2024, 1, 2))]


@pytest.mark.unit
def test_duplicate_business_day_fails_closed() -> None:
    repo, _cur = _repo([("20240102", Decimal("2.55")), ("20240102", Decimal("2.56"))])
    with pytest.raises(MacroLookupError, match="多个生效版本"):
        repo.list_observations(
            as_of=date(2024, 1, 3),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            series_ids=("cn_cgb_10y",),
        )


@pytest.mark.unit
def test_contract_cutoff_column_drift_fails() -> None:
    contracts = load_macro_visibilities()
    drifted = contracts["src.wind.cbondcurvecnbd"].model_copy(update={"event_field": "OPDATE"})
    contracts["src.wind.cbondcurvecnbd"] = drifted
    repo = PostgresMacroRepository(MagicMock(), contracts=contracts)
    with pytest.raises(PitUnsupportedError, match="截止列"):
        repo.list_observations(
            as_of=date(2024, 1, 3),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            series_ids=("cn_cgb_10y",),
        )


@pytest.mark.unit
def test_china_cpi_reads_oecd_series_from_alfred() -> None:
    repo, cur = _repo([(date(2024, 1, 1), date(2024, 2, 20), None, Decimal("-0.8"))])
    rows = repo.list_observations(
        as_of=date(2024, 3, 1),
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        series_ids=("cn_cpi_yoy",),
    )
    _statement, params = cur.execute.call_args.args
    assert params[-1] == "CPALTT01CNM659N"
    assert [(r.value, r.knowledge_dt) for r in rows] == [(Decimal("-0.8"), date(2024, 2, 20))]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("series_id", "fred_id"),
    [("de_bund_10y", "IRLTLT01DEM156N"), ("jp_jgb_10y", "IRLTLT01JPM156N")],
)
def test_oecd_yields_read_from_alfred(series_id: str, fred_id: str) -> None:
    repo, cur = _repo([])
    repo.list_observations(
        as_of=date(2024, 3, 1),
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        series_ids=(series_id,),
    )
    _statement, params = cur.execute.call_args.args
    assert params[-1] == fred_id


@pytest.mark.unit
def test_nbs_cpi_reads_jydb_published_values() -> None:
    # 契约非 strict：InfoPublDate 的日期当天可见，截止日就是 as_of。
    repo, cur = _repo([(date(2026, 10, 31), date(2026, 11, 9), Decimal("0.7"), 0)])
    rows = repo.list_observations(
        as_of=date(2026, 11, 20),
        start=date(2006, 1, 1),
        end=date(2026, 11, 20),
        series_ids=("cn_cpi_yoy_nbs",),
    )
    statement, params = cur.execute.call_args.args
    assert '"src_jydb"."C_ED_MacroIndicatorData"' in statement
    # timestamp 截止列必须按日期比较，发布当天带时刻的行也要算进来。
    assert "::date" in statement
    assert params == (date(2006, 1, 1), date(2026, 11, 20), date(2026, 11, 20), 110255493)
    assert [(r.value, r.knowledge_dt) for r in rows] == [(Decimal("0.7"), date(2026, 11, 9))]


@pytest.mark.unit
def test_nbs_cpi_same_period_takes_latest_release() -> None:
    repo, _cur = _repo(
        [
            (date(2026, 10, 31), date(2026, 11, 9), Decimal("0.7"), 0),
            (date(2026, 10, 31), date(2026, 11, 12), Decimal("0.8"), 0),
        ]
    )
    window = {"start": date(2026, 10, 1), "end": date(2026, 10, 31)}
    first = repo.list_observations(
        as_of=date(2026, 11, 10), series_ids=("cn_cpi_yoy_nbs",), **window
    )
    second = repo.list_observations(
        as_of=date(2026, 11, 20), series_ids=("cn_cpi_yoy_nbs",), **window
    )
    assert [(r.value, r.knowledge_dt) for r in first] == [(Decimal("0.7"), date(2026, 11, 9))]
    assert [(r.value, r.knowledge_dt) for r in second] == [(Decimal("0.8"), date(2026, 11, 12))]


@pytest.mark.unit
def test_nbs_cpi_same_publish_day_fails_closed() -> None:
    repo, _cur = _repo(
        [
            (date(2026, 10, 31), date(2026, 11, 9), Decimal("0.7"), 0),
            (date(2026, 10, 31), date(2026, 11, 9), Decimal("0.8"), 0),
        ]
    )
    with pytest.raises(MacroLookupError, match="同一发布日"):
        repo.list_observations(
            as_of=date(2026, 11, 20),
            start=date(2026, 10, 1),
            end=date(2026, 10, 31),
            series_ids=("cn_cpi_yoy_nbs",),
        )


@pytest.mark.unit
@pytest.mark.parametrize("power", [1, -1, None])
def test_nbs_cpi_nonzero_power_fails_closed(power: int | None) -> None:
    repo, _cur = _repo([(date(2026, 10, 31), date(2026, 11, 9), Decimal("0.7"), power)])
    with pytest.raises(MacroLookupError, match="数量级"):
        repo.list_observations(
            as_of=date(2026, 11, 20),
            start=date(2026, 10, 1),
            end=date(2026, 10, 31),
            series_ids=("cn_cpi_yoy_nbs",),
        )


@pytest.mark.unit
def test_nbs_cpi_timestamp_cutoff_requires_date_only() -> None:
    dataset = "src.jydb.c_ed_macroindicatordata"
    contracts = load_macro_visibilities()
    visibility = contracts[dataset].visibility.model_copy(update={"date_only": False})
    contracts[dataset] = contracts[dataset].model_copy(update={"visibility": visibility})
    repo = PostgresMacroRepository(MagicMock(), contracts=contracts)
    with pytest.raises(PitUnsupportedError, match="date_only"):
        repo.list_observations(
            as_of=date(2026, 11, 20),
            start=date(2026, 10, 1),
            end=date(2026, 10, 31),
            series_ids=("cn_cpi_yoy_nbs",),
        )


@pytest.mark.unit
def test_nbs_cpi_fallback_contract_fails_closed() -> None:
    dataset = "src.jydb.c_ed_macroindicatordata"
    contracts = load_macro_visibilities()
    # 货币供应带 earliest + fixed_lag fallback；宏观读取还没有逐行定级，必须拒绝。
    money = load_bundle().visibilities["src.jydb.ed_moneysupply"]
    contracts[dataset] = contracts[dataset].model_copy(update={"visibility": money.visibility})
    repo = PostgresMacroRepository(MagicMock(), contracts=contracts)
    with pytest.raises(PitUnsupportedError, match="fallback"):
        repo.list_observations(
            as_of=date(2026, 11, 20),
            start=date(2026, 10, 1),
            end=date(2026, 10, 31),
            series_ids=("cn_cpi_yoy_nbs",),
        )

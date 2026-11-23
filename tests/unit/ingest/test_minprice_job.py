from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pyarrow as pa
import pytest

from quantagent.domain.minute_exclusions import JANUARY_21_EXCLUDED
from quantagent.ingest.errors import SourceFetchError, SourceNotReadyError
from quantagent.ingest.jobs.minprice import assert_daily_ready, ingest_day
from quantagent.platform.config import Settings
from quantagent.platform.storage.paths import resolve_var_paths


def test_dry_run_reads_source_without_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    row = (
        "000001.SZ",
        datetime(2026, 11, 20, 9, 30),
        *[Decimal("12")] * 4,
        Decimal("10"),
        Decimal("120"),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([[row]]))
    settings = Settings(var_root=tmp_path, allow_db_write=False)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    pg = MagicMock()
    result = ingest_day(
        MagicMock(),
        pg,
        trade_date=date(2026, 11, 20),
        settings=settings,
        paths=paths,
        calendar=MagicMock(),
    )
    assert result == "dry_run"
    pg.cursor.assert_not_called()
    assert not tmp_path.joinpath("lake").exists()


def test_empty_source_stops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([]))
    settings = Settings(var_root=tmp_path, allow_db_write=False)
    with pytest.raises(SourceFetchError):
        ingest_day(
            MagicMock(),
            MagicMock(),
            trade_date=date(2024, 7, 29),
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
        )


def test_daily_ready_requires_close_and_previous_day_coverage() -> None:
    full = pa.table(
        {
            "ts_code": [f"{i:06d}.SZ" for i in range(95)],
            "trade_time": [datetime(2026, 11, 20, 15, 0)] * 95,
        }
    )
    assert_daily_ready(full, 100)
    with pytest.raises(SourceNotReadyError):
        assert_daily_ready(full, 101)
    partial = full.set_column(1, "trade_time", pa.array([datetime(2026, 11, 20, 14, 59)] * 95))
    with pytest.raises(SourceNotReadyError):
        assert_daily_ready(partial, 100)


def test_accepted_open_low_difference_is_recorded_in_run_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    row = (
        "000001.SZ",
        datetime(2026, 11, 20, 9, 31),
        Decimal("9.95"),
        Decimal("11"),
        Decimal("10"),
        Decimal("10.5"),
        Decimal("10"),
        Decimal("100"),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([[row]]))
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda *a, **k: SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=date(2026, 11, 20),
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            write_db=True,
        )
        == "inserted"
    )
    assert logs[0].tolerated_open_below_low == [
        {
            "ts_code": "000001.SZ",
            "trade_time": "2026-11-20 09:31:00",
            "open": "9.9500",
            "low": "10.0000",
        }
    ]


def test_january_21_excludes_affected_stocks_and_corrects_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    day = date(2026, 1, 21)
    codes = sorted(JANUARY_21_EXCLUDED)
    rows = []
    for code in codes:
        rows.append(
            (code, datetime(2026, 1, 21, 9, 30), *[Decimal("10")] * 4, Decimal("1"), Decimal("-1"))
        )
    for code in codes[:33]:
        rows.append(
            (code, datetime(2026, 1, 21, 9, 31), *[Decimal("10")] * 4, Decimal("1"), Decimal("-1"))
        )
    for code, minute in [("899002.BJ", 30), ("899002.BJ", 31), ("899050.BJ", 30)]:
        rows.append(
            (
                code,
                datetime(2026, 1, 21, 9, minute),
                *[Decimal("10")] * 4,
                Decimal("1"),
                Decimal("-1"),
            )
        )
    rows.append(
        (
            "000001.SZ",
            datetime(2026, 1, 21, 9, 30),
            *[Decimal("10")] * 4,
            Decimal("1"),
            Decimal("5"),
        )
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured: list[pa.Table] = []

    def stage(table: pa.Table, **kwargs: Any) -> SimpleNamespace:
        captured.append(table)
        return SimpleNamespace(content_digest="a" * 64)

    monkeypatch.setattr("quantagent.ingest.jobs.minprice.stage_partition", stage)
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            write_db=True,
        )
        == "inserted"
    )
    assert set(captured[0]["ts_code"].to_pylist()) == {"000001.SZ", "899002.BJ", "899050.BJ"}
    assert len(logs[0].excluded_codes) == 67
    assert len(logs[0].source_corrections) == 3
    assert all(row["amount_after"] == "0.0000" for row in logs[0].source_corrections)


@pytest.mark.parametrize(
    ("day", "code", "negative"),
    [
        (date(2026, 1, 22), "002485.SZ", "-28"),
        (date(2026, 3, 26), "920242.BJ", "-31"),
        (date(2026, 4, 16), "920855.BJ", "-37"),
        (date(2026, 6, 8), "920608.BJ", "-51"),
        (date(2026, 6, 22), "920855.BJ", "-7"),
        (date(2026, 7, 8), "920132.BJ", "-56"),
        (date(2026, 7, 24), "920112.BJ", "-12"),
        (date(2026, 9, 17), "920242.BJ", "-3"),
        (date(2026, 11, 11), "920608.BJ", "-19"),
    ],
)
def test_approved_negative_volume_corrected_after_daily_check(
    monkeypatch, tmp_path, day, code, negative
):
    rows = [
        (
            code,
            datetime.combine(day, datetime.min.time()).replace(hour=9, minute=30),
            *[Decimal("10")] * 4,
            Decimal("1"),
            Decimal("1000"),
        ),
        (
            code,
            datetime.combine(day, datetime.min.time()).replace(hour=15),
            *[Decimal("10")] * 4,
            Decimal("-1"),
            Decimal(negative),
        ),
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [SimpleNamespace(wind_code=code, amount=Decimal("1"))]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    kwargs = {
        "trade_date": day,
        "settings": settings,
        "paths": resolve_var_paths(settings, repo_root=tmp_path),
        "calendar": MagicMock(),
        "daily_prices": prices,
        "write_db": True,
    }
    assert ingest_day(MagicMock(), pg, **kwargs) == "inserted"
    result = captured[0].to_pylist()[1]
    assert result["vol"] == 0 and result["amount"] == 0
    assert logs[0].source_corrections[0]["vol_before"] == "-1.0000"
    assert logs[0].source_corrections[0]["amount_before"] == f"{Decimal(negative):.4f}"
    assert logs[0].input_digest != logs[0].output_digest
    prices.list_prices.return_value = [SimpleNamespace(wind_code=code, amount=Decimal("2"))]
    with pytest.raises(SourceFetchError, match="未通过成交额对比"):
        ingest_day(MagicMock(), pg, **kwargs)


@pytest.mark.parametrize(
    ("day", "code", "amount"),
    [
        (date(2026, 4, 30), "920608.BJ", "422"),
        (date(2026, 6, 2), "920112.BJ", "1037"),
        (date(2026, 6, 29), "920608.BJ", "11"),
        (date(2026, 7, 9), "920422.BJ", "337"),
        (date(2026, 7, 14), "920422.BJ", "11"),
        (date(2026, 7, 17), "920121.BJ", "2063"),
        (date(2026, 7, 28), "920370.BJ", "129"),
        (date(2026, 8, 4), "920395.BJ", "91"),
        (date(2026, 9, 10), "920177.BJ", "971"),
        (date(2026, 9, 28), "920055.BJ", "168"),
        (date(2026, 10, 14), "920020.BJ", "13"),
        (date(2026, 10, 19), "920242.BJ", "20"),
        (date(2026, 10, 22), "920751.BJ", "37"),
        (date(2026, 10, 29), "920871.BJ", "37"),
        (date(2026, 11, 18), "920121.BJ", "1775"),
    ],
)
def test_corrects_approved_positive_amount_and_negative_volume(
    monkeypatch, tmp_path, day, code, amount
):
    row = (
        code,
        datetime.combine(day, datetime.min.time()).replace(hour=15),
        *[Decimal("10")] * 4,
        Decimal("-1"),
        Decimal(amount),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([[row]]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            write_db=True,
        )
        == "inserted"
    )
    result = captured[0].to_pylist()[0]
    assert result["vol"] == 0 and result["amount"] == 0
    assert logs[0].source_corrections[0]["vol_before"] == "-1.0000"
    assert logs[0].source_corrections[0]["amount_before"] == f"{Decimal(amount):.4f}"
    assert logs[0].input_digest != logs[0].output_digest


def test_july_6_corrects_two_rows_with_distinct_amount_signs(monkeypatch, tmp_path):
    day = date(2026, 7, 6)
    rows = [
        (
            "920455.BJ",
            datetime(2026, 7, 6, 9, 30),
            *[Decimal("10")] * 4,
            Decimal("1"),
            Decimal("1000"),
        ),
        (
            "920455.BJ",
            datetime(2026, 7, 6, 15),
            *[Decimal("10")] * 4,
            Decimal("-1"),
            Decimal("-41"),
        ),
        (
            "920541.BJ",
            datetime(2026, 7, 6, 15),
            *[Decimal("10")] * 4,
            Decimal("-1"),
            Decimal("391"),
        ),
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [SimpleNamespace(wind_code="920455.BJ", amount=Decimal("1"))]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            daily_prices=prices,
            write_db=True,
        )
        == "inserted"
    )
    corrected = [r for r in captured[0].to_pylist() if r["trade_time"].hour == 15]
    assert len(corrected) == 2 and all(r["vol"] == 0 and r["amount"] == 0 for r in corrected)
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        ("920455.BJ", "-41.0000"),
        ("920541.BJ", "391.0000"),
    }


def test_august_17_corrects_two_positive_amount_rows(monkeypatch, tmp_path):
    # 同日两条正成交额的 -1 手记录，均按负责人裁定把成交量和成交额置 0。
    rows = [
        (code, datetime(2026, 8, 17, 15), *[Decimal("10")] * 4, Decimal("-1"), Decimal(amount))
        for code, amount in (("920121.BJ", "1462"), ("920679.BJ", "10"))
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=date(2026, 8, 17),
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            write_db=True,
        )
        == "inserted"
    )
    assert all(r["vol"] == 0 and r["amount"] == 0 for r in captured[0].to_pylist())
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        ("920121.BJ", "1462.0000"),
        ("920679.BJ", "10.0000"),
    }
    assert logs[0].input_digest != logs[0].output_digest


def test_august_20_corrects_two_rows_with_distinct_amount_signs(monkeypatch, tmp_path):
    # 同日两条 -1 手记录：正成交额直接置 0，负成交额仍须通过日成交额对比。
    day = date(2026, 8, 20)
    rows = [
        (code, datetime(2026, 8, 20, 9, 30), *[Decimal("10")] * 4, Decimal("1"), Decimal("1000"))
        for code in ("920146.BJ", "920395.BJ")
    ] + [
        (
            "920146.BJ",
            datetime(2026, 8, 20, 15),
            *[Decimal("10")] * 4,
            Decimal("-1"),
            Decimal("37"),
        ),
        (
            "920395.BJ",
            datetime(2026, 8, 20, 15),
            *[Decimal("10")] * 4,
            Decimal("-1"),
            Decimal("-42"),
        ),
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [SimpleNamespace(wind_code="920395.BJ", amount=Decimal("1"))]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    kwargs = {
        "trade_date": day,
        "settings": settings,
        "paths": resolve_var_paths(settings, repo_root=tmp_path),
        "calendar": MagicMock(),
        "daily_prices": prices,
        "write_db": True,
    }
    assert ingest_day(MagicMock(), pg, **kwargs) == "inserted"
    corrected = [r for r in captured[0].to_pylist() if r["trade_time"].hour == 15]
    assert len(corrected) == 2 and all(r["vol"] == 0 and r["amount"] == 0 for r in corrected)
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        ("920146.BJ", "37.0000"),
        ("920395.BJ", "-42.0000"),
    }
    assert all(r["vol_before"] == "-1.0000" for r in logs[0].source_corrections)
    prices.list_prices.return_value = [SimpleNamespace(wind_code="920395.BJ", amount=Decimal("2"))]
    with pytest.raises(SourceFetchError, match="未通过成交额对比"):
        ingest_day(MagicMock(), pg, **kwargs)


def test_august_24_corrects_three_rows_mixed_amount_signs(monkeypatch, tmp_path):
    # 首个三条 -1 手记录的交易日：正成交额直接置 0，两条负成交额分别过日行情对比。
    day = date(2026, 8, 24)
    fixes = (("920168.BJ", "378"), ("920275.BJ", "-62"), ("920679.BJ", "-37"))
    rows = [
        (code, datetime(2026, 8, 24, 9, 30), *[Decimal("10")] * 4, Decimal("1"), Decimal("1000"))
        for code, _ in fixes
    ] + [
        (code, datetime(2026, 8, 24, 15), *[Decimal("10")] * 4, Decimal("-1"), Decimal(amount))
        for code, amount in fixes
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code=code, amount=Decimal("1")) for code in ("920275.BJ", "920679.BJ")
    ]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    kwargs = {
        "trade_date": day,
        "settings": settings,
        "paths": resolve_var_paths(settings, repo_root=tmp_path),
        "calendar": MagicMock(),
        "daily_prices": prices,
        "write_db": True,
    }
    assert ingest_day(MagicMock(), pg, **kwargs) == "inserted"
    corrected = [r for r in captured[0].to_pylist() if r["trade_time"].hour == 15]
    assert len(corrected) == 3 and all(r["vol"] == 0 and r["amount"] == 0 for r in corrected)
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        (code, f"{Decimal(amount):.4f}") for code, amount in fixes
    }
    assert sorted(logs[0].excluded_codes) == []
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code="920275.BJ", amount=Decimal("1")),
        SimpleNamespace(wind_code="920679.BJ", amount=Decimal("2")),
    ]
    with pytest.raises(SourceFetchError, match="未通过成交额对比"):
        ingest_day(MagicMock(), pg, **kwargs)


def test_september_15_corrects_three_positive_amount_rows(monkeypatch, tmp_path):
    # 三条正成交额的 -1 手记录，均按负责人惯例指示把成交量和成交额置 0。
    day = date(2026, 9, 15)
    fixes = (("920121.BJ", "205"), ("920166.BJ", "2"), ("920168.BJ", "542"))
    rows = [
        (code, datetime(2026, 9, 15, 15), *[Decimal("10")] * 4, Decimal("-1"), Decimal(amount))
        for code, amount in fixes
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            write_db=True,
        )
        == "inserted"
    )
    assert all(r["vol"] == 0 and r["amount"] == 0 for r in captured[0].to_pylist())
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        (code, f"{Decimal(amount):.4f}") for code, amount in fixes
    }
    assert logs[0].excluded_codes == []
    assert logs[0].input_digest != logs[0].output_digest


def test_september_30_corrects_two_rows_and_keeps_plain_negative_amount(monkeypatch, tmp_path):
    # 两条 -1 手记录走裁定，同日另一条仅有负成交额（成交量 0）仍由既有日行情规则处理。
    day = date(2026, 9, 30)
    rows = [
        (code, datetime(2026, 9, 30, 9, 30), *[Decimal("10")] * 4, Decimal("1"), Decimal("1000"))
        for code in ("920163.BJ", "920541.BJ", "920395.BJ")
    ] + [
        (
            "920163.BJ",
            datetime(2026, 9, 30, 15),
            *[Decimal("10")] * 4,
            Decimal("-1"),
            Decimal("-3"),
        ),
        (
            "920541.BJ",
            datetime(2026, 9, 30, 15),
            *[Decimal("10")] * 4,
            Decimal("-1"),
            Decimal("-17"),
        ),
        (
            "920395.BJ",
            datetime(2026, 9, 30, 15),
            *[Decimal("10")] * 4,
            Decimal("0"),
            Decimal("-24"),
        ),
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code=code, amount=Decimal("1"))
        for code in ("920163.BJ", "920541.BJ", "920395.BJ")
    ]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    kwargs = {
        "trade_date": day,
        "settings": settings,
        "paths": resolve_var_paths(settings, repo_root=tmp_path),
        "calendar": MagicMock(),
        "daily_prices": prices,
        "write_db": True,
    }
    assert ingest_day(MagicMock(), pg, **kwargs) == "inserted"
    corrected = [r for r in captured[0].to_pylist() if r["trade_time"].hour == 15]
    assert len(corrected) == 3 and all(r["amount"] == 0 for r in corrected)
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        ("920163.BJ", "-3.0000"),
        ("920541.BJ", "-17.0000"),
        ("920395.BJ", "-24.0000"),
    }
    assert logs[0].excluded_codes == []
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code="920163.BJ", amount=Decimal("1")),
        SimpleNamespace(wind_code="920541.BJ", amount=Decimal("2")),
        SimpleNamespace(wind_code="920395.BJ", amount=Decimal("1")),
    ]
    with pytest.raises(SourceFetchError, match="未通过成交额对比"):
        ingest_day(MagicMock(), pg, **kwargs)


def test_october_8_corrects_three_negative_amount_rows(monkeypatch, tmp_path):
    # 三条 -1 手且成交额为负，逐条须通过日行情对比后才置 0 入库。
    day = date(2026, 10, 8)
    fixes = (("920033.BJ", "-29"), ("920541.BJ", "-7"), ("920781.BJ", "-17"))
    rows = [
        (code, datetime(2026, 10, 8, 9, 30), *[Decimal("10")] * 4, Decimal("1"), Decimal("1000"))
        for code, _ in fixes
    ] + [
        (code, datetime(2026, 10, 8, 15), *[Decimal("10")] * 4, Decimal("-1"), Decimal(amount))
        for code, amount in fixes
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code=code, amount=Decimal("1")) for code, _ in fixes
    ]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    kwargs = {
        "trade_date": day,
        "settings": settings,
        "paths": resolve_var_paths(settings, repo_root=tmp_path),
        "calendar": MagicMock(),
        "daily_prices": prices,
        "write_db": True,
    }
    assert ingest_day(MagicMock(), pg, **kwargs) == "inserted"
    corrected = [r for r in captured[0].to_pylist() if r["trade_time"].hour == 15]
    assert len(corrected) == 3 and all(r["vol"] == 0 and r["amount"] == 0 for r in corrected)
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        (code, f"{Decimal(amount):.4f}") for code, amount in fixes
    }
    assert logs[0].excluded_codes == []
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code="920033.BJ", amount=Decimal("1")),
        SimpleNamespace(wind_code="920541.BJ", amount=Decimal("1")),
        SimpleNamespace(wind_code="920781.BJ", amount=Decimal("2")),
    ]
    with pytest.raises(SourceFetchError, match="未通过成交额对比"):
        ingest_day(MagicMock(), pg, **kwargs)


def test_october_12_corrects_two_positive_amount_rows(monkeypatch, tmp_path):
    # 两条正成交额的 -1 手记录，均按负责人惯例指示把成交量和成交额置 0。
    day = date(2026, 10, 12)
    fixes = (("920166.BJ", "404"), ("920541.BJ", "619"))
    rows = [
        (code, datetime(2026, 10, 12, 15), *[Decimal("10")] * 4, Decimal("-1"), Decimal(amount))
        for code, amount in fixes
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            write_db=True,
        )
        == "inserted"
    )
    assert all(r["vol"] == 0 and r["amount"] == 0 for r in captured[0].to_pylist())
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        (code, f"{Decimal(amount):.4f}") for code, amount in fixes
    }
    assert logs[0].excluded_codes == []


def test_october_13_corrects_two_rows_and_keeps_plain_negative_amount(monkeypatch, tmp_path):
    # 两条 -1 手负成交额记录走裁定；同日成交量 0 的负成交额仍由既有日行情规则处理。
    day = date(2026, 10, 13)
    fixes = (("920069.BJ", "-44", "-1"), ("920080.BJ", "-41", "-1"), ("920541.BJ", "-54", "0"))
    rows = [
        (code, datetime(2026, 10, 13, 9, 30), *[Decimal("10")] * 4, Decimal("1"), Decimal("1000"))
        for code, _, _ in fixes
    ] + [
        (code, datetime(2026, 10, 13, 15), *[Decimal("10")] * 4, Decimal(vol), Decimal(amount))
        for code, amount, vol in fixes
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code=code, amount=Decimal("1")) for code, _, _ in fixes
    ]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    kwargs = {
        "trade_date": day,
        "settings": settings,
        "paths": resolve_var_paths(settings, repo_root=tmp_path),
        "calendar": MagicMock(),
        "daily_prices": prices,
        "write_db": True,
    }
    assert ingest_day(MagicMock(), pg, **kwargs) == "inserted"
    corrected = [r for r in captured[0].to_pylist() if r["trade_time"].hour == 15]
    assert len(corrected) == 3 and all(r["amount"] == 0 for r in corrected)
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        (code, f"{Decimal(amount):.4f}") for code, amount, _ in fixes
    }
    assert logs[0].excluded_codes == []
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code="920069.BJ", amount=Decimal("2")),
        SimpleNamespace(wind_code="920080.BJ", amount=Decimal("1")),
        SimpleNamespace(wind_code="920541.BJ", amount=Decimal("1")),
    ]
    with pytest.raises(SourceFetchError, match="未通过成交额对比"):
        ingest_day(MagicMock(), pg, **kwargs)


def test_october_21_corrects_two_positive_amount_rows(monkeypatch, tmp_path):
    # 两条正成交额的 -1 手记录，均按负责人惯例指示把成交量和成交额置 0。
    day = date(2026, 10, 21)
    fixes = (("920145.BJ", "18"), ("920957.BJ", "761"))
    rows = [
        (code, datetime(2026, 10, 21, 15), *[Decimal("10")] * 4, Decimal("-1"), Decimal(amount))
        for code, amount in fixes
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert (
        ingest_day(
            MagicMock(),
            pg,
            trade_date=day,
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            calendar=MagicMock(),
            write_db=True,
        )
        == "inserted"
    )
    assert all(r["vol"] == 0 and r["amount"] == 0 for r in captured[0].to_pylist())
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        (code, f"{Decimal(amount):.4f}") for code, amount in fixes
    }
    assert logs[0].excluded_codes == []


def test_october_27_corrects_three_negative_amount_rows(monkeypatch, tmp_path):
    # 三条 -1 手且成交额为负，逐条须通过日行情对比后才置 0 入库。
    day = date(2026, 10, 27)
    fixes = (("920027.BJ", "-53"), ("920455.BJ", "-56"), ("920675.BJ", "-31"))
    rows = [
        (code, datetime(2026, 10, 27, 9, 30), *[Decimal("10")] * 4, Decimal("1"), Decimal("1000"))
        for code, _ in fixes
    ] + [
        (code, datetime(2026, 10, 27, 15), *[Decimal("10")] * 4, Decimal("-1"), Decimal(amount))
        for code, amount in fixes
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code=code, amount=Decimal("1")) for code, _ in fixes
    ]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    kwargs = {
        "trade_date": day,
        "settings": settings,
        "paths": resolve_var_paths(settings, repo_root=tmp_path),
        "calendar": MagicMock(),
        "daily_prices": prices,
        "write_db": True,
    }
    assert ingest_day(MagicMock(), pg, **kwargs) == "inserted"
    corrected = [r for r in captured[0].to_pylist() if r["trade_time"].hour == 15]
    assert len(corrected) == 3 and all(r["vol"] == 0 and r["amount"] == 0 for r in corrected)
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        (code, f"{Decimal(amount):.4f}") for code, amount in fixes
    }
    assert logs[0].excluded_codes == []
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code="920027.BJ", amount=Decimal("1")),
        SimpleNamespace(wind_code="920455.BJ", amount=Decimal("2")),
        SimpleNamespace(wind_code="920675.BJ", amount=Decimal("1")),
    ]
    with pytest.raises(SourceFetchError, match="未通过成交额对比"):
        ingest_day(MagicMock(), pg, **kwargs)


def test_november_3_corrects_two_rows_mixed_amount_signs(monkeypatch, tmp_path):
    # 两条 -1 手记录：正成交额置 0，负成交额过日行情对比；成交量 0 的负额走既有规则。
    day = date(2026, 11, 3)
    fixes = (("920275.BJ", "-35", "-1"), ("920931.BJ", "263", "-1"), ("920030.BJ", "-55", "0"))
    rows = [
        (code, datetime(2026, 11, 3, 9, 30), *[Decimal("10")] * 4, Decimal("1"), Decimal("1000"))
        for code, _, _ in fixes
    ] + [
        (code, datetime(2026, 11, 3, 15), *[Decimal("10")] * 4, Decimal(vol), Decimal(amount))
        for code, amount, vol in fixes
    ]
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.read_day", lambda *a, **k: iter([rows]))
    captured = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.stage_partition",
        lambda table, **k: captured.append(table) or SimpleNamespace(content_digest="a" * 64),
    )
    monkeypatch.setattr("quantagent.ingest.jobs.minprice.register_partition", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(
        "quantagent.ingest.jobs.minprice.persist_run_log", lambda record, paths: logs.append(record)
    )
    prices = MagicMock()
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code=code, amount=Decimal("1")) for code, _, _ in fixes
    ]
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    pg = MagicMock()
    pg.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    kwargs = {
        "trade_date": day,
        "settings": settings,
        "paths": resolve_var_paths(settings, repo_root=tmp_path),
        "calendar": MagicMock(),
        "daily_prices": prices,
        "write_db": True,
    }
    assert ingest_day(MagicMock(), pg, **kwargs) == "inserted"
    corrected = [r for r in captured[0].to_pylist() if r["trade_time"].hour == 15]
    assert len(corrected) == 3 and all(r["amount"] == 0 for r in corrected)
    assert {(r["ts_code"], r["amount_before"]) for r in logs[0].source_corrections} == {
        (code, f"{Decimal(amount):.4f}") for code, amount, _ in fixes
    }
    assert logs[0].excluded_codes == []
    prices.list_prices.return_value = [
        SimpleNamespace(wind_code="920275.BJ", amount=Decimal("2")),
        SimpleNamespace(wind_code="920931.BJ", amount=Decimal("1")),
        SimpleNamespace(wind_code="920030.BJ", amount=Decimal("1")),
    ]
    with pytest.raises(SourceFetchError, match="未通过成交额对比"):
        ingest_day(MagicMock(), pg, **kwargs)

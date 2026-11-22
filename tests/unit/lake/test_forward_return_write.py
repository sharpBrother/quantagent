"""mart.forward_return 写入守卫、读取往返与物化编排。

每条拒绝都要证明：没有产生任何文件或目录。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
import pytest

from quantagent.adapters.lake.forward_return import LakeForwardReturnRepository
from quantagent.adapters.lake.trade_calendar import load_trade_calendar_visibility
from quantagent.adapters.memory.calendar import MemoryCalendarRepository
from quantagent.adapters.memory.prices import MemoryDailyPriceRepository
from quantagent.adapters.postgres.daily_prices import load_price_visibility
from quantagent.contracts.spec import VisibilityContract
from quantagent.domain.calendar import CalendarDay
from quantagent.domain.errors import InvalidQueryError
from quantagent.domain.forward_return import ForwardReturn
from quantagent.domain.prices.types import DailyPrice
from quantagent.lake.materialize import forward_return as materialize_module
from quantagent.lake.materialize.forward_return import (
    ForwardReturnWriteResult,
    materialize_forward_return,
    write_forward_returns,
)
from quantagent.lake.partitions import LakeLayoutError
from quantagent.platform.storage.paths import VarPaths

if TYPE_CHECKING:
    from pathlib import Path

    import pyarrow as pa


def _row(
    *,
    asset_id: str = "000001.SZ",
    event_dt: date = date(2024, 1, 2),
    start_dt: date = date(2024, 1, 3),
    end_dt: date = date(2024, 1, 9),
    horizon: str = "5d",
    value: float = 0.01,
    pit_grade: str = "A",
    knowledge_dt: date | None = None,
    return_leg: str = "open2open",
    benchmark_id: str = "none",
    return_kind: str = "total",
) -> ForwardReturn:
    return ForwardReturn(
        asset_id=asset_id,
        event_dt=event_dt,
        horizon=horizon,
        return_kind=return_kind,
        benchmark_id=benchmark_id,
        value=value,
        end_dt=end_dt,
        knowledge_dt=knowledge_dt if knowledge_dt is not None else end_dt,
        pit_grade=pit_grade,
        return_leg=return_leg,
        start_dt=start_dt,
    )


def _feb_row(asset_id: str) -> ForwardReturn:
    return _row(
        asset_id=asset_id,
        event_dt=date(2024, 2, 1),
        start_dt=date(2024, 2, 2),
        end_dt=date(2024, 2, 8),
    )


def _assert_nothing_written(dest: Path) -> None:
    assert not dest.exists(), f"拒绝后不应创建目录: {dest}"


def _price_contract() -> VisibilityContract:
    return VisibilityContract.model_validate(
        {
            "dataset": "mart.forward_return",
            "doc_ref": "docs/architecture/derived-datasets.md",
            "temporal_kind": "point_event",
            "event_field": "event_dt",
            "visibility": {
                "rule": "source_field",
                "field": "knowledge_dt",
                "grade": "A",
                "rationale": "读取往返测试用的可见性规则说明必须足够长，满足校验要求",
            },
            "pit_recoverable": True,
        }
    )


@pytest.mark.unit
def test_write_partitions_by_event_month_and_drops_partition_column(tmp_path: Path) -> None:
    dest = tmp_path / "mart" / "forward_return"
    result = write_forward_returns((_row(value=0.0123456789), _feb_row("600000.SH")), dest)
    assert result.row_count == 2
    assert (dest / "ym=202401").is_dir()
    assert (dest / "ym=202402").is_dir()
    schema = pq.read_schema(next((dest / "ym=202401").glob("*.parquet")))
    assert "ym" not in schema.names


@pytest.mark.unit
def test_refuses_empty_batch_without_creating_dir(tmp_path: Path) -> None:
    dest = tmp_path / "forward_return"
    with pytest.raises(LakeLayoutError, match="没有可写入"):
        write_forward_returns((), dest)
    _assert_nothing_written(dest)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (_row(pit_grade="Z"), "pit_grade"),
        (_row(pit_grade="a"), "pit_grade"),
        (_row(knowledge_dt=date(2024, 1, 8)), "knowledge_dt"),
        (_row(knowledge_dt=date(2024, 1, 10)), "knowledge_dt"),
        (_row(start_dt=date(2024, 1, 2)), "区间顺序"),
        (
            _row(start_dt=date(2024, 1, 9), end_dt=date(2024, 1, 9), knowledge_dt=date(2024, 1, 9)),
            "区间顺序",
        ),
        (_row(end_dt=date(2024, 1, 1), knowledge_dt=date(2024, 1, 1)), "区间顺序"),
        (_row(horizon="60d"), "horizon"),
        (_row(return_leg="close2close"), "收益腿"),
        (_row(return_kind="excess"), "收益腿"),
        (_row(benchmark_id="000300.SH"), "benchmark_id"),
        (_row(value=float("nan")), "非有限"),
        (_row(value=float("inf")), "非有限"),
    ],
)
def test_single_bad_row_rejects_whole_batch(
    tmp_path: Path, bad: ForwardReturn, message: str
) -> None:
    dest = tmp_path / "forward_return"
    good = _row(asset_id="600000.SH")
    with pytest.raises(LakeLayoutError, match=message):
        write_forward_returns((good, bad), dest)
    _assert_nothing_written(dest)


@pytest.mark.unit
def test_batch_duplicate_identity_refused(tmp_path: Path) -> None:
    dest = tmp_path / "forward_return"
    with pytest.raises(LakeLayoutError, match="重复身份"):
        write_forward_returns((_row(value=0.1), _row(value=0.2)), dest)
    _assert_nothing_written(dest)


@pytest.mark.unit
def test_existing_identity_refused_and_original_file_untouched(tmp_path: Path) -> None:
    dest = tmp_path / "forward_return"
    write_forward_returns((_row(value=0.1),), dest)
    before = sorted(p.name for p in dest.rglob("*.parquet"))
    with pytest.raises(LakeLayoutError, match="拒绝覆盖既有行"):
        write_forward_returns((_row(value=0.9),), dest)
    assert sorted(p.name for p in dest.rglob("*.parquet")) == before


@pytest.mark.unit
def test_refused_later_partition_leaves_earlier_partition_unwritten(tmp_path: Path) -> None:
    """批次跨一月和二月，只有二月与既有行冲突。一月也不能落盘。"""
    dest = tmp_path / "forward_return"
    write_forward_returns((_feb_row("600000.SH"),), dest)
    batch = (_row(asset_id="000001.SZ"), _feb_row("600000.SH"))
    with pytest.raises(LakeLayoutError, match="拒绝覆盖既有行"):
        write_forward_returns(batch, dest)
    assert not (dest / "ym=202401").exists()


@pytest.mark.unit
def test_readback_mismatch_removes_written_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "forward_return"
    real = materialize_module._content_digest
    calls = {"n": 0}

    def _wrong_on_readback(table: pa.Table) -> str:
        calls["n"] += 1
        return "0" * 64 if calls["n"] == 2 else real(table)

    monkeypatch.setattr(materialize_module, "_content_digest", _wrong_on_readback)
    with pytest.raises(LakeLayoutError, match="回读内容 digest"):
        write_forward_returns((_row(),), dest)
    assert not list(dest.rglob("*.parquet"))


@pytest.mark.unit
def test_lake_read_roundtrip_returns_same_rows(tmp_path: Path) -> None:
    dest = tmp_path / "forward_return"
    kept = _row(asset_id="000001.SZ", value=0.0123456789)
    other = _row(
        asset_id="600000.SH",
        value=-0.25,
        horizon="1d",
        start_dt=date(2024, 1, 3),
        end_dt=date(2024, 1, 4),
    )
    write_forward_returns((kept, other), dest)
    repo = LakeForwardReturnRepository(dest, contract=_price_contract())
    got = repo.scan_window(
        as_of=date(2024, 1, 31),
        horizon="5d",
        return_kind="total",
        benchmark_id="none",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
    )
    assert got == (kept,)


def _paths(tmp_path: Path) -> VarPaths:
    root = tmp_path / "var"
    return VarPaths(
        root=root,
        lake=root / "lake",
        logs=root / "logs",
        runs=root / "logs" / "runs",
        cache=root / "cache",
    )


def _calendar_rows() -> tuple[CalendarDay, ...]:
    rows: list[CalendarDay] = []
    day = date(2024, 1, 1)
    while day <= date(2024, 1, 31):
        rows.append(
            CalendarDay(
                cal_dt=day,
                exchange="SSE",
                is_open=day.weekday() < 5,
                prev_trade_dt=None,
            )
        )
        day = date.fromordinal(day.toordinal() + 1)
    return tuple(rows)


def _price(day: date, code: str, adj_open: Decimal) -> DailyPrice:
    return DailyPrice(
        trade_dt=day,
        wind_code=code,
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=Decimal("1"),
        amount=Decimal("1"),
        pct_change=None,
        adj_open=adj_open,
        trade_status_code=1,
    )


@pytest.mark.unit
def test_materialize_writes_rows_and_run_log_then_refuses_repeat(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    days = _calendar_rows()
    opens = [d.cal_dt for d in days if d.is_open]
    signal = date(2024, 1, 2)
    idx = opens.index(signal)
    # 只给到 T+2 的行情：1d 可以成熟，5d 及以上不成熟，因此只产一行。
    prices = [_price(opens[idx + k], "000001.SZ", Decimal(10 + k)) for k in range(3)]

    def _run() -> ForwardReturnWriteResult:
        return materialize_forward_return(
            paths=paths,
            calendar=MemoryCalendarRepository(days, contract=load_trade_calendar_visibility()),
            prices=MemoryDailyPriceRepository(prices, contract=load_price_visibility()),
            contract=load_price_visibility(),
            start=signal,
            end=signal,
            as_of=date(2024, 1, 31),
            wind_codes=("000001.SZ",),
        )

    result = _run()
    assert result.row_count == 1
    assert (paths.lake / "mart" / "forward_return").is_dir()
    success = [
        p
        for p in paths.runs.glob("*.json")
        if '"status": "success"' in p.read_text(encoding="utf-8")
    ]
    assert len(success) == 1

    with pytest.raises(LakeLayoutError, match="拒绝覆盖既有行"):
        _run()
    failure = [
        p
        for p in paths.runs.glob("*.json")
        if '"status": "failure"' in p.read_text(encoding="utf-8")
    ]
    assert len(failure) == 1


@pytest.mark.unit
def test_materialize_rejects_empty_wind_codes_without_writing_lake(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with pytest.raises(InvalidQueryError, match="wind_codes 为空"):
        materialize_forward_return(
            paths=paths,
            calendar=MemoryCalendarRepository(
                _calendar_rows(), contract=load_trade_calendar_visibility()
            ),
            prices=MemoryDailyPriceRepository((), contract=load_price_visibility()),
            contract=load_price_visibility(),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            as_of=date(2024, 1, 31),
            wind_codes=(),
        )
    assert not paths.lake.exists()

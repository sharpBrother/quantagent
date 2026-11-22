from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.domain.calendar.types import CalendarDay
from quantagent.ingest.writers.minprice_parquet import stage_partition
from quantagent.platform.config import Settings
from quantagent.platform.errors import WriteGateError
from quantagent.platform.storage.paths import resolve_var_paths


def sample():
    schema = pa.schema(
        [
            ("ts_code", pa.string()),
            ("trade_time", pa.timestamp("us")),
            *[
                (name, pa.decimal128(20, 4))
                for name in ("open", "high", "low", "close", "vol", "amount")
            ],
        ]
    )
    return pa.Table.from_pylist(
        [
            {
                "ts_code": "000001.SZ",
                "trade_time": datetime(2026, 11, 20, 9, 30),
                "open": Decimal("12"),
                "high": Decimal("13"),
                "low": Decimal("11"),
                "close": Decimal("12"),
                "vol": Decimal("10"),
                "amount": Decimal("1200"),
            }
        ],
        schema=schema,
    )


def test_staging_needs_both_gates_and_refuses_overwrite(tmp_path):
    day = date(2026, 11, 20)
    calendar = SimpleNamespace(list_days=lambda **kw: (CalendarDay(day, "SSE", True, None),))
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    with pytest.raises(WriteGateError):
        stage_partition(sample(), trade_date=day, calendar=calendar, settings=settings, paths=paths)
    result = stage_partition(
        sample(), trade_date=day, calendar=calendar, settings=settings, paths=paths, write_db=True
    )
    assert result.row_count == 1
    assert (paths.lake / "src/minprice/ashare_minute_bar" / result.file_name).exists()
    with pytest.raises(FileExistsError):
        stage_partition(
            sample(),
            trade_date=day,
            calendar=calendar,
            settings=settings,
            paths=paths,
            write_db=True,
        )


def test_staging_persists_excluded_codes(tmp_path):
    day = date(2026, 11, 20)
    calendar = SimpleNamespace(list_days=lambda **kw: (CalendarDay(day, "SSE", True, None),))
    settings = Settings(var_root=tmp_path, allow_db_write=True)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    result = stage_partition(
        sample(),
        trade_date=day,
        calendar=calendar,
        settings=settings,
        paths=paths,
        write_db=True,
        excluded_codes=["000002.SZ"],
    )
    file = paths.lake / "src/minprice/ashare_minute_bar" / result.file_name
    assert pq.ParquetFile(file).metadata.metadata[b"quantagent.excluded_codes"] == b'["000002.SZ"]'

"""历史占位日期和原始值在迁移时不得伪装成源发布时间。"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quantagent.ingest.errors import IngestError
from quantagent.ingest.jobs import jin10_ism_legacy
from quantagent.ingest.jobs.jin10_ism_legacy import ingest_jin10_ism_legacy, read_legacy_snapshot
from quantagent.platform.config import Settings
from quantagent.platform.storage import resolve_var_paths


def _snapshot(path: Path) -> None:
    rows = [
        {
            "publish_date": f"{year:04}-{month:02}-01",
            "actual_value": "50.1",
            "forecast_value": None,
            "previous_value": "49.9",
        }
        for year in range(1970, 2008)
        for month in range(1, 13)
    ]
    path.write_text(
        json.dumps(
            {
                "source": "wx2.dbo.macro_jin10_usa_ism_pmi",
                "row_count": len(rows),
                "records": rows,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.unit
def test_legacy_rows_preserve_placeholder_and_leave_period_unknown(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    _snapshot(path)
    rows = read_legacy_snapshot(path)
    assert len(rows) == 456
    assert rows[0]["publish_date"] == date(1970, 1, 1)
    assert rows[0]["period_end"] is None
    assert rows[0]["published_at"] is None
    assert rows[0]["source"] == "jin10.wx2.legacy_unknown_release"
    september = next(row for row in rows if row["publish_date"] == date(2007, 9, 4))
    assert september["period_end"] == date(2007, 8, 31)
    assert september["actual_value"] == Decimal("50.1")
    assert september["previous_value"] == Decimal("49.9")
    assert str(september["source"]).startswith(
        "jin10.wx2.legacy_unknown_release;publish_date_verified=https://fraser.stlouisfed.org/"
    )


@pytest.mark.unit
def test_legacy_snapshot_rejects_missing_month(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    _snapshot(path)
    snapshot = json.loads(path.read_text())
    snapshot["records"].pop()
    snapshot["row_count"] -= 1
    path.write_text(json.dumps(snapshot))
    with pytest.raises(IngestError, match="缺失或重复"):
        read_legacy_snapshot(path)


@pytest.mark.unit
def test_replacement_requires_known_exact_key_and_dry_runs(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    _snapshot(path)
    settings = Settings(_env_file=None, var_root=tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    result = ingest_jin10_ism_legacy(
        settings=settings, paths=paths, snapshot=path, replace_original_date=date(2007, 3, 1)
    )
    assert result.row_count == 1
    assert result.dml_count == 0
    changed_key = ingest_jin10_ism_legacy(
        settings=settings, paths=paths, snapshot=path, replace_original_date=date(2007, 9, 1)
    )
    assert changed_key.row_count == 1
    with pytest.raises(IngestError, match="替换须指定"):
        ingest_jin10_ism_legacy(
            settings=settings, paths=paths, snapshot=path, replace_original_date=date(2006, 9, 1)
        )


@pytest.mark.unit
def test_recent_segment_preserves_source_values_and_corrects_verified_date(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    rows = [
        {
            "publish_date": f"{year:04}-{month:02}-01",
            "actual_value": "50.1",
            "forecast_value": "50.0",
            "previous_value": "49.9",
            "period_end": None,
        }
        for year in range(2008, 2026)
        for month in range(1, 13)
        if year < 2025 or month <= 9
    ]
    rows.extend(
        [
            {
                "publish_date": "2022-01-03",
                "actual_value": None,
                "forecast_value": "50.0",
                "previous_value": "49.9",
                "period_end": None,
            },
            {
                "publish_date": "2025-01-03",
                "actual_value": None,
                "forecast_value": None,
                "previous_value": None,
                "period_end": None,
            },
        ]
    )
    path.write_text(
        json.dumps(
            {"source": "wx2.dbo.macro_jin10_usa_ism_pmi", "row_count": len(rows), "records": rows}
        )
    )
    result = read_legacy_snapshot(path, segment="2008-2025")
    assert len(result) == 215
    january = next(row for row in result if row["publish_date"] == date(2008, 1, 2))
    assert january["actual_value"] == Decimal("50.1")
    assert january["forecast_value"] == Decimal("50.0")
    assert january["period_end"] == date(2007, 12, 31)


@pytest.mark.unit
def test_replacement_failure_rolls_back_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "snapshot.json"
    _snapshot(path)
    events: list[str] = []

    class Connection:
        def close(self) -> None:
            events.append("close")

    class Store:
        def __init__(self, conn: object) -> None:
            pass

        def existing_values(
            self, spec: object, keys: object, columns: object
        ) -> dict[object, object]:
            return {(129, date(2007, 3, 1), 0): ("jin10.wx2.legacy_unknown_release",)}

        def delete_keys(self, spec: object, keys: object) -> None:
            events.append("delete")

        def existing_keys(self, spec: object, keys: object) -> set[object]:
            return set()

        def rollback(self) -> None:
            events.append("rollback")

    def fail_write(**kwargs: object) -> None:
        raise IngestError("模拟插入失败")

    monkeypatch.setattr(jin10_ism_legacy, "connect", lambda *args: Connection())
    monkeypatch.setattr(jin10_ism_legacy, "PostgresSrcStore", Store)
    monkeypatch.setattr(jin10_ism_legacy, "write_src_snapshot", fail_write)
    settings = Settings(_env_file=None, var_root=tmp_path, allow_db_write=True)
    with pytest.raises(IngestError, match="模拟插入失败"):
        ingest_jin10_ism_legacy(
            settings=settings,
            paths=resolve_var_paths(settings, repo_root=tmp_path),
            snapshot=path,
            write_db=True,
            replace_original_date=date(2007, 3, 1),
        )
    assert events == ["delete", "rollback", "close"]

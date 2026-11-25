"""日更水位线：只看 PIT 截止列可见的行；身份不符或 lake 为空时返回 None。写入只发生在 tmp_path。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantagent.adapters.lake.feature_value import LakeFeatureRepository
from quantagent.adapters.lake.forward_return import LakeForwardReturnRepository
from quantagent.domain.errors import FeatureLookupError

if TYPE_CHECKING:
    from pathlib import Path


def _write(dest: Path, rows: list[dict[str, object]]) -> None:
    part_dir = dest / "asset_class=stock" / "ym=202601"
    part_dir.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            key: pa.array(
                [row[key] for row in rows],
                type=pa.date32() if key in {"event_dt", "knowledge_dt"} else pa.string(),
            )
            for key in rows[0]
        }
    )
    pq.write_table(table, part_dir / "part-00000.parquet")


def _feature_rows() -> list[dict[str, object]]:
    return [
        {
            "event_dt": date(2026, 1, 5),
            "knowledge_dt": date(2026, 1, 5),
            "feature_id": "f1",
            "definition_version": "v1",
            "param_hash": "p1",
        },
        {
            # 事件日早，但可见日晚于 as_of：不能算作已写入。
            "event_dt": date(2026, 1, 9),
            "knowledge_dt": date(2026, 1, 12),
            "feature_id": "f1",
            "definition_version": "v1",
            "param_hash": "p1",
        },
        {
            "event_dt": date(2026, 1, 15),
            "knowledge_dt": date(2026, 1, 15),
            "feature_id": "other",
            "definition_version": "v1",
            "param_hash": "p1",
        },
    ]


@pytest.mark.unit
def test_feature_watermark_ignores_rows_not_visible_at_as_of(tmp_path: Path) -> None:
    _write(tmp_path, _feature_rows())
    repo = LakeFeatureRepository(tmp_path)
    kwargs = {"feature_id": "f1", "definition_version": "v1", "param_hash": "p1"}
    assert repo.latest_event_dt(as_of=date(2026, 1, 10), **kwargs) == date(2026, 1, 5)
    assert repo.latest_event_dt(as_of=date(2026, 1, 12), **kwargs) == date(2026, 1, 9)


@pytest.mark.unit
def test_feature_watermark_is_per_identity(tmp_path: Path) -> None:
    _write(tmp_path, _feature_rows())
    repo = LakeFeatureRepository(tmp_path)
    assert (
        repo.latest_event_dt(
            as_of=date(2026, 1, 20),
            feature_id="f1",
            definition_version="v2",
            param_hash="p1",
        )
        is None
    )


@pytest.mark.unit
def test_empty_or_missing_lake_gives_none_not_an_error(tmp_path: Path) -> None:
    missing = LakeFeatureRepository(tmp_path / "nowhere")
    assert (
        missing.latest_event_dt(
            as_of=date(2026, 1, 10), feature_id="f1", definition_version="v1", param_hash="p1"
        )
        is None
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    assert (
        LakeFeatureRepository(empty).latest_event_dt(
            as_of=date(2026, 1, 10), feature_id="f1", definition_version="v1", param_hash="p1"
        )
        is None
    )


@pytest.mark.unit
def test_blank_identity_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _feature_rows())
    with pytest.raises(FeatureLookupError):
        LakeFeatureRepository(tmp_path).latest_event_dt(
            as_of=date(2026, 1, 10), feature_id=" ", definition_version="v1", param_hash="p1"
        )


def _forward_rows() -> list[dict[str, object]]:
    base = {"return_kind": "total", "benchmark_id": "none", "return_leg": "open2open"}
    return [
        {
            **base,
            "event_dt": date(2026, 1, 5),
            "knowledge_dt": date(2026, 1, 8),
            "horizon": "1d",
        },
        {
            # 终点 2026-01-20 尚未到期：knowledge_dt 晚于 as_of。
            **base,
            "event_dt": date(2026, 1, 9),
            "knowledge_dt": date(2026, 1, 20),
            "horizon": "1d",
        },
        {
            **base,
            "event_dt": date(2026, 1, 9),
            "knowledge_dt": date(2026, 1, 9),
            "horizon": "5d",
        },
    ]


@pytest.mark.unit
def test_forward_return_watermark_uses_knowledge_dt_and_horizon(tmp_path: Path) -> None:
    _write(tmp_path, _forward_rows())
    repo = LakeForwardReturnRepository(tmp_path)
    assert repo.latest_event_dt(as_of=date(2026, 1, 10), horizon="1d") == date(2026, 1, 5)
    assert repo.latest_event_dt(as_of=date(2026, 1, 20), horizon="1d") == date(2026, 1, 9)
    assert repo.latest_event_dt(as_of=date(2026, 1, 10), horizon="5d") == date(2026, 1, 9)
    assert repo.latest_event_dt(as_of=date(2026, 1, 10), horizon="10d") is None

"""因子长表物理布局 benchmark。

入口是 ``quantagent lake benchmark-layout``，不是 ``scripts/``。合成数据只
用来比较相对布局；绝对时延随真实 200 因子 × 全 A 会变，需要按同一套查询
重跑。
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pyarrow as pa

from quantagent.adapters.lake import (
    FEATURE_VALUE_VIEW,
    build_training_matrix,
    scan_feature_cross_section,
    scan_feature_window,
)
from quantagent.lake.partitions.layout import FeatureValueLayout
from quantagent.lake.partitions.write import write_feature_value_parquet
from quantagent.platform.duck import duck_session, register_parquet
from quantagent.platform.identity import digest_json

if TYPE_CHECKING:
    from pathlib import Path

ScaleName = Literal["tiny", "paper"]

_SORT_FEAT = ("feature_id", "asset_id", "event_dt")
_SORT_EVENT = ("event_dt", "asset_id", "feature_id")
_SORT_EVENT_KEY = (
    "event_dt",
    "asset_id",
    "feature_id",
    "definition_version",
    "param_hash",
)


@dataclass(frozen=True)
class BenchScale:
    name: ScaleName
    n_assets: int
    n_features: int
    n_dates: int
    n_universe: int
    n_matrix_features: int
    n_matrix_dates: int
    start: date = date(2018, 1, 2)


SCALES: dict[ScaleName, BenchScale] = {
    "tiny": BenchScale(
        name="tiny",
        n_assets=12,
        n_features=6,
        n_dates=8,
        n_universe=6,
        n_matrix_features=4,
        n_matrix_dates=6,
    ),
    "paper": BenchScale(
        name="paper",
        n_assets=800,
        n_features=40,
        n_dates=360,
        n_universe=200,
        n_matrix_features=20,
        n_matrix_dates=180,
    ),
}

CANDIDATE_LAYOUTS: tuple[FeatureValueLayout, ...] = (
    FeatureValueLayout("unpart_sort_feat", (), _SORT_FEAT, "zstd"),
    FeatureValueLayout("unpart_sort_event", (), _SORT_EVENT, "zstd"),
    FeatureValueLayout("ym_sort_feat", ("ym",), _SORT_FEAT, "zstd"),
    FeatureValueLayout("ym_sort_event", ("ym",), _SORT_EVENT, "zstd"),
    FeatureValueLayout("event_dt_sort_feat", ("event_dt",), ("feature_id", "asset_id"), "zstd"),
    FeatureValueLayout("year_sort_event", ("year",), _SORT_EVENT, "zstd"),
    FeatureValueLayout(
        "asset_class_ym_sort_event_zstd",
        ("asset_class", "ym"),
        _SORT_EVENT_KEY,
        "zstd",
    ),
    FeatureValueLayout("ym_sort_event_snappy", ("ym",), _SORT_EVENT, "snappy"),
)


@dataclass
class QueryStat:
    name: str
    n: int
    p50_ms: float
    p95_ms: float
    row_count: int


@dataclass
class LayoutReport:
    name: str
    partition_keys: tuple[str, ...]
    sort_keys: tuple[str, ...]
    compression: str
    n_files: int
    nbytes: int
    write_ms: float
    append_day_ms: float
    queries: list[QueryStat] = field(default_factory=list)


def run_layout_benchmark(
    *,
    root: Path,
    scale: ScaleName = "tiny",
    repeats: int = 5,
    rebuild: bool = False,
    memory_limit: str | None = None,
    threads: int | None = None,
) -> dict[str, Any]:
    spec = SCALES[scale]
    if repeats < 1:
        msg = "repeats 必须 >= 1"
        raise ValueError(msg)
    duck_mem = (
        memory_limit if memory_limit is not None else ("4GB" if spec.name == "paper" else "2GB")
    )
    table = build_synthetic_feature_value(spec)
    extra = _slice_day(spec, extra=True)
    reports: list[LayoutReport] = []
    for layout in CANDIDATE_LAYOUTS:
        dest = root / layout.name
        mode: Literal["error", "overwrite"] = "overwrite" if rebuild else "error"
        t0 = time.perf_counter()
        written = write_feature_value_parquet(table, dest, layout, mode=mode)
        write_ms = (time.perf_counter() - t0) * 1000.0
        queries = _time_queries(
            dest,
            spec,
            repeats=repeats,
            memory_limit=duck_mem,
            threads=threads,
        )
        t1 = time.perf_counter()
        write_feature_value_parquet(extra, dest, layout, mode="append")
        append_ms = (time.perf_counter() - t1) * 1000.0
        reports.append(
            LayoutReport(
                name=layout.name,
                partition_keys=layout.partition_keys,
                sort_keys=layout.sort_keys,
                compression=layout.compression,
                n_files=written["n_files"],
                nbytes=written["nbytes"],
                write_ms=write_ms,
                append_day_ms=append_ms,
                queries=queries,
            )
        )
    payload = {
        "scale": spec.name,
        "n_assets": spec.n_assets,
        "n_features": spec.n_features,
        "n_dates": spec.n_dates,
        "n_rows": table.num_rows,
        "repeats": repeats,
        "layouts": [_layout_as_dict(item) for item in reports],
    }
    payload["digest"] = digest_json(
        {key: value for key, value in payload.items() if key != "digest"}
    )
    return payload


def build_synthetic_feature_value(spec: BenchScale) -> pa.Table:
    """笛卡尔积合成长表。缺失不落行；约 5% 行 knowledge_dt 更晚，供 PIT 单测以外的可见性差异。"""
    n_assets = spec.n_assets
    n_features = spec.n_features
    n_dates = spec.n_dates
    n = n_dates * n_assets * n_features
    event_i = np.repeat(np.arange(n_dates, dtype=np.int32), n_assets * n_features)
    asset_i = np.tile(np.repeat(np.arange(n_assets, dtype=np.int32), n_features), n_dates)
    feat_i = np.tile(np.arange(n_features, dtype=np.int32), n_dates * n_assets)
    event_np = np.datetime64(spec.start, "D") + event_i.astype("timedelta64[D]")
    delay = np.ones(n, dtype=np.int32)
    delay[::20] = 7
    knowledge_np = np.datetime64(spec.start, "D") + (event_i + delay).astype("timedelta64[D]")
    event_dt = pa.array(event_np).cast(pa.date32())
    knowledge_dt = pa.array(knowledge_np).cast(pa.date32())
    asset_labels = [f"A{i:04d}" for i in range(n_assets)]
    feature_labels = [f"f{i:03d}" for i in range(n_features)]
    class_labels = ["etf" if i % 10 == 0 else "stock" for i in range(n_assets)]
    value = np.sin(asset_i * 0.07 + feat_i * 0.13 + event_i * 0.01).astype(np.float64)
    computed_at = pa.scalar(datetime(2024, 6, 1), type=pa.timestamp("us"))
    return pa.table(
        {
            "event_dt": event_dt,
            "asset_id": pa.DictionaryArray.from_arrays(asset_i, pa.array(asset_labels)),
            "asset_class": pa.DictionaryArray.from_arrays(asset_i, pa.array(class_labels)),
            "feature_id": pa.DictionaryArray.from_arrays(feat_i, pa.array(feature_labels)),
            "definition_version": pa.DictionaryArray.from_arrays(
                np.zeros(n, dtype=np.int32),
                pa.array(["v1"]),
            ),
            "param_hash": pa.DictionaryArray.from_arrays(
                np.zeros(n, dtype=np.int32),
                pa.array(["p0"]),
            ),
            "value": value,
            "knowledge_dt": knowledge_dt,
            "pit_grade": pa.DictionaryArray.from_arrays(
                np.zeros(n, dtype=np.int32),
                pa.array(["A"]),
            ),
            "computed_at": pa.repeat(computed_at, n),
            "run_id": pa.DictionaryArray.from_arrays(
                np.zeros(n, dtype=np.int32),
                pa.array(["bench"]),
            ),
        }
    )


def _slice_day(spec: BenchScale, *, extra: bool) -> pa.Table:
    day_spec = BenchScale(
        name=spec.name,
        n_assets=spec.n_assets,
        n_features=spec.n_features,
        n_dates=1,
        n_universe=spec.n_universe,
        n_matrix_features=spec.n_matrix_features,
        n_matrix_dates=1,
        start=spec.start + timedelta(days=spec.n_dates if extra else 0),
    )
    return build_synthetic_feature_value(day_spec)


def _time_queries(
    dest: Path,
    spec: BenchScale,
    *,
    repeats: int,
    memory_limit: str | None,
    threads: int | None,
) -> list[QueryStat]:
    last_event = spec.start + timedelta(days=spec.n_dates - 1)
    as_of = last_event + timedelta(days=30)
    feature_id = "f000"
    cross_dt = spec.start + timedelta(days=spec.n_dates // 2)
    matrix_start = last_event - timedelta(days=spec.n_matrix_dates - 1)
    feature_ids = [f"f{i:03d}" for i in range(spec.n_matrix_features)]
    asset_ids = [f"A{i:04d}" for i in range(spec.n_universe)]
    with duck_session(memory_limit=memory_limit, threads=threads) as conn:
        register_parquet(conn, FEATURE_VALUE_VIEW, dest)

        def _window() -> pa.Table:
            return scan_feature_window(
                conn,
                as_of=as_of,
                feature_id=feature_id,
                definition_version="v1",
                param_hash="p0",
                start=spec.start,
                end=last_event,
            )

        def _cross() -> pa.Table:
            return scan_feature_cross_section(conn, as_of=as_of, event_dt=cross_dt)

        def _matrix() -> pa.Table:
            return build_training_matrix(
                conn,
                as_of=as_of,
                start=matrix_start,
                end=last_event,
                feature_ids=feature_ids,
                asset_ids=asset_ids,
            )

        return [
            _measure("single_factor_window", _window, repeats),
            _measure("full_factor_cross_section", _cross, repeats),
            _measure("training_matrix", _matrix, repeats),
        ]


def _measure(name: str, fn: Any, repeats: int) -> QueryStat:
    fn()
    samples: list[float] = []
    rows = 0
    for _ in range(repeats):
        t0 = time.perf_counter()
        table = fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
        rows = table.num_rows
    return QueryStat(
        name=name,
        n=repeats,
        p50_ms=_percentile(samples, 0.50),
        p95_ms=_percentile(samples, 0.95),
        row_count=rows,
    )


def _percentile(samples: list[float], q: float) -> float:
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _layout_as_dict(report: LayoutReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["partition_keys"] = list(report.partition_keys)
    payload["sort_keys"] = list(report.sort_keys)
    return payload

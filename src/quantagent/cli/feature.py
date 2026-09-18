"""``quantagent feature``：研究读取因子长表。必须带 --as-of。"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated

import typer

from quantagent.adapters.lake.feature_metric import LakeFeatureMetricRepository
from quantagent.adapters.lake.feature_value import (
    LakeFeatureRepository,
    load_feature_value_visibility,
)
from quantagent.adapters.lake.visibility import load_dataset_visibility
from quantagent.domain.errors import DomainError
from quantagent.domain.feature_value import FeatureKey
from quantagent.platform.config import get_settings
from quantagent.platform.errors import ConfigError, DuckSessionError
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

feature_app = typer.Typer(help="因子长表与评价指标研究读取。必须传 --as-of。", no_args_is_help=True)


@feature_app.command("window")
def feature_window(
    *,
    feature_id: Annotated[str, typer.Option("--feature-id")],
    definition_version: Annotated[str, typer.Option("--definition-version")],
    param_hash: Annotated[str, typer.Option("--param-hash")],
    start: Annotated[str, typer.Option("--start", help="窗口起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="窗口终点 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="可见日 YYYY-MM-DD，必填")],
) -> None:
    repo = _repo()
    start_dt = _parse_ymd(start, "--start")
    end_dt = _parse_ymd(end, "--end")
    as_of_dt = _parse_ymd(as_of, "--as-of")
    try:
        rows = repo.scan_window(
            as_of=as_of_dt,
            feature_id=feature_id,
            definition_version=definition_version,
            param_hash=param_hash,
            start=start_dt,
            end=end_dt,
        )
    except (DomainError, ConfigError, DuckSessionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"n={len(rows)} as_of={as_of_dt.isoformat()} {_pit_tag()}")
    for row in rows:
        typer.echo(
            f"{row.asset_id} {row.event_dt.isoformat()} {row.value} {row.knowledge_dt.isoformat()}"
        )


@feature_app.command("cross-section")
def feature_cross_section(
    event_dt: Annotated[str, typer.Option("--event-dt", help="截面日 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="可见日 YYYY-MM-DD，必填")],
) -> None:
    repo = _repo()
    event = _parse_ymd(event_dt, "--event-dt")
    as_of_dt = _parse_ymd(as_of, "--as-of")
    try:
        rows = repo.scan_cross_section(as_of=as_of_dt, event_dt=event)
    except (DomainError, ConfigError, DuckSessionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"n={len(rows)} event_dt={event.isoformat()} as_of={as_of_dt.isoformat()} {_pit_tag()}"
    )


@feature_app.command("matrix")
def feature_matrix(
    start: Annotated[str, typer.Option("--start", help="窗口起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="窗口终点 YYYY-MM-DD")],
    feature_keys: Annotated[
        str,
        typer.Option(
            "--feature-keys", help="JSON 数组，每项包含 feature_id、definition_version、param_hash"
        ),
    ],
    asset_ids: Annotated[str, typer.Option("--asset-ids", help="逗号分隔的资产 id")],
    as_of: Annotated[str, typer.Option("--as-of", help="可见日 YYYY-MM-DD，必填")],
) -> None:
    repo = _repo()
    start_dt = _parse_ymd(start, "--start")
    end_dt = _parse_ymd(end, "--end")
    as_of_dt = _parse_ymd(as_of, "--as-of")
    try:
        rows = repo.build_training_matrix(
            as_of=as_of_dt,
            start=start_dt,
            end=end_dt,
            feature_keys=_parse_feature_keys(feature_keys),
            asset_ids=_csv_ids(asset_ids, "--asset-ids"),
        )
    except (DomainError, ConfigError, DuckSessionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"n={len(rows)} as_of={as_of_dt.isoformat()} {_pit_tag()}")


@feature_app.command("metric")
def feature_metric(
    *,
    feature_id: Annotated[str, typer.Option("--feature-id")],
    definition_version: Annotated[str, typer.Option("--definition-version")],
    param_hash: Annotated[str, typer.Option("--param-hash")],
    universe_id: Annotated[str, typer.Option("--universe-id")],
    horizon: Annotated[str, typer.Option("--horizon")],
    metric_id: Annotated[str, typer.Option("--metric-id")],
    window: Annotated[str, typer.Option("--window")],
    benchmark_id: Annotated[str, typer.Option("--benchmark-id")],
    start: Annotated[str, typer.Option("--start", help="窗口起点 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="窗口终点 YYYY-MM-DD")],
    as_of: Annotated[str, typer.Option("--as-of", help="可见日 YYYY-MM-DD，必填")],
) -> None:
    repo = _metric_repo()
    start_dt = _parse_ymd(start, "--start")
    end_dt = _parse_ymd(end, "--end")
    as_of_dt = _parse_ymd(as_of, "--as-of")
    try:
        rows = repo.scan_window(
            as_of=as_of_dt,
            feature_id=feature_id,
            definition_version=definition_version,
            param_hash=param_hash,
            universe_id=universe_id,
            horizon=horizon,
            metric_id=metric_id,
            window=window,
            benchmark_id=benchmark_id,
            start=start_dt,
            end=end_dt,
        )
    except (DomainError, ConfigError, DuckSessionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    vis = load_dataset_visibility("feature.metric").visibility
    typer.echo(f"n={len(rows)} as_of={as_of_dt.isoformat()} pit={vis.rule}/{vis.grade}")
    for row in rows:
        typer.echo(f"{row.event_dt.isoformat()} {row.value} {row.knowledge_dt.isoformat()}")


def _repo() -> LakeFeatureRepository:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    return LakeFeatureRepository(paths.lake / "feature" / "value")


def _metric_repo() -> LakeFeatureMetricRepository:
    settings = get_settings()
    paths = resolve_var_paths(settings, repo_root=detect_repo_root())
    return LakeFeatureMetricRepository(paths.lake / "feature" / "metric")


def _pit_tag() -> str:
    vis = load_feature_value_visibility().visibility
    return f"pit={vis.rule}/{vis.grade}"


def _csv_ids(raw: str, flag: str) -> tuple[str, ...]:
    items = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not items:
        raise typer.BadParameter(f"{flag} 不能为空", param_hint=flag)
    return items


def _parse_ymd(raw: str, flag: str) -> date:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(f"{flag} 必须是 YYYY-MM-DD", param_hint=flag) from exc


def _parse_feature_keys(raw: str) -> tuple[FeatureKey, ...]:
    try:
        items = json.loads(raw)
        fields = {"feature_id", "definition_version", "param_hash"}
        if not isinstance(items, list) or not items:
            raise ValueError("必须是非空数组")
        keys = []
        for item in items:
            if (
                not isinstance(item, dict)
                or set(item) != fields
                or not all(isinstance(v, str) for v in item.values())
            ):
                raise ValueError("每项必须且只能包含三个字符串身份字段")
            keys.append(
                FeatureKey(item["feature_id"], item["definition_version"], item["param_hash"])
            )
        return tuple(keys)
    except (ValueError, TypeError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--feature-keys") from exc

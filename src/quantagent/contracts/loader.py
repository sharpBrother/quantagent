"""从包内 YAML 加载契约。读文件不是业务 IO：契约必须静态可读，CI 无库也能跑。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from quantagent.contracts.errors import ContractError
from quantagent.contracts.spec import DatasetSchemaSpec, VisibilityContract

_SCHEMA_LAYERS = ("pg", "ops", "lake")


@dataclass(frozen=True)
class ContractBundle:
    schemas: dict[str, DatasetSchemaSpec]
    visibilities: dict[str, VisibilityContract]
    schema_paths: dict[str, Path]
    visibility_paths: dict[str, Path]


def package_root() -> Path:
    with as_file(files("quantagent.contracts")) as path:
        return Path(path)


def default_schema_dir(layer: str) -> Path:
    return package_root() / "schemas" / layer


def default_visibility_dir() -> Path:
    return package_root() / "visibility"


def load_bundle(
    *,
    schema_dirs: dict[str, Path] | None = None,
    visibility_dir: Path | None = None,
) -> ContractBundle:
    dirs = schema_dirs or {layer: default_schema_dir(layer) for layer in _SCHEMA_LAYERS}
    vis_dir = visibility_dir or default_visibility_dir()
    schemas: dict[str, DatasetSchemaSpec] = {}
    schema_paths: dict[str, Path] = {}
    for layer, directory in dirs.items():
        for path in _yaml_files(directory):
            schema_spec = _parse_schema(path, expected_layer=layer)
            _reject_duplicate(schemas, schema_spec.dataset, path, kind="schema")
            _assert_filename_matches_dataset(path, schema_spec.dataset)
            schemas[schema_spec.dataset] = schema_spec
            schema_paths[schema_spec.dataset] = path
    visibilities: dict[str, VisibilityContract] = {}
    visibility_paths: dict[str, Path] = {}
    for path in _yaml_files(vis_dir):
        visibility_spec = _parse_visibility(path)
        _reject_duplicate(visibilities, visibility_spec.dataset, path, kind="visibility")
        _assert_filename_matches_dataset(path, visibility_spec.dataset)
        visibilities[visibility_spec.dataset] = visibility_spec
        visibility_paths[visibility_spec.dataset] = path
    return ContractBundle(
        schemas=schemas,
        visibilities=visibilities,
        schema_paths=schema_paths,
        visibility_paths=visibility_paths,
    )


def _yaml_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.yaml") if path.is_file())


def _parse_schema(path: Path, *, expected_layer: str) -> DatasetSchemaSpec:
    payload = _read_mapping(path)
    try:
        spec = DatasetSchemaSpec.model_validate(payload)
    except ValidationError as exc:
        raise ContractError(f"{path}: {exc}") from exc
    if spec.layer != expected_layer:
        raise ContractError(f"{path}: layer={spec.layer!r} 与目录 {expected_layer} 不一致")
    return spec


def _parse_visibility(path: Path) -> VisibilityContract:
    payload = _read_mapping(path)
    try:
        return VisibilityContract.model_validate(payload)
    except ValidationError as exc:
        raise ContractError(f"{path}: {exc}") from exc


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContractError(f"{path}: YAML 无法解析: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContractError(f"{path}: 根节点必须是映射")
    return raw


def _assert_filename_matches_dataset(path: Path, dataset: str) -> None:
    if path.stem != dataset:
        raise ContractError(f"{path}: 文件名必须与 dataset={dataset} 一致")


def _reject_duplicate(existing: dict[str, Any], dataset: str, path: Path, *, kind: str) -> None:
    if dataset in existing:
        raise ContractError(f"{path}: 重复的 {kind} dataset={dataset}")

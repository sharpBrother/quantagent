"""冻结 bundle 契约：manifest 完整性、digest 一致性、行列合同与文件清单。

`frozen/README.md` 的硬约束要求每个 bundle 带 `manifest.json`，digest 按统一 LF
计算，并逐文件记录行数与列合同。这组测试把它变成机械检查，防止冻结制品被静默
改写——`frozen/` 是发布链路的输入，改一位数就换了一次研究身份。

`frozen/` 允许暂时为空，所以发现不到 bundle 时 skip 而不是 fail。
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

MANIFEST_NAME = "manifest.json"
CONFIG_NAME = "config.json"
REQUIRED_KEYS = (
    "bundle_id",
    "research_line",
    "created",
    "purpose",
    "source_runs",
    "freeze_window",
    "config_sha256",
    "files",
    "boundary",
    "superseded_by",
)
EXPECTED_BOUNDARY = {
    "research_only": True,
    "no_database_write": True,
    "production_qualified": False,
}
# frozen/ 单文件上限：这里的体积由制品本身决定，不可压缩；超过需单独评估。
MAX_FILE_BYTES = 4 * 1024 * 1024
# manifest 自身不登记在自己里面；.gitkeep 只是占位，不算制品。
UNREGISTERED_ALLOWED = frozenset({MANIFEST_NAME, ".gitkeep"})


def lf_sha256(path: Path) -> str:
    """按统一 LF 计算 sha256：Windows checkout 的 CRLF 不应造成校验失败。"""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _require(condition: bool, message: str) -> None:
    """校验失败即抛 AssertionError，便于负向测试直接断言。"""
    if not condition:
        raise AssertionError(message)


def _check_manifest_keys(manifest: dict[str, Any], bundle_dir: Path) -> None:
    missing = [key for key in REQUIRED_KEYS if key not in manifest]
    _require(not missing, f"{bundle_dir}: manifest 缺字段 {missing}")
    boundary = manifest["boundary"]
    _require(isinstance(boundary, dict), f"{bundle_dir}: boundary 必须是映射")
    wrong = {k: boundary.get(k) for k, v in EXPECTED_BOUNDARY.items() if boundary.get(k) is not v}
    _require(not wrong, f"{bundle_dir}: boundary 声明不正确 {wrong}")
    _require(isinstance(manifest["files"], list), f"{bundle_dir}: files 必须是列表")
    _require(bool(manifest["files"]), f"{bundle_dir}: files 为空")


def _check_config(manifest: dict[str, Any], bundle_dir: Path) -> None:
    config_path = bundle_dir / CONFIG_NAME
    _require(config_path.is_file(), f"{bundle_dir}: 缺 {CONFIG_NAME}")
    _require(
        lf_sha256(config_path) == manifest["config_sha256"],
        f"{bundle_dir}: {CONFIG_NAME} 的 digest 与 manifest.config_sha256 不一致",
    )


def _check_registered_file(entry: dict[str, Any], bundle_dir: Path) -> str:
    rel: str = entry["path"]
    path = bundle_dir / rel
    _require(path.is_file(), f"{bundle_dir}: manifest 登记的文件不存在 {rel}")
    size = path.stat().st_size
    _require(size <= MAX_FILE_BYTES, f"{bundle_dir}: {rel} 体积 {size} 超过 {MAX_FILE_BYTES}")
    _require(
        lf_sha256(path) == entry["sha256"],
        f"{bundle_dir}: {rel} 的 digest 与 manifest 记录不一致",
    )
    if path.suffix == ".csv":
        _require("rows" in entry and "columns" in entry, f"{bundle_dir}: {rel} 缺 rows/columns")
        frame = pd.read_csv(path, float_precision="round_trip")
        _require(
            len(frame) == entry["rows"],
            f"{bundle_dir}: {rel} 行数 {len(frame)} 与记录 {entry['rows']} 不一致",
        )
        _require(
            list(frame.columns) == list(entry["columns"]),
            f"{bundle_dir}: {rel} 列名与记录不一致",
        )
    return rel


def _check_no_extra_files(registered: set[str], bundle_dir: Path) -> None:
    extra = sorted(
        path.relative_to(bundle_dir).as_posix()
        for path in bundle_dir.rglob("*")
        if path.is_file()
        and path.relative_to(bundle_dir).as_posix() not in registered | UNREGISTERED_ALLOWED
    )
    _require(not extra, f"{bundle_dir}: 存在 manifest 未登记的文件 {extra}")


def validate_bundle(bundle_dir: Path) -> None:
    """校验一个冻结 bundle；任何不一致抛 ``AssertionError``。"""
    manifest_path = bundle_dir / MANIFEST_NAME
    _require(manifest_path.is_file(), f"{bundle_dir}: 缺 {MANIFEST_NAME}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require(isinstance(manifest, dict), f"{bundle_dir}: {MANIFEST_NAME} 必须是映射")
    _check_manifest_keys(manifest, bundle_dir)
    _check_config(manifest, bundle_dir)
    registered = {_check_registered_file(entry, bundle_dir) for entry in manifest["files"]}
    _check_no_extra_files(registered, bundle_dir)


@pytest.mark.contracts
def test_frozen_bundles_match_manifest(frozen_root: Path) -> None:
    manifests = sorted(frozen_root.glob("*/*/manifest.json"))
    if not manifests:
        pytest.skip("frozen/ 下还没有 bundle")
    for manifest_path in manifests:
        validate_bundle(manifest_path.parent)


# 负向测试用的合成 bundle：结构与真实 bundle 相同，只是内容极小。
def _write_bundle(root: Path, rows: list[str] | None = None) -> Path:
    lines = ["2026-11-19", "2026-11-20"] if rows is None else rows
    columns = ["trade_dt", "r0_w_V"]
    bundle_dir = root
    (bundle_dir / "data").mkdir(parents=True)
    config_bytes = (
        json.dumps({"as_of": "2026-11-20"}, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    csv_bytes = ("\n".join([",".join(columns), *lines]) + "\n").encode()
    (bundle_dir / CONFIG_NAME).write_bytes(config_bytes)
    (bundle_dir / "data" / "signals.csv").write_bytes(csv_bytes)
    manifest = {
        "bundle_id": "test_line/synthetic",
        "research_line": "test_line",
        "created": "2026-11-24",
        "purpose": "契约测试用的合成 bundle。",
        "source_runs": [],
        "freeze_window": {"start": "2026-11-19", "end": "2026-11-20"},
        "config_sha256": lf_sha256(bundle_dir / CONFIG_NAME),
        "files": [
            {"path": CONFIG_NAME, "sha256": lf_sha256(bundle_dir / CONFIG_NAME)},
            {
                "path": "data/signals.csv",
                "sha256": lf_sha256(bundle_dir / "data" / "signals.csv"),
                "rows": len(lines),
                "columns": columns,
            },
        ],
        "boundary": dict(EXPECTED_BOUNDARY),
        "superseded_by": None,
    }
    (bundle_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return bundle_dir


def _append_row(bundle_dir: Path) -> None:
    path = bundle_dir / "data" / "signals.csv"
    path.write_bytes(path.read_bytes() + b"2026-11-23,\n")


def _add_unregistered(bundle_dir: Path) -> None:
    (bundle_dir / "data" / "notes.txt").write_text("未登记\n", encoding="utf-8")


def _rewrite_config(bundle_dir: Path) -> None:
    (bundle_dir / CONFIG_NAME).write_text('{"as_of": "2026-11-23"}\n', encoding="utf-8")


def _flip_csv_byte(bundle_dir: Path) -> None:
    path = bundle_dir / "data" / "signals.csv"
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"2026-11-20", b"2026-11-21"))


def _drop_boundary(bundle_dir: Path) -> None:
    path = bundle_dir / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["boundary"]["production_qualified"] = True
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


TAMPERS: dict[str, Callable[[Path], None]] = {
    "追加行": _append_row,
    "未登记文件": _add_unregistered,
    "改配置": _rewrite_config,
    "改数据": _flip_csv_byte,
    "越界声明": _drop_boundary,
}


@pytest.mark.contracts
def test_tampered_bundle_is_rejected(tmp_path: Path) -> None:
    good = _write_bundle(tmp_path / "good")
    validate_bundle(good)  # 未篡改的合成 bundle 必须先通过，否则下面的断言没有意义
    for name, tamper in TAMPERS.items():
        bundle_dir = _write_bundle(tmp_path / name.replace(" ", "_"))
        tamper(bundle_dir)
        with pytest.raises(AssertionError):
            validate_bundle(bundle_dir)

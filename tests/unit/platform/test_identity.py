"""digest 必须对键顺序不敏感，且拒绝无法规范化的对象。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from quantagent.platform.identity import digest_file, digest_json, new_run_id
from quantagent.platform.identity.digest import digest_bytes

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_json_digest_ignores_key_order() -> None:
    left = digest_json({"b": 2, "a": 1})
    right = digest_json({"a": 1, "b": 2})
    assert left == right
    assert len(left) == 64


@pytest.mark.unit
def test_json_digest_changes_when_value_changes() -> None:
    assert digest_json({"a": 1}) != digest_json({"a": 2})


@pytest.mark.unit
def test_file_digest_matches_bytes(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"quantagent")
    assert digest_file(path) == digest_bytes(b"quantagent")


@pytest.mark.unit
def test_run_id_is_32_hex_and_unique() -> None:
    first = new_run_id()
    second = new_run_id()
    assert first != second
    assert len(first) == 32
    int(first, 16)

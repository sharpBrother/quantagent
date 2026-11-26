"""CLI 手动 sync 的看门狗接线：jydb / suntime sync 必须在子进程里跑，不直接调业务函数。

11-25 jydb 卡死 7 小时靠人工发现。调度侧已有看门狗，手动 CLI 若绕过就成盲区。
本测试断言两条命令都经 run_watched_child 且子进程入口是模块顶层函数（spawn 才能导入）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from quantagent.cli.app import app
from quantagent.ingest import sync_child
from quantagent.platform.config import cache_clear
from quantagent.platform.config.settings import Settings
from quantagent.platform.storage import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[None, None, None]:
    cache_clear()
    settings = Settings(_env_file=None, var_root=tmp_path / "var", allow_db_write=False)
    monkeypatch.setattr("quantagent.cli.ingest.get_settings", lambda: settings)
    monkeypatch.setattr(
        "quantagent.cli.ingest.resolve_var_paths",
        lambda settings, repo_root: resolve_var_paths(settings, repo_root=tmp_path),
    )
    monkeypatch.setattr("quantagent.cli.ingest.detect_repo_root", lambda: tmp_path)
    yield
    cache_clear()


def _capture_run_watched(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """拦截 run_watched_child，记录参数并返回假结果，不起真实子进程。"""
    captured: dict[str, object] = {}

    def fake_run_watched_child(**kwargs: object) -> object:
        captured.update(kwargs)
        # 返回带必需字段的假结果，让 CLI 的输出格式化不炸。
        return type(
            "R",
            (),
            {
                "written": False,
                "dataset": "src.jydb.x",
                "pages": 1,
                "row_count": 9,
                "inserted": 0,
                "replaced": 0,
                "skipped": 0,
                "metadata_skipped": 0,
                "dml_count": 0,
                "batch_ids": (),
                "source_cursor": "{}",
                "payload_digest": "d",
            },
        )()

    monkeypatch.setattr("quantagent.ingest.watchdog.run_watched_child", fake_run_watched_child)
    # CLI 在函数体内 import run_watched_child；monkeypatch 模块属性即可，因为 import 在调用时执行。
    return captured


@pytest.mark.unit
def test_jydb_sync_goes_through_watchdog_child(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_run_watched(monkeypatch)
    result = runner.invoke(app, ["ingest", "jydb", "sync", "C_ED_IndicatorMain", "--max-pages", "1"])
    assert result.exit_code == 0, result.output
    assert captured.get("table") == "C_ED_IndicatorMain"
    # 子进程入口必须是 ingest 层的顶层函数，spawn 才能按名导入。
    assert captured.get("child_target") is sync_child.jydb_sync_child
    assert "jydb_ingest_progress" in str(captured.get("progress_dir"))


@pytest.mark.unit
def test_suntime_sync_goes_through_watchdog_child(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_run_watched(monkeypatch)
    result = runner.invoke(app, ["ingest", "suntime", "sync", "con_forecast_idx", "--max-pages", "1"])
    assert result.exit_code == 0, result.output
    assert captured.get("table") == "con_forecast_idx"
    assert captured.get("child_target") is sync_child.suntime_sync_child
    assert "suntime_ingest_progress" in str(captured.get("progress_dir"))


@pytest.mark.unit
def test_sync_children_are_module_top_level_for_spawn() -> None:
    """spawn 子进程按"模块.函数名"导入目标。是模块顶层函数且可 import 才不会起不来。"""
    module = sync_child

    assert hasattr(module, "jydb_sync_child")
    assert hasattr(module, "suntime_sync_child")
    # 顶层函数：__qualname__ 不含点（不在类或嵌套函数里）。
    assert module.jydb_sync_child.__qualname__ == "jydb_sync_child"
    assert module.suntime_sync_child.__qualname__ == "suntime_sync_child"

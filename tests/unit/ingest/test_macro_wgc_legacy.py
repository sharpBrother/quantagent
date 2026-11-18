"""旧库 WGC 迁移保留原始记录，并默认不写库。"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quantagent.ingest.jobs.macro_wgc_legacy import ingest_wgc_legacy
from quantagent.platform.config import Settings
from quantagent.platform.storage import resolve_var_paths


@pytest.mark.unit
def test_wgc_legacy_dry_run_preserves_source_and_logs(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    row = {
        "period_end": "20250630",
        "geography": "WORLD",
        "category": "BARS",
        "value_tonnes": Decimal("250.70000000"),
        "publish_date": "20250731",
        "source": "wgc:gdt_html",
        "file_sha256": "a" * 64,
        "record_hash": "b" * 64,
        "ingested_at": datetime(2026, 9, 9),
    }
    result = ingest_wgc_legacy(settings=settings, paths=paths, fetch=lambda: [row])
    assert not result.written
    assert result.row_count == 1
    assert result.dml_count == 0
    assert len(list(paths.runs.glob("*.json"))) == 1

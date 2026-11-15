"""长表里的切段振幅等于旧消费者看到的值：1 日 cutamp 乘以 -1。"""

from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from quantagent.adapters.lake.feature_value import LakeFeatureRepository
from quantagent.features.library.price.cutamp import DEFINITION_VERSION, FEATURE_ID, PARAM_HASH
from quantagent.platform.config import get_settings
from quantagent.platform.storage import detect_repo_root, resolve_var_paths

_FIXTURE = Path(__file__).parents[1] / "golden" / "market_data" / "cutamp_wx2.json"
_SCALE = Decimal("0.000001")


@pytest.mark.integration
def test_feature_table_matches_legacy_loader_sign() -> None:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    paths = resolve_var_paths(get_settings(), repo_root=detect_repo_root())
    rows = LakeFeatureRepository(paths.lake / "feature" / "value").scan_window(
        as_of=date(2024, 1, 5),
        feature_id=FEATURE_ID,
        definition_version=DEFINITION_VERSION,
        param_hash=PARAM_HASH,
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
    )
    actual = {
        (row.event_dt.isoformat(), row.asset_id): Decimal(str(row.value)).quantize(
            _SCALE,
            rounding=ROUND_HALF_UP,
        )
        for row in rows
    }
    expected = {
        (item["trade_dt"], item["wind_code"]): -Decimal(item["cutamp"])
        for item in payload["rows"]
    }
    assert actual == expected

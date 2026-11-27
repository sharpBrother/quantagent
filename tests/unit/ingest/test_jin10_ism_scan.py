"""金十 ISM 扫描与发现：水位、due 判定、命中、跳空、身份校验与 fail-closed。假源不联网。"""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest

from quantagent.adapters.postgres.src_targets import JIN10_ECONOMIC_CALENDAR
from quantagent.ingest.errors import IngestError, SourceFetchError
from quantagent.ingest.jobs.jin10_ism_scan import (
    _row_of,
    ingest_jin10_ism_scan,
    scan_for_next_release,
)
from quantagent.ingest.sources.macro.jin10_ism import (
    Jin10IsmDetail,
    parse_jin10_ism_detail,
    parse_jin10_next_public_time,
)
from quantagent.ingest.writers.src_follow import fingerprint_columns
from quantagent.ingest.writers.src_insert import row_hash
from quantagent.platform.config import Settings
from quantagent.platform.identity import digest_json
from quantagent.platform.storage import resolve_var_paths

if TYPE_CHECKING:
    from pathlib import Path

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _ism_payload(event_id: int, *, pub: str, public: str, period: str, actual: str | None) -> dict:
    return {
        "status": 200,
        "data": {
            "dataId": event_id,
            "datanameId": 129,
            "pub_time": pub,
            "public_time": public,
            "time_period": period,
            "actual": actual,
            "consensus": "55.0",
            "previous": "55.5",
        },
    }


def _other_indicator_payload(event_id: int) -> dict:
    return {
        "status": 200,
        "data": {
            "dataId": event_id,
            "datanameId": 131,
            "pub_time": "2026-12-01T15:00:00.000Z",
            "public_time": "2026-12-01 23:00:00",
            "time_period": "11月",
            "actual": None,
        },
    }


# ---------------------------------------------------------------------------
# scan_for_next_release
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_scan_hits_ism_after_other_indicators() -> None:
    """连排段内先遇其它指标、跳空，最后命中 ISM。返回命中详情、扫描个数与高水位。"""
    target = _ism_payload(
        1179329,
        pub="2026-12-01T15:00:00.000Z",
        public="2026-12-01 23:00:00",
        period="11月",
        actual=None,
    )
    table = {
        1178752: _other_indicator_payload(1178752),
        1178753: {},  # 跳空
        1178754: {"status": 404, "data": None},  # 显式不存在
        1179329: target,
    }

    def fetch(eid: int) -> dict:
        return table.get(eid, {})

    detail, scanned, last_id = scan_for_next_release(
        start_id=1178752, max_scan=3000, fetch_raw=fetch
    )
    assert detail is not None
    assert detail.data_id == 1179329
    assert detail.actual_value is None  # 尚未公布
    # scanned 是从起点到命中 inclusive 的个数
    assert scanned == 1179329 - 1178752 + 1
    assert last_id == 1179329


@pytest.mark.unit
def test_scan_returns_none_when_exhausted() -> None:
    """窗口内没有 ISM：返回未命中，scanned 等于 max_scan，高水位为窗口末端。"""
    detail, scanned, last_id = scan_for_next_release(
        start_id=1000, max_scan=50, fetch_raw=lambda eid: {}
    )
    assert detail is None
    assert scanned == 50
    assert last_id == 1049


@pytest.mark.unit
def test_scan_fails_closed_on_invalid_ism_identity() -> None:
    """datanameId 为 129 但内容校验失败（时区不一致）时，抛错而不是跳过。

    这是 fail-closed：源端把 ISM 的记录结构改了，宁可报错也不静默当没看见。
    """
    bad = _ism_payload(
        2000,
        pub="2026-12-01T15:00:00.000Z",
        public="2026-12-01 22:00:00",  # 与 UTC 不一致
        period="11月",
        actual=None,
    )

    def fetch(eid: int) -> dict:
        return bad if eid == 2000 else {}

    with pytest.raises(SourceFetchError):
        scan_for_next_release(start_id=2000, max_scan=10, fetch_raw=fetch)


@pytest.mark.unit
def test_scan_skips_non_dict_data() -> None:
    """data 不是 dict（异常结构）时按跳空处理，不中断扫描。"""
    table = {
        100: {"status": 200, "data": None},
        101: _ism_payload(
            101,
            pub="2026-12-01T15:00:00.000Z",
            public="2026-12-01 23:00:00",
            period="11月",
            actual="55.0",
        ),
    }

    def fetch(eid: int) -> dict:
        return table.get(eid, {})

    detail, _, _ = scan_for_next_release(start_id=100, max_scan=10, fetch_raw=fetch)
    assert detail is not None and detail.data_id == 101


# ---------------------------------------------------------------------------
# next_public_time 解析
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_next_public_time_parsed_as_shanghai() -> None:
    result = parse_jin10_next_public_time("2026-12-01 23:00:00")
    assert result is not None
    assert result.tzinfo is not None
    assert result.astimezone(UTC) == datetime(2026, 12, 1, 15, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.parametrize("value", [None, "", "   "])
def test_next_public_time_missing_is_none(value: object) -> None:
    assert parse_jin10_next_public_time(value) is None


@pytest.mark.unit
def test_next_public_time_invalid_format_raises() -> None:
    with pytest.raises(SourceFetchError):
        parse_jin10_next_public_time("12月1日")


# ---------------------------------------------------------------------------
# 详情解析携带 next_public_time
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detail_includes_next_public_at() -> None:
    payload = _ism_payload(
        1178751,
        pub="2026-11-02T15:00:00.000Z",
        public="2026-11-02 23:00:00",
        period="10月",
        actual="55.5",
    )
    payload["data"]["next_public_time"] = "2026-12-01 23:00:00"
    detail = parse_jin10_ism_detail(payload, requested_id=1178751)
    assert detail.next_public_at is not None
    assert detail.next_public_at.astimezone(UTC) == datetime(2026, 12, 1, 15, tzinfo=UTC)


@pytest.mark.unit
def test_detail_without_next_public_time_is_none() -> None:
    payload = _ism_payload(
        1178751,
        pub="2026-11-02T15:00:00.000Z",
        public="2026-11-02 23:00:00",
        period="10月",
        actual="55.5",
    )
    detail = parse_jin10_ism_detail(payload, requested_id=1178751)
    assert detail.next_public_at is None
    # 其余字段不受影响
    assert detail.actual_value == Decimal("55.5")
    assert detail.publish_date == date(2026, 11, 2)


# ---------------------------------------------------------------------------
# 编排：水位、due 判定、写入、fail-closed（stub connection + fake store）
# ---------------------------------------------------------------------------

_JIN10_KEY = ("indicator_id", "publish_date", "data_id")


def _detail(
    event_id: int,
    *,
    publish_date: date,
    period_end: date,
    actual: str | None,
    next_public: datetime | None,
) -> Jin10IsmDetail:
    return Jin10IsmDetail(
        data_id=event_id,
        published_at=datetime(
            publish_date.year, publish_date.month, publish_date.day, 15, tzinfo=UTC
        ),
        publish_date=publish_date,
        period_end=period_end,
        time_period=f"{period_end.month}月",
        actual_value=None if actual is None else Decimal(actual),
        forecast_value=Decimal("55.0"),
        previous_value=Decimal("55.5"),
        revised_value=None,
        next_public_at=next_public,
    )


def _row_of_detail(d: Jin10IsmDetail) -> dict[str, object]:
    return {
        "indicator_id": 129,
        "publish_date": d.publish_date,
        "data_id": d.data_id,
        "period_end": d.period_end,
        "time_period": d.time_period,
        "published_at": d.published_at,
        "actual_value": d.actual_value,
        "forecast_value": d.forecast_value,
        "previous_value": d.previous_value,
        "revised_value": d.revised_value,
        "source": "jin10.economic_calendar",
    }


class FakeJin10Store:
    """模拟 PostgresSrcStore 的跟随源端语义，主键 (indicator_id, publish_date, data_id)。

    同时充当水位连接（``_conn`` 指向自身），cursor() 返回预置的查询结果。
    """

    def __init__(
        self,
        *,
        rows: list[dict[str, object]],
        recent_ids: list[int],
        max_id: int,
    ) -> None:
        self.state: dict[tuple[object, ...], dict[str, Any]] = {}
        for row in rows:
            key = tuple(row[c] for c in _JIN10_KEY)
            fp = fingerprint_columns(JIN10_ECONOMIC_CALENDAR)
            self.state[key] = {
                "hash": row_hash(row, fp),
                "row": dict(row),
                "batch": 0,
            }
        self.committed = copy.deepcopy(self.state)
        self.batches: list[dict[str, Any]] = []
        self.deleted: list[tuple[object, ...]] = []
        self.inserted_rows: list[dict[str, object]] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.next_batch = 100
        self.cursors: list[str | None] = []
        # 水位查询预置
        self._recent_ids = list(recent_ids)
        self._max_id = max_id
        self._conn = self  # _store_conn 读取的底层连接就是自身

    # -- 水位 connection 接口（cursor/execute/fetch） --
    def cursor(self) -> FakeJin10Store:
        return self

    def __enter__(self) -> FakeJin10Store:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self._last_sql = sql
        self._last_params = params

    def fetchall(self) -> list[tuple]:
        if "ORDER BY publish_date" in self._last_sql:
            return [(did, date(2026, 11, 2)) for did in self._recent_ids]
        return []

    def fetchone(self) -> tuple | None:
        if "MAX(data_id)" in self._last_sql:
            return (self._max_id,)
        return None

    # -- SrcWriteStore 接口 --
    def existing_keys(self, spec, keys):
        return {k for k in keys if k in self.state}

    def latest_source_cursor(self, spec):
        return self.cursors[-1] if self.cursors else None

    def existing_hashes(self, spec, keys):
        return {k: self.state[k]["hash"] for k in keys if k in self.state}

    def existing_values(self, spec, keys, columns):
        return {k: tuple(self.state[k]["row"][c] for c in columns) for k in keys if k in self.state}

    def insert_batch(
        self,
        *,
        spec,
        window_start,
        window_end,
        row_count,
        payload_digest,
        started_at,
        finished_at,
        source_cursor=None,
    ):
        bid = self.next_batch
        self.next_batch += 1
        self.batches.append(
            {
                "id": bid,
                "window_start": window_start,
                "window_end": window_end,
                "source_cursor": source_cursor,
            }
        )
        if source_cursor is not None:
            self.cursors.append(source_cursor)
        return bid

    def delete_keys(self, spec, keys):
        self.deleted.extend(keys)
        for k in keys:
            self.state.pop(k, None)

    def insert_rows(self, spec, rows, *, hashes, batch_id, ingested_at):
        for row, digest in zip(rows, hashes, strict=True):
            key = tuple(row[c] for c in _JIN10_KEY)
            self.state[key] = {"hash": digest, "row": dict(row), "batch": batch_id}
            self.inserted_rows.append(dict(row))

    def readback_hashes(self, spec, batch_id, keys):
        return [
            self.state[k]["hash"]
            for k in keys
            if k in self.state and self.state[k]["batch"] == batch_id
        ]

    def mismatched_rows(self, spec, batch_id, rows):
        bad = []
        for row in rows:
            key = tuple(row[c] for c in _JIN10_KEY)
            stored = self.state.get(key)
            if stored is None or any(stored["row"][c] != row[c] for c in row):
                bad.append(key)
        return bad

    def commit(self):
        self.commit_calls += 1
        self.committed = copy.deepcopy(self.state)

    def rollback(self):
        self.rollback_calls += 1
        self.state = copy.deepcopy(self.committed)

    def close(self):
        pass


def _make_store_with_existing() -> FakeJin10Store:
    """库内已有 11-02 期（最新发布）与 9-01 期（全库最大 ID 1184254）。"""
    oct_rel = _detail(
        1178751,
        publish_date=date(2026, 11, 2),
        period_end=date(2026, 10, 31),
        actual="55.5",
        next_public=datetime(2026, 12, 1, 23, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    sep = _detail(
        1145155,
        publish_date=date(2026, 10, 1),
        period_end=date(2026, 9, 30),
        actual="54.5",
        next_public=None,
    )
    aug = _detail(
        1184254,
        publish_date=date(2026, 9, 1),
        period_end=date(2026, 8, 31),
        actual="54.6",
        next_public=None,
    )
    rows = [_row_of_detail(d) for d in (oct_rel, sep, aug)]
    # 按发布日降序：1178751(11-02) > 1145155(10-01) > 1184254(09-01)
    return FakeJin10Store(rows=rows, recent_ids=[1178751, 1145155, 1184254], max_id=1184254)


def _scan_settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, profile="local", allow_db_write=True, var_root=tmp_path)


@pytest.mark.unit
def test_not_due_only_rechecks_no_scan(tmp_path: Path) -> None:
    """未到 next_public_time：不扫描、只复查近期，且写库提交。"""
    store = _make_store_with_existing()
    settings = _scan_settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    # now 在 12-01 23:00 北京之前
    now = datetime(2026, 11, 30, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    details = {
        1178751: _detail(
            1178751,
            publish_date=date(2026, 11, 2),
            period_end=date(2026, 10, 31),
            actual="55.5",
            next_public=datetime(2026, 12, 1, 23, tzinfo=ZoneInfo("Asia/Shanghai")),
        ),
        1145155: _detail(
            1145155,
            publish_date=date(2026, 10, 1),
            period_end=date(2026, 9, 30),
            actual="54.5",
            next_public=None,
        ),
        1184254: _detail(
            1184254,
            publish_date=date(2026, 9, 1),
            period_end=date(2026, 8, 31),
            actual="54.6",
            next_public=None,
        ),
    }
    result = ingest_jin10_ism_scan(
        settings=settings,
        paths=paths,
        write_db=True,
        store=store,
        fetch_detail=lambda eid: details[eid],
        fetch_raw=lambda eid: {},
        now=lambda: now,
    )
    assert result.written
    assert not result.due
    assert not result.scan_attempted
    assert result.rechecked == 3
    assert store.commit_calls == 1
    # 没有插入新行（3 期复查内容未变，全 skipped）
    assert result.inserted == 0


@pytest.mark.unit
def test_revision_replaces_existing_row(tmp_path: Path) -> None:
    """源端修订 actual：同一主键删旧插新，计入 replaced。"""
    store = _make_store_with_existing()
    settings = _scan_settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    now = datetime(2026, 11, 30, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    # 11-02 期 actual 从 55.5 修订为 55.6
    details = {
        1178751: _detail(
            1178751,
            publish_date=date(2026, 11, 2),
            period_end=date(2026, 10, 31),
            actual="55.6",
            next_public=datetime(2026, 12, 1, 23, tzinfo=ZoneInfo("Asia/Shanghai")),
        ),
        1145155: _detail(
            1145155,
            publish_date=date(2026, 10, 1),
            period_end=date(2026, 9, 30),
            actual="54.5",
            next_public=None,
        ),
        1184254: _detail(
            1184254,
            publish_date=date(2026, 9, 1),
            period_end=date(2026, 8, 31),
            actual="54.6",
            next_public=None,
        ),
    }
    result = ingest_jin10_ism_scan(
        settings=settings,
        paths=paths,
        write_db=True,
        store=store,
        fetch_detail=lambda eid: details[eid],
        fetch_raw=lambda eid: {},
        now=lambda: now,
    )
    assert result.replaced == 1
    # 库里最新值应为修订后的 55.6
    key = (129, date(2026, 11, 2), 1178751)
    assert store.state[key]["row"]["actual_value"] == Decimal("55.6")


@pytest.mark.unit
def test_due_scans_and_inserts_new_release(tmp_path: Path) -> None:
    """到期：扫描命中新事件并插入。命中 ID 小于全库最大也接受（实证 1179329 < 1184254）。"""
    store = _make_store_with_existing()
    settings = _scan_settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    now = datetime(2026, 12, 2, 10, tzinfo=ZoneInfo("Asia/Shanghai"))  # 已过 12-01 23:00
    details = {
        1178751: _detail(
            1178751,
            publish_date=date(2026, 11, 2),
            period_end=date(2026, 10, 31),
            actual="55.5",
            next_public=datetime(2026, 12, 1, 23, tzinfo=ZoneInfo("Asia/Shanghai")),
        ),
        1145155: _detail(
            1145155,
            publish_date=date(2026, 10, 1),
            period_end=date(2026, 9, 30),
            actual="54.5",
            next_public=None,
        ),
        1184254: _detail(
            1184254,
            publish_date=date(2026, 9, 1),
            period_end=date(2026, 8, 31),
            actual="54.6",
            next_public=None,
        ),
    }
    new_payload = _ism_payload(
        1179329,
        pub="2026-12-01T15:00:00.000Z",
        public="2026-12-01 23:00:00",
        period="11月",
        actual="56.1",
    )
    raw_table = {1179329: new_payload}
    result = ingest_jin10_ism_scan(
        settings=settings,
        paths=paths,
        write_db=True,
        store=store,
        fetch_detail=lambda eid: details[eid],
        fetch_raw=lambda eid: raw_table.get(eid, {}),
        now=lambda: now,
    )
    assert result.due and result.scan_attempted
    assert result.found_data_id == 1179329
    assert result.scan_start_id == 1178752  # 上一期 + 1，不是 max_id+1
    key = (129, date(2026, 12, 1), 1179329)
    assert key in store.state
    assert result.inserted == 1


@pytest.mark.unit
def test_due_scan_exhausted_fails_closed(tmp_path: Path) -> None:
    """到期但扫超上限未命中：fail-closed 报错，不写库。"""
    store = _make_store_with_existing()
    settings = _scan_settings(tmp_path)
    paths = resolve_var_paths(settings, repo_root=tmp_path)
    now = datetime(2026, 12, 2, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    details = {
        1178751: _detail(
            1178751,
            publish_date=date(2026, 11, 2),
            period_end=date(2026, 10, 31),
            actual="55.5",
            next_public=datetime(2026, 12, 1, 23, tzinfo=ZoneInfo("Asia/Shanghai")),
        ),
        1145155: _detail(
            1145155,
            publish_date=date(2026, 10, 1),
            period_end=date(2026, 9, 30),
            actual="54.5",
            next_public=None,
        ),
        1184254: _detail(
            1184254,
            publish_date=date(2026, 9, 1),
            period_end=date(2026, 8, 31),
            actual="54.6",
            next_public=None,
        ),
    }
    with pytest.raises(IngestError, match="未找到新的 ISM 事件"):
        ingest_jin10_ism_scan(
            settings=settings,
            paths=paths,
            write_db=True,
            store=store,
            fetch_detail=lambda eid: details[eid],
            fetch_raw=lambda eid: {},  # 全空
            now=lambda: now,
            max_scan=50,
        )
    assert store.commit_calls == 0


# ---------------------------------------------------------------------------
# 指纹稳定性回归：decimal 标度与 datetime 时区不应导致同一行指纹漂移
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_row_of_quantizes_decimal_to_storage_precision() -> None:
    """详情接口给任意标度（55.5），入库 numeric(18,8) 读回是 55.50000000。

    ``_row_of`` 必须量化到存储精度，否则写入指纹与回读指纹不一致，复查永不命中 fast-path。
    回归: 2026-11-27 digest 修复。
    """
    detail = Jin10IsmDetail(
        data_id=1178751,
        published_at=datetime(2026, 11, 2, 15, tzinfo=UTC),
        publish_date=date(2026, 11, 2),
        period_end=date(2026, 10, 31),
        time_period="10月",
        actual_value=Decimal("55.5"),
        forecast_value=Decimal("54.6"),
        previous_value=Decimal("54.50"),
        revised_value=None,
        next_public_at=None,
    )
    row = _row_of(detail)
    assert row["actual_value"] == Decimal("55.50000000")
    assert row["forecast_value"] == Decimal("54.60000000")
    assert row["previous_value"] == Decimal("54.50000000")
    assert row["revised_value"] is None


@pytest.mark.unit
def test_fingerprint_stable_across_decimal_scale_and_timezone() -> None:
    """同一行：写入侧（量化后 + UTC）与回读侧（8 位标度 + 上海时区）指纹必须一致。"""
    # 写入侧：源端值经 _row_of 量化，published_at 是 UTC
    write_detail = Jin10IsmDetail(
        data_id=1178751,
        published_at=datetime(2026, 11, 2, 15, tzinfo=UTC),
        publish_date=date(2026, 11, 2),
        period_end=date(2026, 10, 31),
        time_period="10月",
        actual_value=Decimal("55.5"),
        forecast_value=Decimal("54.6"),
        previous_value=Decimal("54.5"),
        revised_value=None,
        next_public_at=None,
    )
    write_row = _row_of(write_detail)
    fp = fingerprint_columns(JIN10_ECONOMIC_CALENDAR)
    write_hash = row_hash(write_row, fp)

    # 回读侧：模拟 timestamptz 读回为上海时区、numeric 读回为 8 位标度
    readback_row = dict(write_row)
    readback_row["published_at"] = datetime(2026, 11, 2, 23, tzinfo=ZoneInfo("Asia/Shanghai"))
    readback_row["actual_value"] = Decimal("55.50000000")
    readback_hash = row_hash(readback_row, fp)

    assert write_hash == readback_hash


@pytest.mark.unit
def test_digest_json_normalizes_datetime_to_utc() -> None:
    """``digest_json`` 对带时区时间统一转 UTC：同一时刻的不同时区表示 digest 相同。"""
    utc = datetime(2026, 11, 2, 15, tzinfo=UTC)
    shanghai = datetime(2026, 11, 2, 23, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert digest_json({"v": utc}) == digest_json({"v": shanghai})
    naive = datetime(2026, 11, 2, 15)
    # 不带时区的时间保持原样（不引入时区假设）
    assert digest_json({"v": naive}) == digest_json({"v": datetime(2026, 11, 2, 15)})

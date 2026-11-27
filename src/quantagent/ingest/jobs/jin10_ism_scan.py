"""金十 ISM 制造业 PMI 新事件发现与增量采集。

发现机制不依赖月历 CDN、历史列表或加密的 WebSocket：

- 上一期详情自带 ``next_public_time``（下一期发布的北京时间），决定何时开始找新事件。
- 近期 event ID 密集连排，且已排期的未来事件也能按 ID 读到。下一期必然出现在
  上一期 ``data_id`` 之后有限范围内，按序扫描 ``datanameId == 129`` 的记录即可发现。

修订处理：详情接口对同一 ``data_id`` 直接覆盖 ``actual``，不给版本身份，属于
"源端不给版本"（见 docs/adr/2026-11-18-source-published-versions.md）。负责人 2026-11-27
裁定按跟随源端处理：同一事务内按主键删旧插新，与 Tushare/Wind 镜像一致，计数入 run log。

水位与 fail-closed：扫描到的最大 ``data_id`` 写入 ``_batch.source_cursor``，停机后从
上次位置续扫。未到发布日只复查修订；扫超 ``max_scan`` 仍未找到新事件即报错，
不静默成功（避免任务成功却长期漏数）。
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from quantagent.adapters.postgres.src_targets import JIN10_ECONOMIC_CALENDAR
from quantagent.adapters.postgres.src_write import PostgresSrcStore
from quantagent.ingest.errors import IngestError
from quantagent.ingest.sources.macro.jin10_ism import (
    INDICATOR_ID,
    fetch_jin10_ism_detail,
    fetch_jin10_raw_detail,
    parse_jin10_ism_detail,
)
from quantagent.ingest.writers.src_follow import write_src_follow
from quantagent.platform.errors import RunLogError
from quantagent.platform.identity import digest_json
from quantagent.platform.pg import connect
from quantagent.platform.runlog import RunLog, persist_run_log

if TYPE_CHECKING:
    from collections.abc import Callable

    import psycopg

    from quantagent.ingest.sources.macro.jin10_ism import Jin10IsmDetail
    from quantagent.ingest.writers.store import SrcWriteStore
    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

ACTION = "ingest.macro.jin10_ism_scan"

# 实证（2026-11-27）：下一期 event ID 通常落在上一期 ID 之后的连排段内。12-01 期
# data_id=1179329，在上一期 1178751 之后 578；该窗口 579 个 ID 命中 562 个事件。
# lookahead 取 3000，覆盖正常排期段又限制每日请求量（约每分钟数十个）。
# 注意金十 ID 不随发布时间单调：2026-10-01 期 1145155 比前期小约 3.9 万（排期批次
# 回落）。正向 lookahead 扫不到这种回落，此时扫超上限 fail-closed 报错，由人工
# 介入补 ID——宁可漏报也不静默漏数。
MAX_SCAN_IDS = 3000

# 每次日更复查最近几期的修订。ISM 数值偶尔在发布后数日内被金十修订，回看 4 期
# （约四个月）既覆盖常见修订窗口，又把每日常规请求数控制在个位数。
REVISION_LOOKBACK = 4


@dataclass(frozen=True)
class Jin10IsmScanResult:
    """``written`` 为 False 时是干跑：只读源端与库内水位，计数字段不代表真实写入。"""

    dataset: str
    written: bool
    latest_data_id: int
    next_public_at: datetime | None
    due: bool
    scan_attempted: bool
    scan_start_id: int | None
    scanned: int
    found_data_id: int | None
    found_publish_date: str | None
    rechecked: int
    row_count: int
    inserted: int
    replaced: int
    skipped: int
    metadata_skipped: int
    dml_count: int
    payload_digest: str
    output_digest: str


def _quantize8(value: Decimal | None) -> Decimal | None:
    """数值量化到 numeric(18,8) 的存储精度。

    详情接口给的是 ``55.5`` 这类任意标度，入库 numeric(18,8) 读回是 ``55.50000000``。
    指纹 digest 按十进制文本序列化，标度不同会导致同一行的写入指纹与回读指纹不一致。
    写入端先量化到存储精度，让两侧一致（与 tushare、GPR 写入端的做法同理）。
    """
    if value is None:
        return None
    return value.quantize(_NUMERIC_QUANTUM)


_NUMERIC_QUANTUM = Decimal("0.00000001")


def _row_of(detail: Jin10IsmDetail) -> dict[str, object]:
    return {
        "indicator_id": INDICATOR_ID,
        "publish_date": detail.publish_date,
        "data_id": detail.data_id,
        "period_end": detail.period_end,
        "time_period": detail.time_period,
        "published_at": detail.published_at,
        "actual_value": _quantize8(detail.actual_value),
        "forecast_value": _quantize8(detail.forecast_value),
        "previous_value": _quantize8(detail.previous_value),
        "revised_value": _quantize8(detail.revised_value),
        "source": "jin10.economic_calendar",
    }


def scan_for_next_release(
    *,
    start_id: int,
    max_scan: int,
    fetch_raw: Callable[[int], dict[str, object]],
) -> tuple[Jin10IsmDetail | None, int, int]:
    """从 ``start_id`` 起按序扫描，返回 (命中的 ISM 详情, 扫描个数, 扫描到的最大 ID)。

    只把 ``datanameId == 129`` 且身份校验通过的记录当作命中；其它指标、不存在的事件
    （跳空）都跳过。扫满 ``max_scan`` 个 ID 未命中则返回 ``(None, scanned, last_id)``。
    fetch_raw 可注入，便于单测不联网。
    """
    scanned = 0
    last_id = start_id - 1
    for event_id in range(start_id, start_id + max_scan):
        scanned += 1
        last_id = event_id
        payload = fetch_raw(event_id)
        if not payload:
            continue
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("datanameId") != INDICATOR_ID:
            continue
        # 命中候选；parse 做完整身份与时区一致性校验，不合格即抛错 fail-closed。
        detail = parse_jin10_ism_detail(payload, requested_id=event_id)
        return detail, scanned, last_id
    return None, scanned, last_id


def _query_watermark(conn: psycopg.Connection, limit: int) -> tuple[list[int], int, int]:
    """库内水位，只读。返回 (最近 limit 期按发布日降序的 data_id, 最新发布日的 data_id, 最大 data_id)。

    扫描起点与「最新一期」必须分开：金十 event ID 按排期批次分配，不随发布时间单调。
    实测 2026-11-02 发布的 10 月期 data_id=1178751，小于 2026-09-01 发布的 8 月期
    1184254。因此：

    - ``next_public_time`` 取自 **publish_date 最新** 的那一期（真正的最新发布）。
    - 扫描新事件从 **最新发布日那期的 data_id + 1** 开始（下一期落在其后的连排段）。
      用全库 MAX(data_id) 会漏掉 ID 小于最大值的新事件，见模块文档的实证说明。
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_id, publish_date FROM src_macro.jin10_economic_calendar "
            "WHERE indicator_id = %s AND data_id > 0 "
            "ORDER BY publish_date DESC, data_id DESC LIMIT %s",
            (INDICATOR_ID, limit),
        )
        recent = cur.fetchall()
        cur.execute(
            "SELECT COALESCE(MAX(data_id), 0) FROM src_macro.jin10_economic_calendar "
            "WHERE indicator_id = %s AND data_id > 0",
            (INDICATOR_ID,),
        )
        max_id_row = cur.fetchone()
    ids = [int(item[0]) for item in recent]
    latest_release_id = ids[0] if ids else 0
    max_id = int(max_id_row[0]) if max_id_row is not None else 0
    return ids, latest_release_id, max_id


def ingest_jin10_ism_scan(
    *,
    settings: Settings,
    paths: VarPaths,
    write_db: bool = False,
    fetch_detail: Callable[[int], Jin10IsmDetail] = fetch_jin10_ism_detail,
    fetch_raw: Callable[[int], dict[str, object]] = fetch_jin10_raw_detail,
    store: SrcWriteStore | None = None,
    now: Callable[[], datetime] | None = None,
    max_scan: int = MAX_SCAN_IDS,
    revision_lookback: int = REVISION_LOOKBACK,
) -> Jin10IsmScanResult:
    """发现新一期并复查近期修订；默认干跑。读取水位与写入在同一事务，成功才推进水位。"""
    started = datetime.now(UTC)
    clock = now or (lambda: datetime.now(UTC))
    owned_conn = None
    try:
        query_conn: psycopg.Connection
        if write_db:
            # 真写：水位读取与写入同一事务，复用写入 store 的连接。
            if store is None:
                owned_conn = connect(settings, "src")
                store = PostgresSrcStore(owned_conn)
            query_conn = _store_conn(store)
        else:
            # 干跑：独立短连接只读水位，写完就关，不进事务。
            owned_conn = connect(settings, "src")
            query_conn = owned_conn
        result = _run(
            settings=settings,
            write_db=write_db,
            store=store,
            query_conn=query_conn,
            fetch_detail=fetch_detail,
            fetch_raw=fetch_raw,
            clock=clock,
            max_scan=max_scan,
            revision_lookback=revision_lookback,
        )
    except Exception as exc:
        if store is not None and write_db:
            with suppress(Exception):
                store.rollback()
        finished = datetime.now(UTC)
        with suppress(RunLogError):
            persist_run_log(
                RunLog(
                    action=ACTION,
                    status="failure",
                    started_at=started,
                    finished_at=finished,
                    elapsed_ms=int((finished - started).total_seconds() * 1000),
                    error=type(exc).__name__,
                ),
                paths,
            )
        raise
    finally:
        if owned_conn is not None:
            owned_conn.close()
    finished = datetime.now(UTC)
    persist_run_log(
        RunLog(
            action=ACTION,
            status="success",
            started_at=started,
            finished_at=finished,
            elapsed_ms=int((finished - started).total_seconds() * 1000),
            input_digest=digest_json({"latest_data_id": result.latest_data_id, "due": result.due}),
            output_digest=result.output_digest,
            row_count=result.row_count,
            dml_count=result.dml_count,
        ),
        paths,
    )
    return result


def _store_conn(store: SrcWriteStore | None) -> psycopg.Connection:
    """取写入 store 底层的 psycopg 连接做只读水位查询，与写入同事务。

    ingest 不直接拼连接串（platform 的职责），但写库 store 已持有一条连接；
    水位读取必须和写入同一事务，才能保证"读到的最新行"与本次写入不冲突。这里只 SELECT。
    """
    conn = getattr(store, "_conn", None) if store is not None else None
    if conn is None:
        raise IngestError("无法取得水位读取的连接")
    return cast("psycopg.Connection", conn)


def _run(
    *,
    settings: Settings,
    write_db: bool,
    store: SrcWriteStore | None,
    query_conn: psycopg.Connection,
    fetch_detail: Callable[[int], Jin10IsmDetail],
    fetch_raw: Callable[[int], dict[str, object]],
    clock: Callable[[], datetime],
    max_scan: int,
    revision_lookback: int,
) -> Jin10IsmScanResult:
    current = clock().astimezone(UTC)

    # 1) 水位：最近几期按发布日排序的 data_id、最新发布日的 data_id、全库最大 data_id。
    recent_ids, latest_release_id, max_id = _query_watermark(
        query_conn, limit=max(revision_lookback, 1)
    )
    if not recent_ids or max_id <= 0:
        raise IngestError(
            "src_macro.jin10_economic_calendar 尚无 data_id > 0 的 ISM 行，无法自动发现。"
            "请先用 quantagent ingest macro jin10-ism-details --detail-id <ID> 回填至少一期"
        )
    if latest_release_id not in recent_ids:
        raise IngestError("库内水位不一致，拒绝继续")

    # 2) 复查最近几期（按发布日取最近 revision_lookback 期），捕获修订。
    #    发布日最新那一期的 next_public_time 决定是否扫描。
    details = [fetch_detail(event_id) for event_id in recent_ids]
    latest_detail = next(item for item in details if item.data_id == latest_release_id)
    next_public_at = latest_detail.next_public_at
    rows = [_row_of(item) for item in details]

    # 3) 是否到下一期发布日。next_public_at 为北京时间，统一转 UTC 比较。
    #    源端没给下一期时间时按未到期处理：不知何时该有新数据，无依据全扫会放大请求量。
    due = next_public_at is not None and current >= next_public_at.astimezone(UTC)

    # 4) 到期则扫描新事件。
    scan_start_id: int | None = None
    scanned = 0
    scan_high_water: int | None = None
    found: Jin10IsmDetail | None = None
    if due:
        # 起点是「上一期（发布日最新）」的下一 ID，不是全库最大 ID。
        # 实证下一期落在上一期之后的连排段内；用 max_id 反而会漏掉 ID 小于
        # 全库最大值的新事件（如 12-01 期 1179329 < 全库最大 1184254）。
        scan_start_id = latest_release_id + 1
        found, scanned, scan_high_water = scan_for_next_release(
            start_id=scan_start_id,
            max_scan=max_scan,
            fetch_raw=fetch_raw,
        )
        if found is None:
            raise IngestError(
                f"已到下一期发布日（next_public_time={next_public_at}），但自 data_id "
                f"{scan_start_id} 起扫描 {scanned} 个 ID 未找到新的 ISM 事件。"
                "可能源端排期结构变化或事件缺失，拒绝静默成功"
            )
        if found.data_id == latest_release_id:
            raise IngestError("扫描命中了上一期自身，扫描起点有误")
        if found.data_id in set(recent_ids):
            raise IngestError("扫描命中了已入库的历史事件，扫描起点或身份校验有误")
        rows.append(_row_of(found))

    # 5) 写入。window 用本次扫描的 ID 区间标识；未扫描时用扫描起点水位，便于追溯。
    high_water = scan_high_water if scan_high_water is not None else latest_release_id
    window_start = str(scan_start_id) if scan_start_id is not None else str(latest_release_id)
    write_result = write_src_follow(
        spec=JIN10_ECONOMIC_CALENDAR,
        rows=rows,
        settings=settings,
        write_db=write_db,
        store=store,
        window_start=window_start,
        window_end=str(high_water),
        source_cursor=str(high_water),
    )
    return Jin10IsmScanResult(
        dataset=write_result.dataset,
        written=write_result.written,
        latest_data_id=max_id,
        next_public_at=next_public_at,
        due=due,
        scan_attempted=scan_start_id is not None,
        scan_start_id=scan_start_id,
        scanned=scanned,
        found_data_id=None if found is None else found.data_id,
        found_publish_date=None if found is None else found.publish_date.isoformat(),
        rechecked=len(details),
        row_count=write_result.row_count,
        inserted=write_result.inserted,
        replaced=write_result.replaced,
        skipped=write_result.skipped,
        metadata_skipped=write_result.metadata_skipped,
        dml_count=write_result.dml_count,
        payload_digest=write_result.payload_digest,
        output_digest=write_result.output_digest,
    )

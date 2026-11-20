"""从契约 YAML 生成源表列注释（``COMMENT ON COLUMN``）。

契约 YAML 的 ``columns.<名>.description`` 是字段中文说明的唯一来源。这里把它翻译成
PostgreSQL 注释语句，再由 ``quantagent contracts emit-comments`` 写成迁移文件。

为什么放在 ingest 层：目标表与 schema 取自 ``ALLOWED_SRC_WRITE_TARGETS``，这份白名单
在本层。contracts 位于 ingest 之下，不能反向导入，所以生成逻辑放在这里。

生成结果只依赖输入：同一份契约得到同一段 SQL，迁移防漂移测试据此比对。
"""

from __future__ import annotations

from dataclasses import dataclass

from quantagent.contracts.loader import ContractBundle, load_bundle
from quantagent.ingest.writers.tables import ALLOWED_SRC_WRITE_TARGETS

# 写入迁移文件开头的说明。SQL 解析器会忽略以 -- 开头的整行注释。
HEADER_LINES: tuple[str, ...] = (
    "-- 本文件由 `quantagent contracts emit-comments` 从契约 YAML 生成，勿手改。",
    "-- 字段说明的唯一来源是 src/quantagent/contracts/schemas/pg/src.*.yaml 的 columns.<名>.description。",
    "-- COMMENT ON 只取轻量锁，不阻塞写入。",
)


class ColumnCommentError(Exception):
    """契约无法安全地翻译成列注释。停止生成，不猜测目标表。"""


@dataclass(frozen=True)
class ColumnComment:
    pg_schema: str
    pg_table: str
    column: str
    description: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.pg_schema, self.pg_table, self.column)


def build_column_comments(bundle: ContractBundle | None = None) -> tuple[ColumnComment, ...]:
    """返回所有非空列说明，按 (schema, 表, 契约中列的位置) 排序。

    只处理 ``layer: pg`` 且 dataset 以 ``src.`` 开头的契约。其中 dataset 必须登记在写入
    白名单里：白名单才知道它落在哪张物理表。不在白名单的 dataset 直接报错，不按名字猜。
    """
    loaded = bundle if bundle is not None else load_bundle()
    rows: list[tuple[str, str, int, ColumnComment]] = []
    seen: set[tuple[str, str, str]] = set()
    for dataset, schema in loaded.schemas.items():
        if schema.layer != "pg" or not dataset.startswith("src."):
            continue
        spec = ALLOWED_SRC_WRITE_TARGETS.get(dataset)
        if spec is None:
            raise ColumnCommentError(
                f"契约 {dataset} 不在写入白名单 ALLOWED_SRC_WRITE_TARGETS，无法确定物理表"
            )
        for position, (column, column_spec) in enumerate(schema.columns.items()):
            if not column_spec.description.strip():
                continue
            _assert_safe_identifier(spec.pg_schema, spec.pg_table, column)
            _assert_single_line(column_spec.description, dataset=dataset, column=column)
            comment = ColumnComment(
                pg_schema=spec.pg_schema,
                pg_table=spec.pg_table,
                column=column,
                description=column_spec.description,
            )
            if comment.key in seen:
                raise ColumnCommentError(f"列注释重复: {'.'.join(comment.key)}")
            seen.add(comment.key)
            rows.append((spec.pg_schema, spec.pg_table, position, comment))
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    return tuple(row[3] for row in rows)


def render_comment_sql(comments: tuple[ColumnComment, ...]) -> str:
    """渲染为迁移文件内容：开头说明，之后每列一条 ``COMMENT ON COLUMN``。"""
    lines = [*HEADER_LINES, ""]
    for comment in comments:
        target = f'{comment.pg_schema}."{comment.pg_table}"."{comment.column}"'
        lines.append(f"COMMENT ON COLUMN {target} IS {_sql_string(comment.description)};")
    return "\n".join(lines) + "\n"


def _sql_string(text: str) -> str:
    """单引号字符串字面量。SQL 规则：内部单引号加倍。"""
    return "'" + text.replace("'", "''") + "'"


def _assert_safe_identifier(pg_schema: str, pg_table: str, column: str) -> None:
    # 标识符直接放进双引号。出现双引号会破坏语句，这种名字不应存在，所以拒绝。
    for name in (pg_table, column):
        if '"' in name:
            raise ColumnCommentError(f"标识符含双引号，无法安全生成: {pg_schema}.{name}")


def _assert_single_line(description: str, *, dataset: str, column: str) -> None:
    # 迁移按行解析（整行 -- 注释会被丢弃），说明里的换行会让语句被截断。
    if "\n" in description or "\r" in description:
        raise ColumnCommentError(f"{dataset}.{column} 的 description 含换行，不能生成注释")

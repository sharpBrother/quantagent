"""双面独立的前向迁移。

``db/migrations/src/`` 与 ``db/migrations/ops/`` 各一条序列，互不混用。
登记表 ``qa_migrate.applied`` 由运行器创建，不进编号 SQL——两条序列都要
用它，且它必须能幂等存在。

迁移 SQL 只允许 ``CREATE`` / ``COMMENT``。ingest 的 insert-only 动词白名单
管的是数据写入；这里管的是结构演进，禁止 ``DROP`` / ``ALTER`` / 任何 DML。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from quantagent.adapters.postgres.errors import MigrationError
from quantagent.platform.config.write_gate import assert_db_write_allowed
from quantagent.platform.identity import digest_file, digest_json
from quantagent.platform.pg import connect, plane_configured
from quantagent.platform.runlog import RunLog, persist_run_log
from quantagent.platform.storage import resolve_var_paths

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import psycopg

    from quantagent.platform.config.settings import Settings
    from quantagent.platform.storage.paths import VarPaths

Plane = Literal["src", "ops"]
PLANES: tuple[Plane, ...] = ("src", "ops")
ALLOWED_LEADING = frozenset({"CREATE", "COMMENT"})
_FORBIDDEN = re.compile(
    r"\b(?:DROP|ALTER|TRUNCATE|UPDATE|MERGE|DELETE|INSERT|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
# 外键动作不是 DML。Dagster 的 run_tags 使用 ON DELETE CASCADE。
_FK_ACTION = re.compile(r"\bON\s+(?:DELETE|UPDATE)\b", re.IGNORECASE)
_DROP_TABLE = re.compile(
    r'^DROP TABLE\s+((?:[A-Za-z_][\w]*\.)?"[^"]+")\s*$',
    re.IGNORECASE,
)
_CREATE_TABLE = re.compile(
    r'^CREATE TABLE\s+((?:[A-Za-z_][\w]*\.)?"[^"]+")',
    re.IGNORECASE,
)
_CREATE_VIEW = re.compile(
    r'^CREATE VIEW\s+((?:[A-Za-z_][\w]*\.)?"[^"]+")\s+AS\b',
    re.IGNORECASE,
)
_FILENAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
# COMMENT 只放行列注释：说明文字来自契约 YAML，由 contracts emit-comments 生成。
# 表注释、库注释等其他形式一律拒绝。
_COMMENT_COLUMN = re.compile(
    r"COMMENT ON COLUMN \w+\.\"[^\"]+\"\.\"[^\"]+\" IS '(?:[^']|'')*'",
    re.IGNORECASE,
)
# 删表且不在同文件重建的历史例外，文件与表名写死。0018 按分表原则删除三张空的旧宏观表，
# 必须位于文件开头。应用时 _refuse_nonempty_drop 仍会检查行数，非空则拒绝。
_DROP_WITHOUT_REBUILD: dict[str, frozenset[str]] = {
    "0018_macro_source_tables.sql": frozenset(
        {
            'src_macro."macro_jin10_usa_ism_pmi"',
            'src_macro."macro_gpr_daily"',
            'src_macro."macro_fred_observation"',
        }
    ),
}

# 空表删表重建白名单：文件名 -> 允许重建的表。与 _DROP_WITHOUT_REBUILD 不同，这里要求
# 每条 DROP 紧跟同名 CREATE，且表集合与白名单完全一致，防止在别的语句之后夹带删表。
# 只登记已确认 0 行的迁移；其他文件仍按上面的同文件重建规则。
_REBUILD_PAIRS: dict[str, frozenset[str]] = {
    "0019_bond_fx_wind_tables.sql": frozenset(
        {
            'src_wind."CBONDCURVECNBD"',
            'src_wind."CBONDCURVECSI"',
            'src_wind."CBONDREPOANDIBLEODPRICES"',
            'src_wind."CBONDPRICESREPO"',
            'src_wind."CBONDREPO"',
            'src_wind."FXEODPRICES"',
        }
    ),
    "0033_qt_osindexquote.sql": frozenset({'src_jydb."QT_OSIndexQuote"'}),
}
# 删物理表并在同一文件建同名视图的白名单。视图只做筛选、不存数据，与重建表的规则不同：
# 不要求 _batch_id 索引，但仍要求每条 DROP 紧跟同名 CREATE VIEW，且表集合与白名单完全一致。
# 只登记 0020 的一处：AINDEXINDUSTRIESCITICS 由 AINDEXDESCRIPTION 按中信成分筛出（2026-11-19 裁定）。
_DROP_TO_VIEW_PAIRS: dict[str, frozenset[str]] = {
    "0020_aindexdescription.sql": frozenset({'src_wind."AINDEXINDUSTRIESCITICS"'}),
}
CATALOG_SCHEMA_SQL = "CREATE SCHEMA IF NOT EXISTS qa_migrate"
CATALOG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS qa_migrate.applied (
    plane text NOT NULL,
    filename text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (plane, filename)
)
"""


@dataclass(frozen=True)
class MigrationFile:
    plane: Plane
    filename: str
    path: Path
    checksum: str


@dataclass(frozen=True)
class PlaneReport:
    plane: Plane
    applied: tuple[str, ...]
    pending: tuple[str, ...]
    applied_now: tuple[str, ...]
    statement_count: int


def migrations_root(repo_root: Path) -> Path:
    path = repo_root / "db" / "migrations"
    if not path.is_dir():
        raise MigrationError(f"找不到迁移目录: {path}")
    return path


def list_migration_files(repo_root: Path, plane: Plane) -> tuple[MigrationFile, ...]:
    directory = migrations_root(repo_root) / plane
    if not directory.is_dir():
        raise MigrationError(f"找不到 {plane} 迁移目录: {directory}")
    files: list[MigrationFile] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"迁移文件名非法: {path.name}（需要 NNNN_name.sql）")
        files.append(
            MigrationFile(
                plane=plane,
                filename=path.name,
                path=path,
                checksum=digest_file(path),
            )
        )
    numbers = [path.filename[:4] for path in files]
    if numbers != sorted(numbers):
        raise MigrationError(f"{plane} 迁移序号未按字典序排列")
    if len(set(numbers)) != len(numbers):
        raise MigrationError(f"{plane} 迁移序号重复")
    if not files:
        raise MigrationError(f"{plane} 迁移目录为空")
    for item in files:
        assert_migration_sql(item.path.read_text(encoding="utf-8"), filename=item.filename)
    return tuple(files)


def split_sql_statements(sql: str) -> tuple[str, ...]:
    """按分号切语句。分号若在双引号标识符或单引号字面量里则不切。

    单引号也要识别：列注释的 description 是字面量，里面的 ``;`` 与 ``"`` 不能把语句切坏。
    ``''`` 转义会让引号状态翻转两次，状态保持正确。
    """
    body_lines: list[str] = []
    for raw in sql.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("--"):
            continue
        body_lines.append(raw)
    body = "\n".join(body_lines)
    parts: list[str] = []
    buf: list[str] = []
    in_ident = False
    in_literal = False
    for char in body:
        if char == "'" and not in_ident:
            in_literal = not in_literal
        elif char == '"' and not in_literal:
            in_ident = not in_ident
        elif char == ";" and not in_ident and not in_literal:
            statement = "".join(buf).strip()
            if statement:
                parts.append(statement)
            buf = []
            continue
        buf.append(char)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return tuple(parts)


def assert_migration_sql(sql: str, *, filename: str) -> tuple[str, ...]:
    statements = split_sql_statements(sql)
    if not statements:
        raise MigrationError(f"{filename} 没有可执行语句")
    created = {
        match.group(1)
        for statement in statements
        if (match := _CREATE_TABLE.match(statement)) is not None
    }
    exempt = _DROP_WITHOUT_REBUILD.get(filename, frozenset())
    rebuild_allowed = _REBUILD_PAIRS.get(filename)
    view_allowed = _DROP_TO_VIEW_PAIRS.get(filename)
    rebuilt: set[str] = set()
    replaced_by_view: set[str] = set()
    exempt_dropped: set[str] = set()
    seen_non_drop = False
    for pos, statement in enumerate(statements):
        dropped = _DROP_TABLE.match(statement)
        if dropped is not None:
            # 已应用的迁移文件不能改。空表列与源端不一致时，只允许删掉这张表并在同一文件里建回。
            name = dropped.group(1)
            if view_allowed is not None:
                if name not in view_allowed or not _followed_by_same(
                    statements, pos, name, _CREATE_VIEW
                ):
                    raise MigrationError(
                        f"{filename} 的删表改视图不在白名单或未紧跟同名 CREATE VIEW: {name}"
                    )
                replaced_by_view.add(name)
                continue
            if rebuild_allowed is not None:
                if name not in rebuild_allowed or not _followed_by_same(
                    statements, pos, name, _CREATE_TABLE
                ):
                    raise MigrationError(
                        f"{filename} 的删表重建不在白名单或未紧跟同名 CREATE: {name}"
                    )
                rebuilt.add(name)
                continue
            if name in created:
                continue
            if name in exempt and not seen_non_drop:
                exempt_dropped.add(name)
                continue
            raise MigrationError(f"{filename} 删除的表没有在同一文件重建: {name}")
        seen_non_drop = True
        leading = _leading_keyword(statement)
        if leading not in ALLOWED_LEADING:
            raise MigrationError(f"{filename} 语句动词非法: {leading}")
        _assert_comment_form(statement, leading=leading, filename=filename)
        if _FORBIDDEN.search(_FK_ACTION.sub(" ", statement)):
            raise MigrationError(f"{filename} 含禁止动词: {statement[:80]}")
    if exempt_dropped != exempt:
        raise MigrationError(f"{filename} 的开头删表与白名单不一致")
    _assert_replacements_complete(filename, rebuilt, replaced_by_view)
    return statements


def _assert_comment_form(statement: str, *, leading: str, filename: str) -> None:
    """COMMENT 只允许列注释的完整形式，其他 COMMENT 形式一律拒绝。"""
    if leading == "COMMENT" and _COMMENT_COLUMN.fullmatch(statement) is None:
        raise MigrationError(f"{filename} 只允许 COMMENT ON COLUMN: {statement[:80]}")


def _assert_replacements_complete(
    filename: str, rebuilt: set[str], replaced_by_view: set[str]
) -> None:
    """白名单中登记的每张表都必须被删除并在同文件重建或改视图，不多不少。"""
    if rebuilt != _REBUILD_PAIRS.get(filename, frozenset()):
        raise MigrationError(f"{filename} 的删表重建与白名单不一致")
    if replaced_by_view != _DROP_TO_VIEW_PAIRS.get(filename, frozenset()):
        raise MigrationError(f"{filename} 的删表改视图与白名单不一致")


def _followed_by_same(
    statements: Sequence[str], pos: int, name: str, pattern: re.Pattern[str]
) -> bool:
    """第 pos 条 DROP 之后紧跟的语句是否是同名 CREATE（由 pattern 限定是 TABLE 还是 VIEW）。"""
    if pos + 1 >= len(statements):
        return False
    following = pattern.match(statements[pos + 1])
    return following is not None and following.group(1) == name


def resolve_planes(raw: str) -> tuple[Plane, ...]:
    text = raw.strip().lower()
    if text == "all":
        return PLANES
    if text in PLANES:
        return (text,)
    raise MigrationError("plane 只允许 src、ops 或 all")


def collect_status(
    *,
    settings: Settings,
    repo_root: Path,
    planes: Sequence[Plane] | None = None,
) -> tuple[PlaneReport, ...]:
    selected = tuple(planes) if planes is not None else PLANES
    reports: list[PlaneReport] = []
    for plane in selected:
        files = list_migration_files(repo_root, plane)
        if not plane_configured(settings, plane):
            reports.append(
                PlaneReport(
                    plane=plane,
                    applied=(),
                    pending=tuple(item.filename for item in files),
                    applied_now=(),
                    statement_count=0,
                )
            )
            continue
        with connect(settings, plane) as conn:
            applied_map = _load_applied(conn, plane)
            _assert_checksums(files, applied_map)
            pending = tuple(item.filename for item in files if item.filename not in applied_map)
            reports.append(
                PlaneReport(
                    plane=plane,
                    applied=tuple(item.filename for item in files if item.filename in applied_map),
                    pending=pending,
                    applied_now=(),
                    statement_count=0,
                )
            )
    return tuple(reports)


def apply_migrations(
    *,
    settings: Settings,
    repo_root: Path,
    planes: Sequence[Plane],
    write_db: bool,
    var_paths: VarPaths | None = None,
) -> tuple[PlaneReport, ...]:
    files_by_plane = {plane: list_migration_files(repo_root, plane) for plane in planes}
    for plane in planes:
        if not plane_configured(settings, plane):
            label = "研究数据面" if plane == "src" else "控制状态面"
            raise MigrationError(f"PostgreSQL {label}未配置，无法 migrate")
    if write_db:
        assert_db_write_allowed(settings=settings, write_db=True)
    reports: list[PlaneReport] = []
    for plane in planes:
        files = files_by_plane[plane]
        with connect(settings, plane) as conn:
            reports.append(_apply_plane(conn, plane=plane, files=files, write_db=write_db))
    if write_db:
        _write_run_log(
            settings=settings,
            repo_root=repo_root,
            reports=tuple(reports),
            var_paths=var_paths,
        )
    return tuple(reports)


def _apply_plane(
    conn: psycopg.Connection[Any],
    *,
    plane: Plane,
    files: tuple[MigrationFile, ...],
    write_db: bool,
) -> PlaneReport:
    if write_db:
        _ensure_catalog(conn)
    applied_map = _load_applied(conn, plane)
    _assert_checksums(files, applied_map)
    pending = [item for item in files if item.filename not in applied_map]
    applied_now: list[str] = []
    statement_count = 0
    if write_db:
        for item in pending:
            statements = assert_migration_sql(
                item.path.read_text(encoding="utf-8"),
                filename=item.filename,
            )
            with conn.transaction():
                for statement in statements:
                    _refuse_nonempty_drop(conn, statement)
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO qa_migrate.applied (plane, filename, checksum) "
                    "VALUES (%s, %s, %s)",
                    (plane, item.filename, item.checksum),
                )
            applied_now.append(item.filename)
            statement_count += len(statements)
        still_pending: tuple[str, ...] = ()
        now_applied = tuple(item.filename for item in files)
    else:
        still_pending = tuple(item.filename for item in pending)
        now_applied = tuple(item.filename for item in files if item.filename in applied_map)
    return PlaneReport(
        plane=plane,
        applied=now_applied,
        pending=still_pending,
        applied_now=tuple(applied_now),
        statement_count=statement_count,
    )


def _refuse_nonempty_drop(conn: psycopg.Connection[Any], statement: str) -> None:
    dropped = _DROP_TABLE.match(statement)
    if dropped is None:
        return
    qualified = dropped.group(1)
    schema, table = qualified.split(".", 1)
    table_name = table.strip('"')
    exists = conn.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table_name),
    ).fetchone()
    if exists is None:
        return
    count = conn.execute(f"SELECT count(*) FROM {qualified}").fetchone()
    if count is not None and int(count[0]) > 0:
        raise MigrationError(f"拒绝删除非空表: {qualified} rows={count[0]}")


def _ensure_catalog(conn: psycopg.Connection[Any]) -> None:
    with conn.transaction():
        conn.execute(CATALOG_SCHEMA_SQL)
        conn.execute(CATALOG_TABLE_SQL)


def _load_applied(conn: psycopg.Connection[Any], plane: Plane) -> dict[str, str]:
    exists = conn.execute(
        "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'qa_migrate'"
    ).fetchone()
    if exists is None:
        return {}
    rows = conn.execute(
        "SELECT filename, checksum FROM qa_migrate.applied WHERE plane = %s",
        (plane,),
    ).fetchall()
    return {str(filename): str(checksum) for filename, checksum in rows}


def _assert_checksums(files: tuple[MigrationFile, ...], applied: dict[str, str]) -> None:
    by_name = {item.filename: item for item in files}
    for filename, checksum in applied.items():
        item = by_name.get(filename)
        if item is None:
            raise MigrationError(f"catalog 中有磁盘上不存在的迁移: {filename}")
        if item.checksum != checksum:
            raise MigrationError(
                f"已应用的迁移文件被改动，拒绝继续: {filename} "
                f"catalog={checksum} disk={item.checksum}"
            )


def _leading_keyword(statement: str) -> str:
    token = statement.split(None, 1)[0]
    return token.upper()


def _write_run_log(
    *,
    settings: Settings,
    repo_root: Path,
    reports: tuple[PlaneReport, ...],
    var_paths: VarPaths | None,
) -> None:
    paths = var_paths if var_paths is not None else resolve_var_paths(settings, repo_root=repo_root)
    finished = datetime.now(UTC)
    payload = [
        {
            "plane": report.plane,
            "applied_now": list(report.applied_now),
            "applied": list(report.applied),
        }
        for report in reports
    ]
    dml_count = sum(report.statement_count for report in reports)
    record = RunLog(
        action="db.migrate",
        status="success",
        finished_at=finished,
        elapsed_ms=0,
        input_digest=digest_json(payload),
        output_digest=digest_json({"dml_count": dml_count}),
        row_count=0,
        dml_count=dml_count,
    )
    persist_run_log(record, paths)

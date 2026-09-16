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
_FILENAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

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
    """按分号切语句。生成的 SQL 不含字符串字面量里的分号。"""
    body_lines: list[str] = []
    for raw in sql.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("--"):
            continue
        body_lines.append(raw)
    body = "\n".join(body_lines)
    parts: list[str] = []
    buf: list[str] = []
    in_quote = False
    for char in body:
        if char == '"':
            in_quote = not in_quote
            buf.append(char)
            continue
        if char == ";" and not in_quote:
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
    for statement in statements:
        leading = _leading_keyword(statement)
        if leading not in ALLOWED_LEADING:
            raise MigrationError(f"{filename} 语句动词非法: {leading}")
        if _FORBIDDEN.search(statement):
            raise MigrationError(f"{filename} 含禁止动词: {statement[:80]}")
    return statements


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

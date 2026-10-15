"""旧库迁移测试：给"已存在旧表结构的库"补列与补索引。

为什么单独测这一条路径：CI 里 MySQL 那一轮用的是空库，``CREATE TABLE IF NOT EXISTS``
会直接把新结构建出来，迁移里的 ``ALTER TABLE`` 全部走"列已存在"的跳过分支，
真正的 ``ADD COLUMN`` 一次都没执行过。而线上部署时表是旧的，走的就是这条路径，
所以必须显式构造旧结构再跑一次迁移，否则部署时的失败只能等上线才知道。
"""
import sqlite3
import re

import pytest

import database
from database import get_conn

LEGACY_USER_ID = 778877
LEGACY_TITLE = "legacy-document"

NEW_DOCUMENT_COLUMNS = {"project_id", "rel_path", "line_count", "structure_json"}
NEW_CHUNK_COLUMNS = {"project_id", "rel_path", "language", "symbol_name", "start_line", "end_line"}

_ADD_COLUMN_RE = re.compile(r"ALTER TABLE (\w+) ADD COLUMN (\w+)")


def _added_columns(statements) -> set:
    return {match.groups() for match in (_ADD_COLUMN_RE.match(s) for s in statements) if match}


def _schema_columns(schema, table: str) -> set:
    """从建表 DDL 里提取列名（供静态一致性检查用）。"""
    for ddl in schema:
        marker = f"CREATE TABLE IF NOT EXISTS {table}"
        if marker not in ddl:
            continue
        body = ddl.split(marker, 1)[1].split("\n    )")[0]
        return set(re.findall(r"^\s*([a-z_]+)\s+[A-Z]", body, re.M))
    return set()


def test_migration_columns_are_defined_in_schema():
    """迁移里 ADD 的列必须真的建表 DDL 里存在，否则说明两处漂移了。"""
    for statements, schema in (
        (database._MYSQL_MIGRATIONS, database._MYSQL_SCHEMA),
        (database._SQLITE_MIGRATIONS, database._MYSQL_SCHEMA),
    ):
        for table, column in _added_columns(statements):
            assert column in _schema_columns(schema, table), f"{table}.{column} 未在建表 DDL 中定义"


def test_both_drivers_migrate_the_same_columns():
    """SQLite 与 MySQL 的增量列必须保持一致，避免只在一种驱动上补了列。"""
    assert _added_columns(database._MYSQL_MIGRATIONS) == _added_columns(database._SQLITE_MIGRATIONS)


@pytest.fixture
def tmp_path():
    """独立的本地临时目录。

    pytest 内置的同名夹具会扫描系统临时目录下的 ``pytest-of-*``，在受限环境里可能被拒；
    这里直接创建并自行清理，语义相同但不依赖环境目录权限。
    """
    import shutil
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp(prefix="codemind-migration-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


_SQLITE_LEGACY_SCHEMA = """
CREATE TABLE rag_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    language TEXT NOT NULL DEFAULT 'text',
    char_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_rag_documents_user ON rag_documents(user_id);
CREATE TABLE rag_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_rag_chunks_user ON rag_chunks(user_id);
"""


def test_sqlite_legacy_database_gains_project_columns(tmp_path, monkeypatch):
    if database.DB_DRIVER != "sqlite":
        pytest.skip("仅在 SQLite 驱动下运行")

    legacy_db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(legacy_db))
    try:
        conn.executescript(_SQLITE_LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO rag_documents(user_id,title,source,language,char_count,chunk_count,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (LEGACY_USER_ID, LEGACY_TITLE, "manual", "text", 12, 1, "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO rag_chunks(document_id,user_id,chunk_index,content,embedding_json,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (1, LEGACY_USER_ID, 0, "legacy chunk", "[0.1, 0.2]", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    # 把连接指向"旧库"，跑真实的初始化入口
    monkeypatch.setattr(database, "DB_PATH", legacy_db)
    database.init_db()

    conn = sqlite3.connect(str(legacy_db))
    conn.row_factory = sqlite3.Row
    try:
        document_columns = {row["name"] for row in conn.execute("PRAGMA table_info(rag_documents)")}
        chunk_columns = {row["name"] for row in conn.execute("PRAGMA table_info(rag_chunks)")}
        assert NEW_DOCUMENT_COLUMNS <= document_columns
        assert NEW_CHUNK_COLUMNS <= chunk_columns

        # 新表也要建出来
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='projects'"
        ).fetchone()[0] == 1

        # 新列上的索引必须建上（否则项目过滤会退化成全表扫描）
        indexes = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_rag_%_project'"
            )
        }
        assert indexes == {"idx_rag_documents_project", "idx_rag_chunks_project"}

        # 旧数据不能丢，新列取到默认值
        document = conn.execute(
            "SELECT title, project_id, rel_path, line_count, structure_json FROM rag_documents WHERE user_id=?",
            (LEGACY_USER_ID,),
        ).fetchone()
        assert document["title"] == LEGACY_TITLE
        assert document["project_id"] is None
        assert document["rel_path"] is None
        assert document["line_count"] == 0
        assert document["structure_json"] is None

        chunk = conn.execute(
            "SELECT content, project_id, language, start_line FROM rag_chunks WHERE user_id=?",
            (LEGACY_USER_ID,),
        ).fetchone()
        assert chunk["content"] == "legacy chunk"
        assert chunk["project_id"] is None
        assert chunk["language"] == ""
        assert chunk["start_line"] == 0
    finally:
        conn.close()


def test_sqlite_migration_is_idempotent(tmp_path, monkeypatch):
    """重复执行迁移不应报错（每次启动都会跑一遍）。"""
    if database.DB_DRIVER != "sqlite":
        pytest.skip("仅在 SQLite 驱动下运行")

    legacy_db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(legacy_db))
    try:
        conn.executescript(_SQLITE_LEGACY_SCHEMA)
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(database, "DB_PATH", legacy_db)
    database.init_db()
    database.init_db()

    conn = sqlite3.connect(str(legacy_db))
    try:
        document_columns = {row[1] for row in conn.execute("PRAGMA table_info(rag_documents)")}
        assert NEW_DOCUMENT_COLUMNS <= document_columns
    finally:
        conn.close()


_MYSQL_DOWNGRADE_STATEMENTS = [
    "ALTER TABLE rag_documents DROP COLUMN project_id",
    "ALTER TABLE rag_documents DROP COLUMN rel_path",
    "ALTER TABLE rag_documents DROP COLUMN line_count",
    "ALTER TABLE rag_documents DROP COLUMN structure_json",
    "ALTER TABLE rag_chunks DROP COLUMN project_id",
    "ALTER TABLE rag_chunks DROP COLUMN rel_path",
    "ALTER TABLE rag_chunks DROP COLUMN language",
    "ALTER TABLE rag_chunks DROP COLUMN symbol_name",
    "ALTER TABLE rag_chunks DROP COLUMN start_line",
    "ALTER TABLE rag_chunks DROP COLUMN end_line",
    "DROP TABLE projects",
]


def test_mysql_legacy_database_gains_project_columns():
    """把表退回旧结构后再跑迁移，验证真正的 ADD COLUMN 与 CREATE INDEX 能执行成功。

    CI 的 MySQL 轮次才会执行本用例；SQLite 轮次自动跳过。
    """
    if database.DB_DRIVER != "mysql":
        pytest.skip("仅在 MySQL 驱动下运行")

    conn = get_conn()
    try:
        for statement in _MYSQL_DOWNGRADE_STATEMENTS:
            conn.execute(statement)
        conn.commit()
        conn.execute(
            "INSERT INTO rag_documents(user_id,title,source,language,char_count,chunk_count,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (LEGACY_USER_ID, LEGACY_TITLE, "manual", "text", 12, 1, "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        database._init_mysql()

        conn = get_conn()
        try:
            document_columns = {row["Field"] for row in conn.execute("SHOW COLUMNS FROM rag_documents")}
            chunk_columns = {row["Field"] for row in conn.execute("SHOW COLUMNS FROM rag_chunks")}
            assert NEW_DOCUMENT_COLUMNS <= document_columns
            assert NEW_CHUNK_COLUMNS <= chunk_columns

            document_indexes = {row["Key_name"] for row in conn.execute("SHOW INDEX FROM rag_documents")}
            chunk_indexes = {row["Key_name"] for row in conn.execute("SHOW INDEX FROM rag_chunks")}
            assert "idx_rag_documents_project" in document_indexes
            assert "idx_rag_chunks_project" in chunk_indexes

            document = conn.execute(
                "SELECT title, project_id, line_count FROM rag_documents WHERE user_id=?",
                (LEGACY_USER_ID,),
            ).fetchone()
            assert document["title"] == LEGACY_TITLE
            assert document["project_id"] is None
            assert document["line_count"] == 0

            # projects 表由迁移重建
            assert conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()["c"] >= 0
        finally:
            conn.close()
    finally:
        # 无论断言是否通过，都再跑一次迁移把表结构恢复完整，
        # 避免用例失败后把共享库留在"缺列"状态、让后续用例报出迷惑性的错误
        try:
            database._init_mysql()
        except Exception:
            pass
        conn = get_conn()
        try:
            conn.execute("DELETE FROM rag_documents WHERE user_id=?", (LEGACY_USER_ID,))
            conn.commit()
        finally:
            conn.close()

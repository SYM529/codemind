"""Database layer.

Two interchangeable drivers selected by DB_DRIVER:
- sqlite (default): zero-config local file database, used for local dev and tests
- mysql: PyMySQL with a connection pool, used in production (Docker / 云服务器)

All business code goes through get_conn() and keeps the sqlite3 call style
(conn.execute / conn.commit / conn.close, rows readable by column name);
the MySQL wrapper translates the few dialect differences so call sites
stay driver-agnostic.
"""
import json
import os
import re
from pathlib import Path

DB_DRIVER = os.getenv("DB_DRIVER", "sqlite").strip().lower()

DB_DIR = Path(__file__).parent / "data"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.getenv("APP_DB_PATH", str(DB_DIR / "app.sqlite")))

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "codemind")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "codemind")

_mysql_pool = None


class _CursorWrap:
    """Exposes the cursor attributes business code relies on."""

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return self._cur.lastrowid


class MySQLConn:
    """sqlite3-style facade over a pooled PyMySQL connection.

    Translates dialect differences:
    - ``?`` placeholders -> ``%s``
    - ``INSERT OR IGNORE`` -> ``INSERT IGNORE``
    - ``INSERT OR REPLACE`` -> ``REPLACE INTO``
    """

    def __init__(self, raw_conn):
        self._conn = raw_conn

    @staticmethod
    def _translate(sql: str) -> str:
        s = sql.strip()
        if re.match(r"(?i)^INSERT\s+OR\s+IGNORE\b", s):
            s = re.sub(r"(?i)^INSERT\s+OR\s+IGNORE(\s+INTO\b)?", "INSERT IGNORE INTO", s, count=1)
        elif re.match(r"(?i)^INSERT\s+OR\s+REPLACE\b", s):
            s = re.sub(r"(?i)^INSERT\s+OR\s+REPLACE(\s+INTO\b)?", "REPLACE INTO", s, count=1)
        return s.replace("?", "%s")

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(self._translate(sql), tuple(params))
        return _CursorWrap(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        # PooledDB: close() returns the connection to the pool
        self._conn.close()


def _get_mysql_pool():
    global _mysql_pool
    if _mysql_pool is None:
        import pymysql
        from dbutils.pooled_db import PooledDB

        _mysql_pool = PooledDB(
            creator=pymysql,
            maxconnections=10,
            blocking=True,
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )
    return _mysql_pool


def get_conn():
    if DB_DRIVER == "mysql":
        return MySQLConn(_get_mysql_pool().connection())
    import sqlite3

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_MYSQL_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS generations (
        generation_id VARCHAR(64) PRIMARY KEY,
        user_id BIGINT NULL,
        language VARCHAR(32) NOT NULL,
        task VARCHAR(32) NOT NULL,
        style VARCHAR(32) NOT NULL,
        code MEDIUMTEXT NOT NULL,
        summary MEDIUMTEXT NOT NULL,
        comments_json LONGTEXT NOT NULL,
        risks_json LONGTEXT NOT NULL,
        suggestions_json LONGTEXT NOT NULL,
        debug_json LONGTEXT NOT NULL,
        created_at VARCHAR(40) NOT NULL,
        INDEX idx_generations_user (user_id),
        INDEX idx_generations_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS usage_records (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        user_id BIGINT NULL,
        generation_id VARCHAR(64) NOT NULL,
        model VARCHAR(64) NOT NULL,
        estimated_input_tokens BIGINT NOT NULL,
        estimated_output_tokens BIGINT NOT NULL,
        estimated_cost_usd DOUBLE NOT NULL,
        token_source VARCHAR(16) NOT NULL DEFAULT 'unknown',
        created_at VARCHAR(40) NOT NULL,
        INDEX idx_usage_user (user_id),
        INDEX idx_usage_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS feedback (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        user_id BIGINT NULL,
        generation_id VARCHAR(64) NOT NULL,
        rating VARCHAR(16) NOT NULL,
        comment MEDIUMTEXT NOT NULL,
        created_at VARCHAR(40) NOT NULL,
        INDEX idx_feedback_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluations (
        generation_id VARCHAR(64) PRIMARY KEY,
        user_id BIGINT NULL,
        schema_valid INTEGER NOT NULL,
        function_count INTEGER NOT NULL,
        comment_count INTEGER NOT NULL,
        function_coverage DOUBLE NOT NULL,
        valid_line_rate DOUBLE NOT NULL,
        duration_ms BIGINT NOT NULL,
        created_at VARCHAR(40) NOT NULL,
        INDEX idx_evaluations_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        username VARCHAR(64) NOT NULL UNIQUE,
        email VARCHAR(128) NOT NULL UNIQUE,
        password_hash VARCHAR(128) NOT NULL,
        role VARCHAR(16) NOT NULL DEFAULT 'user',
        is_disabled TINYINT NOT NULL DEFAULT 0,
        created_at VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_documents (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        user_id BIGINT NOT NULL,
        title VARCHAR(255) NOT NULL,
        source VARCHAR(32) NOT NULL DEFAULT 'manual',
        language VARCHAR(32) NOT NULL DEFAULT 'text',
        char_count INTEGER NOT NULL DEFAULT 0,
        chunk_count INTEGER NOT NULL DEFAULT 0,
        project_id BIGINT NULL,
        rel_path VARCHAR(512) NULL,
        line_count INTEGER NOT NULL DEFAULT 0,
        structure_json LONGTEXT NULL,
        created_at VARCHAR(40) NOT NULL,
        INDEX idx_rag_documents_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_chunks (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        document_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL,
        chunk_index INTEGER NOT NULL,
        content MEDIUMTEXT NOT NULL,
        embedding_json LONGTEXT NOT NULL,
        project_id BIGINT NULL,
        rel_path VARCHAR(512) NULL,
        language VARCHAR(32) NOT NULL DEFAULT '',
        symbol_name VARCHAR(128) NULL,
        start_line INTEGER NOT NULL DEFAULT 0,
        end_line INTEGER NOT NULL DEFAULT 0,
        created_at VARCHAR(40) NOT NULL,
        INDEX idx_rag_chunks_user (user_id),
        INDEX idx_rag_chunks_document (document_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_cache (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        user_id BIGINT NOT NULL,
        signature LONGTEXT NOT NULL,
        embedding_json LONGTEXT NOT NULL,
        result_json LONGTEXT NOT NULL,
        hits INTEGER NOT NULL DEFAULT 0,
        created_at VARCHAR(40) NOT NULL,
        INDEX idx_ai_cache_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        public_id VARCHAR(32) NOT NULL UNIQUE,
        user_id BIGINT NOT NULL,
        name VARCHAR(128) NOT NULL,
        archive_name VARCHAR(255) NOT NULL DEFAULT '',
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        file_count INTEGER NOT NULL DEFAULT 0,
        indexed_file_count INTEGER NOT NULL DEFAULT 0,
        chunk_count INTEGER NOT NULL DEFAULT 0,
        total_bytes BIGINT NOT NULL DEFAULT 0,
        detail_json LONGTEXT NULL,
        error_message VARCHAR(512) NOT NULL DEFAULT '',
        created_at VARCHAR(40) NOT NULL,
        updated_at VARCHAR(40) NOT NULL,
        INDEX idx_projects_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

_MYSQL_TABLES = [
    "generations", "usage_records", "feedback", "evaluations",
    "users", "rag_documents", "rag_chunks", "ai_cache", "projects",
]

# 增量列迁移：MySQL 的 CREATE TABLE IF NOT EXISTS 不会给已存在的表补列，
# 因此必须显式 ALTER，否则线上库（表已存在）永远拿不到新列。
# 每条语句都允许失败（列已存在时报错），迁移是幂等的。
_MYSQL_MIGRATIONS = [
    "ALTER TABLE rag_documents ADD COLUMN project_id BIGINT NULL",
    "ALTER TABLE rag_documents ADD COLUMN rel_path VARCHAR(512) NULL",
    "ALTER TABLE rag_documents ADD COLUMN line_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE rag_documents ADD COLUMN structure_json LONGTEXT NULL",
    "ALTER TABLE rag_chunks ADD COLUMN project_id BIGINT NULL",
    "ALTER TABLE rag_chunks ADD COLUMN rel_path VARCHAR(512) NULL",
    "ALTER TABLE rag_chunks ADD COLUMN language VARCHAR(32) NOT NULL DEFAULT ''",
    "ALTER TABLE rag_chunks ADD COLUMN symbol_name VARCHAR(128) NULL",
    "ALTER TABLE rag_chunks ADD COLUMN start_line INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE rag_chunks ADD COLUMN end_line INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX idx_rag_documents_project ON rag_documents(project_id)",
    "CREATE INDEX idx_rag_chunks_project ON rag_chunks(project_id)",
]

# SQLite 侧同样的迁移（MySQL 不支持 ADD COLUMN IF NOT EXISTS，SQLite 侧统一走 try/except）
_SQLITE_MIGRATIONS = [
    "ALTER TABLE rag_documents ADD COLUMN project_id INTEGER",
    "ALTER TABLE rag_documents ADD COLUMN rel_path TEXT",
    "ALTER TABLE rag_documents ADD COLUMN line_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE rag_documents ADD COLUMN structure_json TEXT",
    "ALTER TABLE rag_chunks ADD COLUMN project_id INTEGER",
    "ALTER TABLE rag_chunks ADD COLUMN rel_path TEXT",
    "ALTER TABLE rag_chunks ADD COLUMN language TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE rag_chunks ADD COLUMN symbol_name TEXT",
    "ALTER TABLE rag_chunks ADD COLUMN start_line INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE rag_chunks ADD COLUMN end_line INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_rag_documents_project ON rag_documents(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_project ON rag_chunks(project_id)",
]


def _apply_migrations(conn, statements) -> None:
    """逐条执行迁移，已存在则跳过。

    注意：新列上的索引必须放在 CREATE TABLE 之后单独执行，
    否则对"旧库"（表已存在、列还没补）执行 CREATE INDEX 会直接失败并中断整个初始化。
    """
    for statement in statements:
        try:
            conn.execute(statement)
            conn.commit()
        except Exception:
            # 列/索引已存在，或该驱动不支持该语句：迁移本身是幂等的，忽略即可
            pass


def _mysql_admin_conn():
    import pymysql

    return pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
        password=MYSQL_PASSWORD, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _init_mysql():
    # Ensure the database itself exists (requires a user with CREATE privilege)
    admin = _mysql_admin_conn()
    with admin.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
            "DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    admin.commit()
    admin.close()

    conn = get_conn()
    for ddl in _MYSQL_SCHEMA:
        conn.execute(ddl)
    conn.commit()
    _apply_migrations(conn, _MYSQL_MIGRATIONS)
    conn.close()


def reset_mysql_tables():
    """Drop and recreate all tables (used to reset the test database)."""
    conn = get_conn()
    for table in _MYSQL_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS `{table}`")
    conn.commit()
    conn.close()
    _init_mysql()


def init_db():
    if DB_DRIVER == "mysql":
        _init_mysql()
        return

    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS generations (
            generation_id TEXT PRIMARY KEY,
            user_id INTEGER,
            language TEXT NOT NULL,
            task TEXT NOT NULL,
            style TEXT NOT NULL,
            code TEXT NOT NULL,
            summary TEXT NOT NULL,
            comments_json TEXT NOT NULL,
            risks_json TEXT NOT NULL,
            suggestions_json TEXT NOT NULL,
            debug_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            generation_id TEXT NOT NULL,
            model TEXT NOT NULL,
            estimated_input_tokens INTEGER NOT NULL,
            estimated_output_tokens INTEGER NOT NULL,
            estimated_cost_usd REAL NOT NULL,
            token_source TEXT NOT NULL DEFAULT 'unknown',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            generation_id TEXT NOT NULL,
            rating TEXT NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evaluations (
            generation_id TEXT PRIMARY KEY,
            user_id INTEGER,
            schema_valid INTEGER NOT NULL,
            function_count INTEGER NOT NULL,
            comment_count INTEGER NOT NULL,
            function_coverage REAL NOT NULL,
            valid_line_rate REAL NOT NULL,
            duration_ms INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rag_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            language TEXT NOT NULL DEFAULT 'text',
            char_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            project_id INTEGER,
            rel_path TEXT,
            line_count INTEGER NOT NULL DEFAULT 0,
            structure_json TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            project_id INTEGER,
            rel_path TEXT,
            language TEXT NOT NULL DEFAULT '',
            symbol_name TEXT,
            start_line INTEGER NOT NULL DEFAULT 0,
            end_line INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_user ON rag_chunks(user_id);
        CREATE INDEX IF NOT EXISTS idx_rag_documents_user ON rag_documents(user_id);
        CREATE TABLE IF NOT EXISTS ai_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            signature TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            result_json TEXT NOT NULL,
            hits INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ai_cache_user ON ai_cache(user_id);
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_id TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            archive_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            file_count INTEGER NOT NULL DEFAULT 0,
            indexed_file_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            total_bytes INTEGER NOT NULL DEFAULT 0,
            detail_json TEXT,
            error_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
    """)

    for col in ["ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"] + [
        f"ALTER TABLE {t} ADD COLUMN user_id INTEGER"
        for t in ("generations", "usage_records", "feedback", "evaluations")
    ] + [
        "ALTER TABLE usage_records ADD COLUMN token_source TEXT NOT NULL DEFAULT 'unknown'",
        "ALTER TABLE users ADD COLUMN is_disabled INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            conn.execute(col)
        except Exception:
            pass
    _apply_migrations(conn, _SQLITE_MIGRATIONS)
    conn.commit()
    conn.close()


def _read_legacy_json(name: str) -> list:
    p = DB_DIR / name
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def migrate_legacy():
    # Legacy JSON files only exist for local sqlite deployments
    if DB_DRIVER == "mysql":
        return

    conn = get_conn()
    cur = conn.cursor()

    if cur.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0:
        for e in _read_legacy_json("ai-generations.json"):
            cur.execute(
                "INSERT OR IGNORE INTO generations"
                "(generation_id,language,task,style,code,summary,comments_json,risks_json,suggestions_json,debug_json,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    e.get("generationId", ""),
                    e.get("language", "javascript"),
                    e.get("task", ""),
                    e.get("style", "default"),
                    e.get("code", ""),
                    e.get("summary", ""),
                    json.dumps(e.get("comments", [])),
                    json.dumps(e.get("risks", [])),
                    json.dumps(e.get("suggestions", [])),
                    json.dumps(e.get("debug", {})),
                    e.get("createdAt", ""),
                ),
            )

    if cur.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0] == 0:
        for e in _read_legacy_json("ai-usage.json"):
            cur.execute(
                "INSERT INTO usage_records(generation_id,model,estimated_input_tokens,estimated_output_tokens,estimated_cost_usd,created_at) VALUES(?,?,?,?,?,?)",
                (e.get("generationId", "legacy"), e.get("model", "unknown"),
                 e.get("estimatedInputTokens", 0), e.get("estimatedOutputTokens", 0),
                 e.get("estimatedCostUsd", 0), e.get("createdAt", "")),
            )

    if cur.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0:
        for e in _read_legacy_json("ai-feedback.json"):
            cur.execute(
                "INSERT INTO feedback(generation_id,rating,comment,created_at) VALUES(?,?,?,?)",
                (e.get("generationId", "legacy"), e.get("rating", ""),
                 e.get("comment", ""), e.get("createdAt", "")),
            )

    if cur.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 0:
        for e in _read_legacy_json("ai-evaluations.json"):
            cur.execute(
                "INSERT OR IGNORE INTO evaluations"
                "(generation_id,schema_valid,function_count,comment_count,function_coverage,valid_line_rate,duration_ms,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (
                    e.get("generationId", f"legacy-{e.get('createdAt', '')}"),
                    1 if e.get("schemaValid") else 0,
                    e.get("functionCount", 0), e.get("commentCount", 0),
                    e.get("functionCoverage", 0), e.get("validLineRate", 0),
                    e.get("durationMs", 0), e.get("createdAt", ""),
                ),
            )

    conn.commit()
    conn.close()


init_db()
migrate_legacy()

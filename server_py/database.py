import sqlite3
import json
import os
from pathlib import Path

DB_DIR = Path(__file__).parent / "data"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.getenv("APP_DB_PATH", str(DB_DIR / "app.sqlite")))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
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
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
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
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def _read_legacy_json(name: str) -> list:
    p = DB_DIR / name
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def migrate_legacy():
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

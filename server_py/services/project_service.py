"""项目级代码理解：上传落盘、ZIP 扫描、知识库索引与项目生命周期管理。

设计约束（与现有单文件链路保持一致）：

- 向量不新开存储：项目文件与手动文档共用 ``rag_documents`` / ``rag_chunks``，
  靠 ``project_id`` 区分归属，检索时按 ``project_id`` 过滤实现项目隔离；
- Embedding / BM25 / 混合检索全部复用 ``rag_service``，这里不重复实现；
- 结构分析复用 ``code_analyzer.analyze_code``，切片复用 ``code_chunker``；
- 索引是同步 CPU 任务，由路由层交给后台线程执行，这里用信号量限制并发。
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import (
    PROJECT_INDEX_CONCURRENCY,
    PROJECT_MAX_ARCHIVE_ENTRIES,
    PROJECT_MAX_CHUNK_CHARS,
    PROJECT_MAX_CHUNK_LINES,
    PROJECT_MAX_CHUNKS,
    PROJECT_MAX_COMPRESSION_RATIO,
    PROJECT_MAX_DEPTH,
    PROJECT_MAX_FILES,
    PROJECT_MAX_SINGLE_FILE_BYTES,
    PROJECT_MAX_TOTAL_UNCOMPRESSED_BYTES,
    PROJECT_MAX_ZIP_BYTES,
    PROJECT_STALE_UPLOAD_HOURS,
    PROJECT_UPLOAD_TMP_DIR,
)
from database import get_conn
from services import archive_service, code_chunker, rag_service
from services.archive_service import ArchiveError, ArchiveLimits
from services.code_analyzer import analyze_code

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_INDEXING = "indexing"
STATUS_READY = "ready"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
TERMINAL_STATUSES = frozenset({STATUS_READY, STATUS_PARTIAL, STATUS_FAILED})

ARCHIVE_FILENAME = "upload.zip"
FILES_DIRNAME = "files"
DETAIL_SAMPLE_LIMIT = 20
# 上传工作目录名固定为 32 位十六进制（= uuid4().hex），
# 清理逻辑只认这个形态，避免误删同一父目录下的其它数据。
_UPLOAD_DIR_RE = re.compile(r"^[0-9a-f]{32}$")

# 只有这些语言才做结构分析：其余（含 text 文档）直接走文本切片，
# 绝不能把未知语言交给 analyze_code，否则会静默退化成 JS 正则解析产生错误结构。
_ANALYZABLE_LANGUAGES = frozenset(archive_service.LANGUAGE_BY_EXTENSION.values())

LIMITS = ArchiveLimits(
    max_zip_bytes=PROJECT_MAX_ZIP_BYTES,
    max_total_bytes=PROJECT_MAX_TOTAL_UNCOMPRESSED_BYTES,
    max_single_bytes=PROJECT_MAX_SINGLE_FILE_BYTES,
    max_files=PROJECT_MAX_FILES,
    max_entries=PROJECT_MAX_ARCHIVE_ENTRIES,
    max_depth=PROJECT_MAX_DEPTH,
    max_ratio=PROJECT_MAX_COMPRESSION_RATIO,
)

_index_semaphore = threading.Semaphore(PROJECT_INDEX_CONCURRENCY)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- 上传工作目录 ---


def new_public_id() -> str:
    """项目对外标识：随机 32 位十六进制，避免自增 ID 被枚举（IDOR）。"""
    return uuid.uuid4().hex


def upload_dir_for(public_id: str) -> Path:
    return PROJECT_UPLOAD_TMP_DIR / public_id


def new_upload_dir(public_id: str) -> Path:
    PROJECT_UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)
    path = upload_dir_for(public_id)
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def discard_upload_dir(upload_dir: Optional[Path]) -> None:
    """删除单个工作目录（失败不抛异常：清理不应影响主流程）。"""
    if not upload_dir:
        return
    shutil.rmtree(upload_dir, ignore_errors=True)


def cleanup_stale_upload_dirs(max_age_hours: int = PROJECT_STALE_UPLOAD_HOURS) -> int:
    """清理上次异常退出残留的工作目录（进程启动时调用）。

    只删除"名字是 32 位十六进制且修改时间早于阈值"的子目录，
    即使配置误把工作目录指向了数据目录，也不会误删数据库等其它文件。
    """
    root = PROJECT_UPLOAD_TMP_DIR
    if not root.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for child in root.iterdir():
        if not _UPLOAD_DIR_RE.fullmatch(child.name):
            continue
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("清理陈旧上传工作目录 %s 个", removed)
    return removed


# --- 项目记录 ---


def _row_to_project(row) -> Dict[str, Any]:
    detail: Dict[str, Any] = {}
    if row["detail_json"]:
        try:
            detail = json.loads(row["detail_json"]) or {}
        except (TypeError, ValueError):
            detail = {}
    return {
        # 对外只暴露随机 public_id，不暴露自增主键
        "projectId": row["public_id"],
        "name": row["name"],
        "archiveName": row["archive_name"],
        "status": row["status"],
        "fileCount": row["file_count"],
        "indexedFileCount": row["indexed_file_count"],
        "chunkCount": row["chunk_count"],
        "totalBytes": row["total_bytes"],
        "errorMessage": row["error_message"],
        "detail": detail,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def fetch_project_row(user_id: int, public_id: str):
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT * FROM projects WHERE public_id=? AND user_id=?", (public_id, user_id)
        ).fetchone()
    finally:
        conn.close()


def _fetch_row_by_public(public_id: str):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM projects WHERE public_id=?", (public_id,)).fetchone()
    finally:
        conn.close()


def create_project(user_id: int, public_id: str, name: str, archive_name: str) -> Dict[str, Any]:
    now = _now()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO projects(public_id,user_id,name,archive_name,status,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (public_id, user_id, name, archive_name, STATUS_PENDING, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return get_project(user_id, public_id)


def get_project(user_id: int, public_id: str) -> Optional[Dict[str, Any]]:
    row = fetch_project_row(user_id, public_id)
    return _row_to_project(row) if row else None


def list_projects(user_id: int) -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM projects WHERE user_id=? ORDER BY id DESC", (user_id,)
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_project(row) for row in rows]


def count_user_projects(user_id: int) -> int:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM projects WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
    finally:
        conn.close()


def delete_project(user_id: int, public_id: str) -> bool:
    """删除项目及其全部知识片段与工作目录。"""
    row = fetch_project_row(user_id, public_id)
    if not row:
        return False
    rag_service.delete_project_documents(user_id, row["id"])
    conn = get_conn()
    try:
        conn.execute("DELETE FROM projects WHERE id=?", (row["id"],))
        conn.commit()
    finally:
        conn.close()
    discard_upload_dir(upload_dir_for(public_id))
    return True


def delete_projects_for_user(user_id: int) -> List[str]:
    """删除该用户全部项目记录与知识片段，返回需要清理的工作目录名。"""
    conn = get_conn()
    try:
        public_ids = [
            row["public_id"]
            for row in conn.execute(
                "SELECT public_id FROM projects WHERE user_id=?", (user_id,)
            ).fetchall()
        ]
    finally:
        conn.close()
    rag_service.delete_all_user_project_documents(user_id)
    conn = get_conn()
    try:
        conn.execute("DELETE FROM projects WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return public_ids


def _update_project(project_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{key}=?" for key in fields)
    conn = get_conn()
    try:
        conn.execute(
            f"UPDATE projects SET {assignments} WHERE id=?",
            tuple(fields.values()) + (project_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _fail_project(project_id: int, code: str, message: str) -> None:
    logger.warning("项目索引终止 project_id=%s code=%s message=%s", project_id, code, message)
    _update_project(
        project_id,
        status=STATUS_FAILED,
        error_message=message,
        detail_json=json.dumps({"errorCode": code}, ensure_ascii=False),
    )


# --- 索引 ---


def index_project(public_id: str, upload_dir: Path) -> None:
    """后台索引任务：解包 → 逐文件解析/切片/向量化 → 建立项目知识库。

    调用方（路由层）负责把上传内容写入 ``upload_dir/upload.zip``；
    本函数无论成功失败都会清理该工作目录。
    """
    row = _fetch_row_by_public(public_id)
    if not row:
        logger.warning("索引任务找不到项目记录 public_id=%s", public_id)
        discard_upload_dir(upload_dir)
        return

    project_id = row["id"]
    user_id = row["user_id"]
    zip_path = upload_dir / ARCHIVE_FILENAME

    try:
        with _index_semaphore:
            _update_project(project_id, status=STATUS_INDEXING, error_message="")
            _index_extracted(project_id, user_id, zip_path, upload_dir / FILES_DIRNAME)
    except ArchiveError as exc:
        _fail_project(project_id, exc.code, exc.message)
    except Exception:
        logger.exception("项目索引失败 public_id=%s", public_id)
        _fail_project(project_id, "INDEX_FAILED", "项目解析失败，请稍后重试")
    finally:
        discard_upload_dir(upload_dir)


def _index_extracted(project_id: int, user_id: int, zip_path: Path, files_dir: Path) -> None:
    plan = archive_service.plan_archive(zip_path, LIMITS)
    written_bytes = archive_service.extract_plan(zip_path, files_dir, plan, LIMITS)

    detail: Dict[str, Any] = {
        "skipped": plan.skipped,
        "skippedSamples": plan.skipped_samples,
        "skipReasonLabels": archive_service.SKIP_REASONS,
    }
    _update_project(
        project_id,
        file_count=len(plan.entries),
        total_bytes=written_bytes,
        detail_json=json.dumps(detail, ensure_ascii=False),
    )

    # 用一次探针向量确定当前 Embedding 维度：项目内所有文件必须同维度，
    # 否则检索阶段会因维度不一致整体报错。
    expected_dim = int(rag_service.embed_query("embedding dimension probe").shape[0])
    rag_service.check_embedding_dimension(user_id, expected_dim, project_id)

    indexed_files = 0
    total_chunks = 0
    failed_files: List[str] = []
    structure_failed: List[str] = []
    unreadable: List[str] = []

    for _info, rel_path, language in plan.entries:
        if total_chunks >= PROJECT_MAX_CHUNKS:
            detail["truncated"] = True
            logger.info("项目 %s 达到 Chunk 上限 %s，停止后续索引", project_id, PROJECT_MAX_CHUNKS)
            break

        content = archive_service.read_source_text(
            files_dir / rel_path, PROJECT_MAX_SINGLE_FILE_BYTES
        )
        if content is None:
            unreadable.append(rel_path)
            continue

        structure: Optional[Dict[str, Any]] = None
        if language in _ANALYZABLE_LANGUAGES:
            try:
                structure = analyze_code(content, language)
                structure["totalLines"] = content.count("\n") + 1
            except Exception as exc:
                # 语法错误/解析失败不阻断：退化为文本切片仍然可检索
                logger.info("结构分析失败，降级为文本切片 %s: %s", rel_path, exc)
                structure = None
                structure_failed.append(rel_path)

        try:
            chunks = code_chunker.build_chunks(
                content,
                structure,
                max_lines=PROJECT_MAX_CHUNK_LINES,
                overlap=rag_service.DEFAULT_OVERLAP_LINES,
                max_chars=PROJECT_MAX_CHUNK_CHARS,
            )
            chunks = chunks[: max(0, PROJECT_MAX_CHUNKS - total_chunks)]
            if not chunks:
                unreadable.append(rel_path)
                continue
            written = rag_service.index_project_file(
                user_id, project_id, rel_path, language, content, structure, chunks,
                expected_dim=expected_dim,
            )
        except Exception:
            logger.exception("索引文件失败 %s", rel_path)
            failed_files.append(rel_path)
            continue

        indexed_files += 1
        total_chunks += written
        # 逐文件回写进度，前端轮询即可看到解析进度
        _update_project(project_id, indexed_file_count=indexed_files, chunk_count=total_chunks)

    if unreadable:
        detail["unreadableSamples"] = unreadable[:DETAIL_SAMPLE_LIMIT]
    if structure_failed:
        detail["structureFailedSamples"] = structure_failed[:DETAIL_SAMPLE_LIMIT]
    if failed_files:
        detail["failedFiles"] = failed_files[:DETAIL_SAMPLE_LIMIT]

    if indexed_files == 0:
        _fail_project(project_id, "NO_INDEXABLE_FILES", "压缩包中没有可成功索引的文件")
        return

    status = STATUS_PARTIAL if (failed_files or unreadable or structure_failed) else STATUS_READY
    _update_project(
        project_id,
        status=status,
        indexed_file_count=indexed_files,
        chunk_count=total_chunks,
        detail_json=json.dumps(detail, ensure_ascii=False),
        error_message="",
    )
    logger.info(
        "项目索引完成 project_id=%s status=%s 文件 %s/%s Chunk %s",
        project_id, status, indexed_files, len(plan.entries), total_chunks,
    )


def search_project(user_id: int, public_id: str, query: str, top_k: int = 4) -> List[Dict[str, Any]]:
    """项目内检索（跨项目不可见）。"""
    row = fetch_project_row(user_id, public_id)
    if not row:
        return []
    return rag_service.search(user_id, query, top_k, project_id=row["id"])


def list_files(user_id: int, public_id: str) -> Optional[List[Dict[str, Any]]]:
    """项目文件清单；项目不存在或不属于该用户时返回 None。"""
    row = fetch_project_row(user_id, public_id)
    if not row:
        return None
    return rag_service.list_project_files(user_id, row["id"])


def get_file(user_id: int, public_id: str, document_id: int) -> Optional[Dict[str, Any]]:
    """单个项目文件的结构与分块；项目/文件不存在时返回 None。"""
    row = fetch_project_row(user_id, public_id)
    if not row:
        return None
    return rag_service.get_project_file(user_id, row["id"], document_id)


def project_counts_for_admin() -> Dict[str, int]:
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()["c"]
        ready = conn.execute(
            "SELECT COUNT(*) AS c FROM projects WHERE status IN ('ready','partial')"
        ).fetchone()["c"]
        chunks = conn.execute(
            "SELECT COUNT(*) AS c FROM rag_chunks WHERE project_id IS NOT NULL"
        ).fetchone()["c"]
    finally:
        conn.close()
    return {"projects": total, "indexedProjects": ready, "projectChunks": chunks}

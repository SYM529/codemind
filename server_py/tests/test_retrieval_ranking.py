"""检索排序与来源先验测试。

覆盖两处修复：
1. 中文按单字切词时，"的/在/是"这类虚词几乎出现在任何中文文本里，会把词面覆盖率
   抬到接近 1——既让证据门槛形同虚设，也在重排时把实现代码挤下去；
2. 排序缺少"这是实现代码"的先验，文档与测试文件会压过真正的实现。
"""
import pytest

from database import get_conn
from services import code_chunker, project_service, rag_service

USER_ID = 7373

# 同一段代码分别以"文档"和"测试"的身份入库，用来隔离来源权重的影响
SAMPLE_CODE = "\n".join([
    "def login(username, password):",
    "    validate_credentials(username, password)",
    "    return issue_token(username)",
])


@pytest.fixture
def project_id():
    public_id = project_service.new_public_id()
    project_service.create_project(USER_ID, public_id, "ranking", "ranking.zip")
    row = project_service.fetch_project_row(USER_ID, public_id)
    try:
        yield row["id"]
    finally:
        conn = get_conn()
        try:
            conn.execute("DELETE FROM rag_chunks WHERE project_id=?", (row["id"],))
            conn.execute("DELETE FROM rag_documents WHERE project_id=?", (row["id"],))
            conn.execute("DELETE FROM projects WHERE id=?", (row["id"],))
            conn.commit()
        finally:
            conn.close()


def _index(project_id: int, rel_path: str, language: str, content: str) -> None:
    chunks = code_chunker.build_chunks(content, None, max_lines=60, overlap=10, max_chars=4000)
    assert chunks, f"{rel_path} 未切出任何片段"
    rag_service.index_project_file(USER_ID, project_id, rel_path, language, content, None, chunks)


# --- 来源分类 ---


def test_source_kind_classification():
    assert rag_service.source_kind("server_py/routes/auth.py", "python") == "code"
    assert rag_service.source_kind("docs/README.md", "text") == "doc"
    assert rag_service.source_kind("server_py/tests/test_api.py", "python") == "test"
    assert rag_service.source_kind("server_py/tests/helper.py", "python") == "test"
    assert rag_service.source_kind("pkg/auth_test.py", "python") == "test"
    # 手动知识库没有相对路径，按代码档处理（同类之间权重一致，不影响相对顺序）
    assert rag_service.source_kind(None, "javascript") == "code"


# --- 中文虚词不参与词面覆盖率 ---


def test_content_tokens_drop_cjk_function_words():
    assert rag_service._content_tokens("的了在是") == set()
    assert rag_service._content_tokens("这个项目的登录") == {"项", "目", "登", "录"}


def test_query_with_only_function_words_gets_no_context(project_id):
    _index(project_id, "docs/notes.md", "text", "这个是在中的的的和与以及在里")

    context, metadata = rag_service.build_context(
        USER_ID, "在哪里", top_k=4, project_id=project_id, require_overlap=True
    )

    assert context == ""
    assert metadata == []


def test_real_content_words_still_retrieve(project_id):
    _index(project_id, "docs/notes.md", "text", "登录逻辑校验密码并签发令牌")

    context, metadata = rag_service.build_context(
        USER_ID, "登录逻辑", top_k=4, project_id=project_id, require_overlap=True
    )

    assert "登录" in context
    assert metadata and metadata[0]["relPath"] == "docs/notes.md"


# --- 来源先验：实现代码优先 ---


def test_code_outranks_document_for_identical_content(project_id):
    _index(project_id, "docs/guide.md", "text", SAMPLE_CODE)
    _index(project_id, "server_py/routes/auth.py", "python", SAMPLE_CODE)

    hits = rag_service.search(USER_ID, "login password issue_token", top_k=2, project_id=project_id)

    assert [hit["relPath"] for hit in hits] == [
        "server_py/routes/auth.py",
        "docs/guide.md",
    ]
    assert hits[0]["sourceKind"] == "code"
    assert hits[1]["sourceKind"] == "doc"


def test_code_outranks_test_file_for_identical_content(project_id):
    _index(project_id, "server_py/tests/test_auth.py", "python", SAMPLE_CODE)
    _index(project_id, "server_py/routes/auth.py", "python", SAMPLE_CODE)

    hits = rag_service.search(USER_ID, "login password issue_token", top_k=2, project_id=project_id)

    assert hits[0]["relPath"] == "server_py/routes/auth.py"
    assert hits[1]["sourceKind"] == "test"

"""ZIP 安全边界测试：路径穿越、压缩炸弹、敏感文件、超限与异常输入。

全部为纯函数测试，不连数据库、不访问网络。
"""
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest

from services import archive_service
from services.archive_service import ArchiveError, ArchiveLimits


@pytest.fixture
def tmp_path():
    """独立的本地临时目录。

    不复用 pytest 内置的同名夹具：内置实现需要扫描系统临时目录下的 ``pytest-of-*``
    目录，在受限的执行环境里会因权限被拒绝；这里用 ``mkdtemp`` 直接创建并自行清理，
    语义相同但不依赖具体环境的目录权限。
    """
    path = Path(tempfile.mkdtemp(prefix="codemind-archive-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _limits(**overrides) -> ArchiveLimits:
    base = {
        "max_zip_bytes": 1024 * 1024,
        "max_total_bytes": 10 * 1024 * 1024,
        "max_single_bytes": 1024 * 1024,
        "max_files": 10,
        "max_entries": 50,
        "max_depth": 5,
        "max_ratio": 120,
    }
    base.update(overrides)
    return ArchiveLimits(**base)


def _write_zip(path, entries, compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compression) as archive:
        for name, payload in entries:
            if isinstance(payload, zipfile.ZipInfo):
                archive.writestr(payload, "target")
            else:
                archive.writestr(name, payload)
    return path


def _symlink_entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.external_attr = (0o120777 << 16)
    return info


# --- 文件名归一化 ---


@pytest.mark.parametrize("raw", [
    "../evil.py",
    "..\\evil.py",
    "a/../../evil.py",
    "/etc/passwd.py",
    "C:/Windows/evil.py",
    "//server/share/evil.py",
    "NUL.py",
    "con.py",
    "a.py:stream",
    "a.py ",
    "a.py.",
    "",
])
def test_unsafe_member_names_are_rejected(raw):
    assert archive_service.normalize_member_name(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("src/main.py", "src/main.py"),
    ("./src/./main.py", "src/main.py"),
    ("src\\main.py", "src/main.py"),
    ("src//main.py", "src/main.py"),
])
def test_safe_member_names_are_normalized(raw, expected):
    assert archive_service.normalize_member_name(raw) == expected


# --- 文件筛选 ---


def test_language_detection_by_extension():
    assert archive_service.classify_relative_path("src/a.py", 5) == ("python", None)
    assert archive_service.classify_relative_path("src/a.tsx", 5) == ("typescript", None)
    assert archive_service.classify_relative_path("docs/readme.md", 5) == ("text", None)
    assert archive_service.classify_relative_path("bin/a.exe", 5)[1] == "unsupported_type"
    assert archive_service.classify_relative_path("a/b/c/d/e/f.py", 3)[1] == "too_deep"


def test_blocked_directories_and_sensitive_files(tmp_path):
    entries = [
        ("node_modules/lib/index.js", "x"),
        (".git/config.py", "x"),
        ("__pycache__/mod.py", "x"),
        ("dist/app.js", "x"),
        ("venv/lib.py", "x"),
        (".env", "SECRET=1"),
        (".env.local", "SECRET=1"),
        ("id_rsa", "key"),
        ("config/secret.pem", "key"),
        ("credentials.json", "{}"),
        ("src/ok.py", "print(1)"),
    ]
    plan = archive_service.plan_archive(_write_zip(tmp_path / "a.zip", entries), _limits())

    assert [path for _, path, _ in plan.entries] == ["src/ok.py"]
    assert plan.skipped["blocked_dir"] == 5
    assert plan.skipped["sensitive_file"] == 5


def test_unsupported_and_duplicate_entries_are_skipped(tmp_path):
    entries = [
        ("src/ok.py", "print(1)"),
        ("src/ok.py", "print(2)"),  # 重复路径
        ("logo.png", "binary"),
        ("package.json", "{}"),
    ]
    plan = archive_service.plan_archive(_write_zip(tmp_path / "a.zip", entries), _limits())

    assert len(plan.entries) == 1
    assert plan.skipped["duplicate"] == 1
    assert plan.skipped["unsupported_type"] == 2


def test_symlink_entry_is_rejected(tmp_path):
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as archive:
        archive.writestr("src/ok.py", "print(1)")
        archive.writestr(_symlink_entry("src/link.py"), "target")
    plan = archive_service.plan_archive(tmp_path / "a.zip", _limits())

    assert [path for _, path, _ in plan.entries] == ["src/ok.py"]
    assert plan.skipped["symlink"] == 1


def test_no_indexable_files_is_rejected(tmp_path):
    path = _write_zip(tmp_path / "a.zip", [("logo.png", "binary")])
    with pytest.raises(ArchiveError) as exc:
        archive_service.plan_archive(path, _limits())
    assert exc.value.code == "NO_INDEXABLE_FILES"


# --- 上限 ---


def test_entry_count_limit(tmp_path):
    entries = [(f"src/f{index}.py", "print(1)") for index in range(6)]
    path = _write_zip(tmp_path / "a.zip", entries)
    with pytest.raises(ArchiveError) as exc:
        archive_service.plan_archive(path, _limits(max_entries=5))
    assert exc.value.code == "ARCHIVE_TOO_MANY_ENTRIES"


def test_file_count_limit(tmp_path):
    entries = [(f"src/f{index}.py", "print(1)") for index in range(6)]
    path = _write_zip(tmp_path / "a.zip", entries)
    with pytest.raises(ArchiveError) as exc:
        archive_service.plan_archive(path, _limits(max_files=5))
    assert exc.value.code == "ARCHIVE_TOO_MANY_FILES"


def test_single_file_limit_skips_file(tmp_path):
    entries = [("src/big.py", "a" * 5000), ("src/ok.py", "print(1)")]
    plan = archive_service.plan_archive(
        _write_zip(tmp_path / "a.zip", entries), _limits(max_single_bytes=1000)
    )
    assert [path for _, path, _ in plan.entries] == ["src/ok.py"]
    assert plan.skipped["too_large"] == 1


def test_total_size_limit(tmp_path):
    entries = [(f"src/f{index}.py", "a" * 4000) for index in range(3)]
    path = _write_zip(tmp_path / "a.zip", entries)
    with pytest.raises(ArchiveError) as exc:
        archive_service.plan_archive(path, _limits(max_total_bytes=5000))
    assert exc.value.code == "ARCHIVE_TOO_LARGE"


def test_compression_ratio_bomb_is_rejected(tmp_path):
    # 单文件都在上限内、总量也在上限内，但压缩比异常（高度可压缩内容）
    entries = [("src/f1.py", "A" * 700_000), ("src/f2.py", "A" * 700_000)]
    path = _write_zip(tmp_path / "a.zip", entries)
    with pytest.raises(ArchiveError) as exc:
        archive_service.plan_archive(path, _limits(max_ratio=50))
    assert exc.value.code == "ARCHIVE_SUSPICIOUS_RATIO"


# --- 解压 ---


def test_extract_writes_only_inside_destination(tmp_path):
    entries = [("src/nested/ok.py", "print(1)"), ("README.md", "# hi")]
    path = _write_zip(tmp_path / "a.zip", entries)
    plan = archive_service.plan_archive(path, _limits())

    dest = tmp_path / "work" / "files"
    written = archive_service.extract_plan(path, dest, plan, _limits())

    assert written == len("print(1)") + len("# hi")
    assert (dest / "src" / "nested" / "ok.py").read_text() == "print(1)"
    assert (dest / "README.md").read_text() == "# hi"
    # 目标目录之外不得出现任何解压产物
    assert not (tmp_path / "work" / "ok.py").exists()
    assert not (tmp_path / "nested").exists()


def test_traversal_entries_are_dropped_and_never_extracted(tmp_path):
    entries = [
        ("../evil.py", "pwned"),
        ("a/../../evil2.py", "pwned"),
        ("/tmp/evil3.py", "pwned"),
        ("src/ok.py", "print(1)"),
    ]
    path = _write_zip(tmp_path / "a.zip", entries)
    plan = archive_service.plan_archive(path, _limits())
    assert plan.skipped["unsafe_path"] == 3

    dest = tmp_path / "work" / "files"
    archive_service.extract_plan(path, dest, plan, _limits())

    assert not (tmp_path / "evil.py").exists()
    assert not (tmp_path / "work" / "evil.py").exists()
    assert not (tmp_path / "evil2.py").exists()
    assert (dest / "src" / "ok.py").exists()


def test_extraction_rechecks_real_bytes(tmp_path):
    """元数据可以伪造，真正的上限必须在写入过程中按实际字节强制。"""
    entries = [("src/ok.py", "a" * 5000)]
    path = _write_zip(tmp_path / "a.zip", entries)
    plan = archive_service.plan_archive(path, _limits(max_single_bytes=10000))
    assert len(plan.entries) == 1

    with pytest.raises(ArchiveError) as exc:
        archive_service.extract_plan(path, tmp_path / "work", plan, _limits(max_total_bytes=100))
    assert exc.value.code == "ARCHIVE_TOO_LARGE"


# --- 异常输入 ---


def test_empty_zip_is_rejected(tmp_path):
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w"):
        pass
    with pytest.raises(ArchiveError) as exc:
        archive_service.plan_archive(path, _limits())
    assert exc.value.code == "EMPTY_ARCHIVE"


def test_corrupt_zip_is_rejected(tmp_path):
    path = tmp_path / "broken.zip"
    path.write_bytes(b"not a zip at all")
    with pytest.raises(ArchiveError) as exc:
        archive_service.plan_archive(path, _limits())
    assert exc.value.code == "INVALID_ARCHIVE"


# --- 文本读取 ---


def test_read_source_text_handles_encodings_and_binary(tmp_path):
    utf8 = tmp_path / "a.py"
    utf8.write_bytes("print('中文')".encode("utf-8"))
    assert archive_service.read_source_text(utf8, 1000) == "print('中文')"

    bom = tmp_path / "b.py"
    bom.write_bytes("print(1)".encode("utf-8-sig"))
    assert archive_service.read_source_text(bom, 1000) == "print(1)"

    gbk = tmp_path / "c.py"
    gbk.write_bytes("# 中文注释".encode("gbk"))
    assert archive_service.read_source_text(gbk, 1000) == "# 中文注释"

    binary = tmp_path / "d.py"
    binary.write_bytes(b"\x00\x01\x02binary")
    assert archive_service.read_source_text(binary, 1000) is None

    empty = tmp_path / "e.py"
    empty.write_bytes(b"")
    assert archive_service.read_source_text(empty, 1000) is None

    assert archive_service.read_source_text(utf8, 3) is None

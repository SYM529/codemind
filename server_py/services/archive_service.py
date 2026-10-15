"""ZIP 项目包的安全解包与文件筛选。

这里是上传链路唯一的安全边界，设计原则：

1. 绝不调用 ``ZipFile.extractall()``，逐条目自行解包；
2. 条目名先归一化再校验，任何绝对路径、``..``、盘符、UNC、NTFS 数据流一律拒绝；
3. 压缩包元数据（``file_size``）可被伪造，因此真正的上限在**写入过程中按实际字节数**强制；
4. 只放行明确的源代码/文档后缀，密钥、环境变量、证书、数据库文件一律不索引；
5. 全程只读字节，不导入、不执行、不解析上传包中的任何代码。
"""
from __future__ import annotations

import logging
import posixpath
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 读取/写入的解压分块大小：分块是为了让"按实际字节计数"能在写入过程中及时中断
READ_CHUNK_BYTES = 256 * 1024
# 二进制探测只看文件开头这么多字节
_BINARY_SNIFF_BYTES = 8192
# 压缩比检查的最小样本量：太小的包（几百字节）比值噪声大，容易误判
_RATIO_CHECK_FLOOR_BYTES = 1024 * 1024

# 允许索引的源代码后缀 → 语言。
# 只放行 code_analyzer 真正支持的四种语言，未知语言不会被传进去
# （code_analyzer.analyze_code 对未知语言会静默退化成 JS 正则解析，产生错误结构）。
LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
}
# 允许索引的文档后缀：语言记为 text，不做结构分析，只做文本切片
DOCUMENT_EXTENSIONS = {".md", ".txt", ".rst"}
ALLOWED_EXTENSIONS = frozenset(LANGUAGE_BY_EXTENSION) | frozenset(DOCUMENT_EXTENSIONS)

# 目录黑名单：命中即整棵子树跳过（依赖目录、构建产物、IDE 配置）
BLOCKED_DIR_NAMES = frozenset({
    ".git", ".hg", ".svn", ".bzr",
    "node_modules", "bower_components",
    "dist", "build", "out", "target", "coverage", "htmlcov",
    "venv", ".venv", "env", "virtualenv", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".cache",
    ".idea", ".vscode", ".vs", ".gradle", ".mvn",
    ".next", ".nuxt", ".svelte-kit", "vendor", "site-packages", "vendor_bundle",
    "__MACOSX",
})

# 敏感文件名（小写精确匹配）
BLOCKED_FILE_NAMES = frozenset({
    ".env", ".npmrc", ".yarnrc", ".netrc", ".htpasswd", ".pgpass", ".my.cnf",
    ".git-credentials", ".dockercfg", ".dockerconfigjson", ".aws",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "credentials.json", "secrets.json", "secret.json",
    "service-account.json", "keystore", "master.key",
})
# 敏感后缀（证书、私钥、密钥库、数据库文件）
BLOCKED_FILE_SUFFIXES = (
    ".pem", ".key", ".crt", ".cer", ".p12", ".pfx", ".jks", ".keystore", ".ppk",
    ".asc", ".gpg", ".kdbx", ".sqlite", ".sqlite3", ".db", ".mdb", ".env",
)
# 敏感前缀：.env.local / .env.production 之类
BLOCKED_FILE_PREFIXES = (".env.", "secret.", "secrets.")

# Windows 保留设备名（含 CON.txt 形式）；这些名字在 Windows 上会被重定向到设备
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")

# 跳过原因 → 面向用户的说明（错误信息里绝不出现服务器绝对路径）
SKIP_REASONS = {
    "unsafe_path": "非法路径（路径穿越/绝对路径/Windows 保留名）",
    "blocked_dir": "依赖目录或构建产物",
    "sensitive_file": "敏感文件（密钥/环境变量/证书）",
    "unsupported_type": "不支持的文件类型",
    "too_deep": "目录层级过深",
    "too_large": "文件超过单文件上限",
    "duplicate": "路径重复",
    "symlink": "符号链接",
    "empty_after_read": "文件为空或不是文本",
    "unreadable": "文件无法读取",
}


class ArchiveError(Exception):
    """压缩包校验失败。code 供接口层映射 HTTP 状态码，message 面向用户。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ArchiveLimits:
    max_zip_bytes: int
    max_total_bytes: int
    max_single_bytes: int
    max_files: int
    max_entries: int
    max_depth: int
    max_ratio: int


@dataclass
class ArchivePlan:
    """校验通过后待解包的条目清单。"""

    # (中央目录条目, 安全相对路径, 语言)：语言在这里一次判定，索引阶段直接复用，
    # 避免"哪里算语言"有两份实现而漂移。
    entries: List[Tuple[zipfile.ZipInfo, str, str]] = field(default_factory=list)
    skipped: Dict[str, int] = field(default_factory=dict)
    skipped_samples: List[str] = field(default_factory=list)
    planned_bytes: int = 0

    def note_skip(self, reason: str, name: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1
        # 只保留少量样例用于前端展示，避免 detail_json 无上限增长
        if len(self.skipped_samples) < 20:
            self.skipped_samples.append(name)


def normalize_member_name(raw: str) -> Optional[str]:
    """把 ZIP 条目名归一化为安全的相对路径（POSIX 分隔符）。

    不安全或不可用的名字返回 ``None``，由调用方计入跳过原因。
    这里直接拒绝 ``..`` 而不是"抵消"它，避免任何形式的路径回溯。
    """
    if not raw:
        return None
    # Windows 打包工具可能写反斜杠；ZIP 规范本身用正斜杠
    name = raw.replace("\\", "/")
    name = unicodedata.normalize("NFC", name)
    if "\x00" in name:
        return None
    # 绝对路径、UNC、盘符
    if name.startswith("/") or _DRIVE_PREFIX_RE.match(name):
        return None

    parts: List[str] = []
    for part in name.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        # NTFS 备用数据流（a.txt::$DATA）与任何含冒号的段
        if ":" in part:
            return None
        # Windows 会静默截断结尾的空格与点，造成同名覆盖
        if part.endswith(" ") or part.endswith("."):
            return None
        if part.split(".")[0].upper() in _WINDOWS_RESERVED_NAMES:
            return None
        parts.append(part)

    if not parts:
        return None
    return "/".join(parts)


def classify_relative_path(rel_path: str, max_depth: int) -> Tuple[Optional[str], Optional[str]]:
    """判断相对路径是否可索引。

    返回 ``(language, skip_reason)``：
    - 可索引时 language 为语言名（文档为 ``text``），skip_reason 为 ``None``；
    - 否则 language 为 ``None``，skip_reason 为跳过原因。
    """
    parts = rel_path.split("/")
    if len(parts) > max_depth:
        return None, "too_deep"

    for directory in parts[:-1]:
        lowered = directory.lower()
        if lowered in BLOCKED_DIR_NAMES or lowered.endswith(".egg-info"):
            return None, "blocked_dir"

    file_name = parts[-1]
    lowered_name = file_name.lower()
    if (
        lowered_name in BLOCKED_FILE_NAMES
        or lowered_name.startswith(BLOCKED_FILE_PREFIXES)
        or lowered_name.endswith(BLOCKED_FILE_SUFFIXES)
    ):
        return None, "sensitive_file"

    extension = posixpath.splitext(lowered_name)[1]
    if extension in LANGUAGE_BY_EXTENSION:
        return LANGUAGE_BY_EXTENSION[extension], None
    if extension in DOCUMENT_EXTENSIONS:
        return "text", None
    return None, "unsupported_type"


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """ZIP 把 Unix 文件类型放在外部属性的高 16 位。"""
    return stat.S_ISLNK(info.external_attr >> 16)


def plan_archive(zip_path: Path, limits: ArchiveLimits) -> ArchivePlan:
    """只读取中央目录做预检，不解压任何内容。

    这一层用于快速失败（不落盘、不占磁盘），真正的上限在 ``extract_plan`` 里按实际字节执行。
    """
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ArchiveError("INVALID_ARCHIVE", "文件不是有效的 ZIP 压缩包或已损坏") from exc

    with archive:
        try:
            infos = archive.infolist()
        except Exception as exc:  # 中央目录损坏
            logger.warning("读取 ZIP 中央目录失败: %s", exc)
            raise ArchiveError("INVALID_ARCHIVE", "压缩包目录结构损坏，无法解析") from exc

        if not infos:
            raise ArchiveError("EMPTY_ARCHIVE", "压缩包为空")
        if len(infos) > limits.max_entries:
            raise ArchiveError(
                "ARCHIVE_TOO_MANY_ENTRIES",
                f"压缩包条目数超过上限（最多 {limits.max_entries} 个）",
            )

        plan = ArchivePlan()
        seen_paths: set[str] = set()

        for info in infos:
            if info.is_dir():
                continue
            rel_path = normalize_member_name(info.filename)
            if rel_path is None:
                plan.note_skip("unsafe_path", info.filename[:120])
                continue
            if _is_symlink(info):
                plan.note_skip("symlink", rel_path)
                continue
            if rel_path in seen_paths:
                plan.note_skip("duplicate", rel_path)
                continue

            language, skip_reason = classify_relative_path(rel_path, limits.max_depth)
            if skip_reason:
                plan.note_skip(skip_reason, rel_path)
                continue
            if info.file_size > limits.max_single_bytes:
                plan.note_skip("too_large", rel_path)
                continue

            seen_paths.add(rel_path)
            plan.entries.append((info, rel_path, language or "text"))
            plan.planned_bytes += info.file_size

        if not plan.entries:
            raise ArchiveError(
                "NO_INDEXABLE_FILES",
                "压缩包中没有可索引的源代码或文档文件（支持 .py/.js/.ts/.jsx/.tsx/.java/.md/.txt/.rst）",
            )
        if len(plan.entries) > limits.max_files:
            raise ArchiveError(
                "ARCHIVE_TOO_MANY_FILES",
                f"可索引文件数超过上限（最多 {limits.max_files} 个，当前 {len(plan.entries)} 个）",
            )
        if plan.planned_bytes > limits.max_total_bytes:
            raise ArchiveError(
                "ARCHIVE_TOO_LARGE",
                f"解压后大小超过上限（最多 {limits.max_total_bytes // (1024 * 1024)} MB）",
            )

        zip_bytes = max(zip_path.stat().st_size, 1)
        if (
            plan.planned_bytes > _RATIO_CHECK_FLOOR_BYTES
            and plan.planned_bytes / zip_bytes > limits.max_ratio
        ):
            raise ArchiveError(
                "ARCHIVE_SUSPICIOUS_RATIO",
                "压缩包压缩比异常，已拒绝处理",
            )

        return plan


def extract_plan(zip_path: Path, dest_dir: Path, plan: ArchivePlan, limits: ArchiveLimits) -> int:
    """按预检清单解包到 ``dest_dir``，返回实际写入的字节数。

    写入过程中按**实际**字节数强制单文件与总量上限：元数据里的 ``file_size`` 可以伪造，
    只有真实计数才能挡住压缩炸弹。
    """
    dest_root = dest_dir.resolve()
    written_total = 0

    with zipfile.ZipFile(zip_path) as archive:
        for info, rel_path, _language in plan.entries:
            target = (dest_dir / rel_path).resolve()
            # 双保险：归一化已经拒绝过 `..`，这里再确认落点没有逃出目标目录
            if target != dest_root and dest_root not in target.parents:
                raise ArchiveError("ARCHIVE_PATH_TRAVERSAL", "压缩包包含非法路径，已拒绝解压")

            target.parent.mkdir(parents=True, exist_ok=True)
            file_bytes = 0
            try:
                with archive.open(info) as source, open(target, "wb") as sink:
                    while True:
                        block = source.read(READ_CHUNK_BYTES)
                        if not block:
                            break
                        file_bytes += len(block)
                        written_total += len(block)
                        if file_bytes > limits.max_single_bytes:
                            raise ArchiveError(
                                "ARCHIVE_TOO_LARGE",
                                f"文件 {rel_path} 解压后超过单文件上限",
                            )
                        if written_total > limits.max_total_bytes:
                            raise ArchiveError(
                                "ARCHIVE_TOO_LARGE",
                                f"解压总量超过上限（最多 {limits.max_total_bytes // (1024 * 1024)} MB）",
                            )
                        sink.write(block)
            except ArchiveError:
                raise
            except RuntimeError as exc:
                # 加密压缩包在 open 时抛 RuntimeError
                raise ArchiveError("INVALID_ARCHIVE", "压缩包已加密或损坏，无法读取") from exc
            except (zipfile.BadZipFile, OSError) as exc:
                logger.warning("解压条目失败 %s: %s", rel_path, exc)
                raise ArchiveError("INVALID_ARCHIVE", "压缩包已损坏，无法完整解压") from exc

    return written_total


def read_source_text(path: Path, max_bytes: int) -> Optional[str]:
    """读取并解码源码/文档文本；二进制或超限返回 ``None``。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw or len(raw) > max_bytes:
        return None
    # NUL 字节是二进制文件的可靠特征
    if b"\x00" in raw[:_BINARY_SNIFF_BYTES]:
        return None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None

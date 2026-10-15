import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

PORT = int(os.getenv("PORT", "3001"))
JWT_SECRET = os.getenv("JWT_SECRET", "")
INSECURE_JWT_SECRETS = {"development-only-change-me", "replace_with_a_long_random_secret", "secret", "changeme"}
AI_DAILY_QUOTA = max(1, int(os.getenv("AI_DAILY_QUOTA", "20")))
ADMIN_BOOTSTRAP_USERNAME = os.getenv("ADMIN_BOOTSTRAP_USERNAME", "admin")
# 关闭公开注册后，新账号只能由管理员通过 /api/admin/users 创建
ALLOW_PUBLIC_REGISTRATION = os.getenv("ALLOW_PUBLIC_REGISTRATION", "true").strip().lower() not in ("false", "0", "no", "off")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_INPUT_COST = float(os.getenv("DEEPSEEK_INPUT_COST_PER_MILLION", "0"))
DEEPSEEK_OUTPUT_COST = float(os.getenv("DEEPSEEK_OUTPUT_COST_PER_MILLION", "0"))

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:8080").split(",") if o.strip()]

# --- 项目级代码理解（ZIP 上传）限制 ---
# 全部可用同名环境变量覆盖。这里只约束"落盘与入库"的量级，
# 反向代理侧的请求体上限（nginx client_max_body_size）必须不小于 PROJECT_MAX_ZIP_BYTES，
# 两者是"与"关系：任何一项都不会放宽另一项。
PROJECT_MAX_ZIP_BYTES = max(1, int(os.getenv("PROJECT_MAX_ZIP_BYTES", str(20 * 1024 * 1024))))
PROJECT_MAX_TOTAL_UNCOMPRESSED_BYTES = max(
    1, int(os.getenv("PROJECT_MAX_TOTAL_UNCOMPRESSED_BYTES", str(120 * 1024 * 1024)))
)
PROJECT_MAX_SINGLE_FILE_BYTES = max(1, int(os.getenv("PROJECT_MAX_SINGLE_FILE_BYTES", str(1024 * 1024))))
PROJECT_MAX_FILES = max(1, int(os.getenv("PROJECT_MAX_FILES", "500")))
# 条目数上限比文件数上限宽松，用于覆盖"大量被忽略条目"的压缩包，避免提前报错
PROJECT_MAX_ARCHIVE_ENTRIES = max(1, int(os.getenv("PROJECT_MAX_ARCHIVE_ENTRIES", "5000")))
PROJECT_MAX_DEPTH = max(1, int(os.getenv("PROJECT_MAX_DEPTH", "12")))
# 解压总量 / 压缩包体积 的比值上限，用于拦截高压缩比炸弹（正常源码通常在 10 倍以内）
PROJECT_MAX_COMPRESSION_RATIO = max(1, int(os.getenv("PROJECT_MAX_COMPRESSION_RATIO", "120")))
PROJECT_MAX_CHUNKS = max(1, int(os.getenv("PROJECT_MAX_CHUNKS", "4000")))
PROJECT_MAX_PER_USER = max(1, int(os.getenv("PROJECT_MAX_PER_USER", "20")))
# 单个 Chunk 的上限：优先按符号边界切，超出后按行窗口切，最后按字符兜底
PROJECT_MAX_CHUNK_LINES = max(1, int(os.getenv("PROJECT_MAX_CHUNK_LINES", "60")))
PROJECT_MAX_CHUNK_CHARS = max(200, int(os.getenv("PROJECT_MAX_CHUNK_CHARS", "4000")))
# 同时进行的索引任务数。索引是 CPU 密集的同步任务，用信号量限制并发，
# 避免多个大项目同时解压/向量化把线程池和内存吃满。
PROJECT_INDEX_CONCURRENCY = max(1, int(os.getenv("PROJECT_INDEX_CONCURRENCY", "2")))
PROJECT_UPLOAD_RATE_LIMIT = max(1, int(os.getenv("PROJECT_UPLOAD_RATE_LIMIT", "5")))
PROJECT_UPLOAD_RATE_WINDOW_SECONDS = max(1, int(os.getenv("PROJECT_UPLOAD_RATE_WINDOW_SECONDS", "60")))
# 解压工作目录：默认落在 data/ 下，容器部署时位于 server-data 卷内，
# 这样重启后仍能扫描并清理上次异常退出残留的目录。
PROJECT_UPLOAD_TMP_DIR = Path(
    os.getenv("PROJECT_UPLOAD_TMP_DIR", str(Path(__file__).parent / "data" / "tmp"))
)
PROJECT_STALE_UPLOAD_HOURS = max(1, int(os.getenv("PROJECT_STALE_UPLOAD_HOURS", "6")))

# --- 项目级问答（project Q&A）---
# 问答与生成共用 DeepSeek 调用链与每日 AI 额度；这里额外限制单次问答的召回量与上下文体积，
# 并单独设置提问频率，避免一次问答消耗过多 Token。
PROJECT_QA_MAX_TOP_K = max(1, min(8, int(os.getenv("PROJECT_QA_MAX_TOP_K", "6"))))
PROJECT_QA_MAX_CONTEXT_CHARS = max(1000, int(os.getenv("PROJECT_QA_MAX_CONTEXT_CHARS", "8000")))
PROJECT_QA_RATE_LIMIT = max(1, int(os.getenv("PROJECT_QA_RATE_LIMIT", "10")))
PROJECT_QA_RATE_WINDOW_SECONDS = max(1, int(os.getenv("PROJECT_QA_RATE_WINDOW_SECONDS", "60")))

if not JWT_SECRET or JWT_SECRET in INSECURE_JWT_SECRETS:
    raise RuntimeError("JWT_SECRET 未配置或仍为占位符，请先在 server_py/.env 中设置一个足够长的随机字符串")

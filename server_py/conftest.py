import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Use an isolated database for tests.
_tmp_db = Path(tempfile.gettempdir()) / "nlp_code_assistant_test.sqlite"
if _tmp_db.exists():
    _tmp_db.unlink()
os.environ["APP_DB_PATH"] = str(_tmp_db)

# 测试环境固定密钥，并强制不配置 DeepSeek key：
# 防止本地 .env 被 load_dotenv 读入后在测试中发起真实付费 API 调用。
# （load_dotenv 默认不覆盖已存在的环境变量）
os.environ["JWT_SECRET"] = "ci-test-secret-that-is-long-enough-for-hs256"
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["EMBEDDING_API_KEY"] = ""
os.environ["EMBEDDING_BASE_URL"] = ""

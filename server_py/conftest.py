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

# TEST_DB_DRIVER=mysql 时用独立的 MySQL 测试库（CI 中由 service 容器提供）；
# 默认 sqlite，用临时文件，跑完即弃。
if os.getenv("TEST_DB_DRIVER", "sqlite").strip().lower() == "mysql":
    os.environ["DB_DRIVER"] = "mysql"
    os.environ["MYSQL_HOST"] = os.getenv("MYSQL_TEST_HOST", "127.0.0.1")
    os.environ["MYSQL_PORT"] = os.getenv("MYSQL_TEST_PORT", "3306")
    os.environ["MYSQL_USER"] = os.getenv("MYSQL_TEST_USER", "root")
    os.environ["MYSQL_PASSWORD"] = os.getenv("MYSQL_TEST_PASSWORD", "root")
    os.environ["MYSQL_DATABASE"] = "codemind_test"

    import database as _database

    _database.reset_mysql_tables()

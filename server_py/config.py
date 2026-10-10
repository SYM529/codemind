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

if not JWT_SECRET or JWT_SECRET in INSECURE_JWT_SECRETS:
    raise RuntimeError("JWT_SECRET 未配置或仍为占位符，请先在 server_py/.env 中设置一个足够长的随机字符串")

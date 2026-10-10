# CloudStudio 部署指南（CodeMind）

CodeMind 是一个 FastAPI + Vue3 的全栈应用，本地用 `docker compose` 跑两个容器：
- `server`：FastAPI 后端，容器内端口 `3001`
- `client`：Vue3 前端（nginx 托管静态），容器内端口 `80`，映射到宿主机 `8080`

> 注意：本项目规则会自动忽略 `node_modules/`、`.pyc`、`.env`、`client/dist/` 等文件，部署/上传时不会包含这些。

---

## 一、本地快速拉起（反复使用）

前提：本机已安装并运行 Docker Desktop。

项目根目录已提供两个脚本：

- `start-docker.bat` — 双击即构建并启动（`docker compose up -d --build`），启动后访问 http://localhost:8080
- `stop-docker.bat`  — 双击停止容器

也可以手动在 `d:\NLP\src` 下执行：

```powershell
# 启动（首次或改代码后加 --build）
docker compose up -d --build

# 停止
docker compose down

# 查看状态
docker compose ps

# 健康检查
curl.exe http://localhost:8080/api/health
```

> `.env` 不在仓库中，本地如需启用 AI 功能，请参考 `server_py/.env.example` 创建 `server_py/.env`。不创建也能跑，AI 调用会降级（前端提示 key 未配置）。

---

## 二、CloudStudio 网页手动部署

当 CloudStudio 自动部署通道不可用时，可手动在控制台部署。

### 1. 同步代码进工作空间
新建 CloudStudio 工作空间，把本项目（`d:\NLP\src`）同步进去（Git 推送或上传）。
上传时会自动忽略 `node_modules/`、`.pyc`、`.env`、`client/dist/` 等。

### 2. 创建 `server_py/.env`（关键）
`.env` 不会被上传，必须手动在沙箱终端创建。用 `server_py/.env.example` 的真实值替换：

```bash
cat > server_py/.env <<'EOF'
PORT=3001
CORS_ORIGINS=http://localhost:8080
JWT_SECRET=换成一个足够长的随机字符串
ADMIN_BOOTSTRAP_USERNAME=admin
AI_DAILY_QUOTA=20
DEEPSEEK_API_KEY=你的真实key
DEEPSEEK_MODEL=deepseek-chat
EOF
```

### 3. 构建并启动
```bash
docker compose build
docker compose up -d
```

### 4. 开放端口，获取公网 URL
在 CloudStudio 面板把 **8080** 端口（client 容器 `80→8080`）对外开放，
复制生成的公网预览 URL 即可访问。

---

## 三、关闭后如何重新打开

- **本机**：关掉后仍可重新打开——双击 `start-docker.bat`（或 `docker compose up -d`），前提是本机 Docker Desktop 在运行。
- **CloudStudio 公网**：用 `cloud_studio_deploy_sandbox` 正式部署（或上述手动部署）生成的沙箱会**持久保留在 deployments 列表里并带独立公网预览 URL**，关掉 IDE 不会消失；沙箱内服务若停了，重新进终端 `docker compose up -d` 即可重新拉起。

---

## 四、环境变量说明（server_py/.env）

| 变量 | 说明 |
| --- | --- |
| `PORT` | 后端监听端口，默认 `3001` |
| `CORS_ORIGINS` | 允许的前端源，公网部署时改为你的预览 URL |
| `JWT_SECRET` | 登录鉴权密钥，必须是足够长的随机字符串 |
| `ADMIN_BOOTSTRAP_USERNAME` | 首个管理员引导用户名 |
| `AI_DAILY_QUOTA` | 每用户每日 AI 调用配额 |
| `DEEPSEEK_API_KEY` | DeepSeek（OpenAI 兼容）API Key，启用 AI 必需 |
| `DEEPSEEK_MODEL` | 模型名，默认 `deepseek-chat` |
| `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` | 可选，RAG 向量化；不填则用本地哈希 n-gram 嵌入 |

# CodeMind 部署与问题排查复盘

> 记录项目从 SQLite 迁移 MySQL、部署到云服务器过程中真实遇到的问题、排查思路与修复方案。每个问题按「现象 → 排查 → 根因 → 修复 → 预防」结构整理。

---

## 问题 1：MySQL 迁移后 AI 生成报"服务暂时不可用"（本文档最重要的一条）

### 现象

前端点击「生成注释」持续报错 `AI 服务暂时不可用`，但所有外围检查全部正常：

- `/api/health` 200
- 容器内 `printenv DEEPSEEK_API_KEY` 有真实 Key
- 用该 Key 直接 curl DeepSeek 官方接口，返回正常 `choices`（Key 有效、余额充足）
- 当日额度仅用 12/20
- 服务日志里全部是 200，**没有任何报错**

### 排查过程

1. 排除 Key 未加载：`docker compose exec server printenv` 确认环境变量已注入
2. 排除 Key 无效/欠费：绕过项目，用容器内 Key 直接调 DeepSeek API，返回 200 + choices
3. 排除额度耗尽：查 `usage_records` 表当日计数
4. **关键卡点**：为什么访问日志全是 200？阅读流式接口源码发现盲点——SSE 接口无论中途出什么错，HTTP 状态码都是 200，异常在 `except` 分支里被转成流内的 `error` 事件，**且没有写日志**，异常被完全吞掉
5. 破局：给异常分支补上 `logger.exception`，重新部署后复现，日志立即出现完整堆栈：

```
pymysql.err.ProgrammingError: (1064, "You have an error in your SQL syntax ...
near 'INSERT evaluations(generation_id,user_id,schema_valid,...' at line 1")
```

### 根因

SQLite 迁移 MySQL 时，为了不改动 13 个业务调用点，在 `database.py` 的 `MySQLConn` 中实现了一层 SQL 方言翻译层。`INSERT OR REPLACE INTO` 需转成 MySQL 的 `REPLACE INTO`，当时的实现是简单的掐头替换：

```python
# 错误实现：原 SQL 已含 INTO，拼出双重 INTO
s = "REPLACE INTO" + s[len("INSERT OR REPLACE"):]
# "INSERT OR REPLACE INTO t" -> "REPLACE INTO INTO t"  <- MySQL 1064
```

**触发链路**：AI 生成本身成功，失败发生在生成完成后的落库步骤（`record_evaluation` 保存质量评估），一步失败将整个请求拖成错误事件。

### 为什么测试没拦住

42 项测试覆盖鉴权、RAG、缓存等路径，但「生成成功后写评估/写历史」链路需要真实调用 LLM；测试环境强制置空 Key 走 503 降级，**走不到落库逻辑**——MySQL 模式测试全绿，上线一用即炸。

### 修复

1. 方言转换改用正则，兼容带/不带 `INTO` 两种写法（`database.py` 的 `_translate`）
2. 新增 `tests/test_database_dialect.py`：5 个纯函数单元测试锁住转换行为（无需连接数据库，成本极低）
3. 流式异常写入服务端日志，同类问题从"排查一小时"变成"30 秒定位"

### 经验教训

- **接口返回 200 ≠ 没有错误**：SSE/长连接类接口的错误藏在事件流里，必须在服务端留痕
- **集成测试绿 ≠ 关键写路径被覆盖**：依赖外部付费 API 的链路，测试里只能走到降级分支，真实数据的完整落库路径是盲区；把纯函数（如 SQL 翻译）拆出来做单元测试可以低成本补上这块
- 排查外部依赖问题时，**绕过自己的代码直接用最小请求验证第三方服务**（如裸 curl DeepSeek），能快速切分"对方的问题"和"自己的问题"

---

## 问题 2：注册页面不显示注册入口

### 现象

部署后访问首页，登录页没有「立即注册」链接。

### 根因

`.env` 中 `ALLOW_PUBLIC_REGISTRATION=false`（关闭公开注册），前端通过 `/api/auth/registration-status` 感知后隐藏注册入口——这是**设计行为**，不是故障。

### 连带发现的真 Bug

后端为首个管理员留有引导通道：库中无管理员时，用 `ADMIN_BOOTSTRAP_USERNAME` 指定的用户名注册会自动授予 admin 角色。但前端在"注册关闭"状态下直接拦截提交（`Register.vue` 中 return 掉），把引导通道也堵死了。

### 修复

前端允许提交注册请求，由后端裁决：引导管理员放行，其余账号后端返回 403，前端仅展示错误信息。后端保持唯一权威校验点，前端不做业务判断。

### 经验教训

前端拦截校验看似"体验好"，但会复制一份业务规则；**规则只在一处（后端）定义**，前端只负责展示错误，才能避免多处规则不一致导致的死锁。

---

## 问题 3：服务器 git clone GitHub 卡死

### 现象

国内云服务器 `git clone https://github.com/...` 长时间无响应。

### 解决

依次尝试：

1. 浅克隆减少数据量：`git clone --depth 1`
2. 镜像加速前缀：`git clone --depth 1 https://gh-proxy.com/https://github.com/USER/REPO.git`
3. 兜底方案：本地 `scp -r` 整个目录到服务器

### 后续注意

- 服务器上所有 git 仓库属主可能是 root，操作需 `sudo`
- 本地与服务器两侧修改代码后，用 `git stash` / `git checkout -- .` / `git pull` 对齐，避免同一改动在两侧形成不同提交

---

## 问题 4：Docker 命令报权限拒绝

### 现象

`docker compose up` 报 `permission denied ... /var/run/docker.sock`。

### 解决

```bash
# 临时：命令前加 sudo
# 一劳永逸：加入 docker 组（需重新登录 SSH 生效）
sudo usermod -aG docker ubuntu
```

---

## 问题 5：本地修改 `.env` 后线上不生效

### 现象

改了 `server_py/.env`，但线上行为没变化。

### 根因

存在两份独立的 `.env`：本地仓库一份（仅本地开发用）、服务器上一份（线上用）。`.env` 在 `.gitignore` 中不会被 git 同步。且容器只在**创建时**读取环境变量，改文件不会影响已运行的容器。

### 解决

1. 改服务器上的 `~/codemind/server_py/.env`（不是本地那份）
2. 必须执行 `docker compose up -d server` 重建容器
3. 验证：`docker compose exec server printenv KEY_NAME`

### 经验教训

排查配置问题时，永远验证「容器里实际加载到的值」而不是「文件里写了什么」——`printenv` 一次就能区分"没改对"和"没生效"。

---

## 问题 6：git push 间歇性失败（Connection reset）

### 现象

本地 `git push origin main` 时而成功时而 `Connection was reset`，无规律。

### 解决

网络间歇性波动，写了个带重试的推送习惯（重试 3-5 次、间隔几秒）；多个提交本地先行 `commit`，保证任何时刻推送失败都不丢代码。

### 经验教训

**提交本地化 + 小步提交**是应对不稳定网络的最佳实践：push 永远只是"同步"，不是"保存"。

---

## 问题 7：SQLite 容器化部署数据丢失（迁移动机）

### 现象

项目最初部署在 CloudBase 云托管，SQLite 写在容器可写层，每次重新部署数据全部清空。

### 决策

迁移到 MySQL：本地开发保留 SQLite 零配置回退（`DB_DRIVER=sqlite`），生产使用 MySQL 8（PyMySQL + DBUtils 连接池），数据落在 `mysql-data` 卷持久化，3306 端口不映射公网、仅容器内网可达。

### 经验教训

容器是易失的，**容器内任何磁盘写入都应视为临时数据**；持久化状态要么外置到数据库服务，要么挂载卷，并在架构文档里明确写出。

---

## 汇总：沉淀下来的通用原则

1. **错误必须留痕**：任何"把异常转成用户友好的提示"的代码，同一行必须伴随服务端日志
2. **业务规则单点定义**：后端是唯一裁决者，前端只展示结果
3. **纯函数优先做单元测试**：SQL 翻译、签名构造这类无 IO 逻辑，单测成本最低、防回归收益最大
4. **排查外部依赖先做最小验证**：绕过自己代码直接 curl 第三方，快速二分定位
5. **容器内无持久状态**：配置走环境变量注入 + 验证实际加载值，数据走卷或外部数据库
6. **本地提交先行**：push 是同步不是保存，网络再差也不会丢工作

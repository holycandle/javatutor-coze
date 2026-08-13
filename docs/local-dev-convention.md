# JavaTutor Coze Agent 本地开发规约

> 目标：保证项目安全，并保证本地代码在 Coze 平台环境可运行。
> 本规约不涉及具体业务/产品设计；业务设计与接口契约见其他文档。
>
> **修订原则**：任何与 Coze 平台实测行为冲突的条目，以平台实测为准并回写本规约。

## 1. 工作模型

1. 本地仓库（Git）是唯一代码事实来源；Coze 平台工作区只做部署运行，不在平台内手工改代码。
2. 每次改动：本地通过全部验证门槛 → commit → push 远程仓库 → Coze 平台拉取指定分支/标签部署。
3. Coze 平台导出目录仅作只读参考，禁止编辑。
4. 禁止在 Coze 平台工作区执行与 `scripts/`、`.coze` 不一致的手工构建。

## 2. 外壳契约（禁止修改）

以下文件/目录为平台外壳，默认禁止修改；确需修改必须双人评审并单独提交：

| 路径 | 类型 | 说明 |
|---|---|---|
| `.coze` | 文件 | TOML 格式平台配置：entrypoint、python-3.12、dev/deploy 的 build/run/pack 命令 |
| `scripts/` | 目录 | 平台外壳脚本目录（`setup.sh`、`http_run.sh`、`pack.sh`、`load_env.py`/`.sh`、`local_run.sh`），禁止修改或新增 |
| `src/main.py` | 文件 | FastAPI 服务与 HTTP/SSE 协议、lifespan 编译图 |
| `src/storage/` | 目录 | 数据库引擎、checkpointer、S3 初始化（平台内置） |
| `src/utils/` | 目录 | 平台内置工具 |
| `pyproject.toml` 中平台 SDK 版本区间 | — | `coze-coding-utils`、`coze-coding-dev-sdk`、`coze-workload-identity`、`cozeloop` 等 |

> **注意**：`scripts/` 目录为平台外壳，禁止新增业务脚本。开发工具脚本统一放入 `tools/` 目录（如 `tools/seed_knowledge.py`）。

业务代码只允许新增到：`src/agents/`、`src/graphs/`、`src/tools/`、`src/learning/`、`tools/`、`assets/`、`config/`、`tests/`、`docs/`。

## 3. 环境一致性规约

### 3.1 Python 版本

项目要求 Python >= 3.12，由 `.coze` 中 `requires = ["python-3.12"]` 和 `pyproject.toml` 中 `requires-python = ">=3.12"` 双重约束。本地建议使用 `pyenv` 或系统 Python 3.12；不强制要求 `.python-version` 文件（当前项目未使用）。

### 3.2 依赖管理

1. 依赖管理只用 `uv`：

```bash
uv sync --frozen          # 按锁文件精确安装
uv sync                   # 无锁文件时按 pyproject.toml 解析并生成锁文件
```

2. `uv.lock` 必须提交；禁止手工改锁文件。新增依赖用 `uv add <pkg>`，会自动更新 `pyproject.toml` 和 `uv.lock`。
3. **Linux 专用依赖必须带平台标记**。`pyproject.toml` 中的 `pycairo`、`dbus-python`、`PyGObject` 是 Linux 专用包，已添加 `sys_platform == 'linux'` 标记，确保 Windows/macOS 本地 `uv sync` 跳过、Coze Linux 正常安装：

```toml
"pycairo==1.29.0 ; sys_platform == 'linux'",
"dbus-python==1.3.2 ; sys_platform == 'linux'",
"PyGObject==3.48.2 ; sys_platform == 'linux'",
```

4. **平台构建路径**（了解即可，不影响本地开发）：
   - DEV 环境（`COZE_PROJECT_ENV=DEV`）：`setup.sh` 执行 `uv sync --frozen`，安装到 `.venv`
   - DEPLOY 环境：`setup.sh` 执行 `uv export --frozen --no-hashes --no-dev | uv pip install --target $PIP_TARGET`，安装到 `$PIP_TARGET` 目录

### 3.3 环境变量

下表为实际 Coze 平台环境变量与本地对照（基于 2026-08-11 平台实测）：

| 变量 | Coze 平台值 | 本地 | 说明 |
|---|---|---|---|
| `COZE_WORKSPACE_PATH` | `/workspace/projects` | 本地仓库根目录 | 项目工作目录 |
| `COZE_PROJECT_TYPE` | `agent` | 必须设 `agent` | 决定使用 AgentStreamRunner（`stream_mode=messages`）还是 WorkflowStreamRunner |
| `COZE_PROJECT_ENV` | `DEV` | 可设 `DEV` | 控制是否启用 uvicorn reload；`setup.sh` 根据此值选择安装路径 |
| `COZE_INTEGRATION_MODEL_BASE_URL` | `https://integration.coze.cn/api/v3` | 本地模型端点 | LLM/Embedding API base URL |
| `COZE_WORKLOAD_IDENTITY_API_KEY` | 平台注入 | 本地 Key（可占位） | 模型调用鉴权 |
| `COZE_WORKLOAD_IDENTITY_CLIENT_ID` | 平台注入 | 本地可不配 | Workload Identity OAuth |
| `COZE_WORKLOAD_IDENTITY_CLIENT_SECRET` | 平台注入 | 本地可不配 | Workload Identity OAuth |
| `COZE_WORKLOAD_IDENTITY_TOKEN_ENDPOINT` | 平台注入 | 本地可不配 | Token 获取端点 |
| `PGDATABASE_URL` | 通过 `Client.get_project_env_vars()` 获取，非直接 env var | 本地必须配可用 PostgreSQL | 数据库连接串；`db.py` 先查 env var，再查 workload identity |
| `COZE_LOG_DIR` | `/app/work/logs/bypass` | 本地指向可写目录（如 `<repo>/.logs`） | 日志文件目录；`LOG_FILE = {COZE_LOG_DIR}/app.log` |
| `DEPLOY_RUN_PORT` | `5000` | 默认 `5000` | HTTP 服务端口；`http_run.sh` 读取此值 |
| `COZE_PROJECT_ID` | `7671055723538907190` | 本地可不配 | 项目 ID |
| `COZE_BUCKET_NAME` | 平台注入 | 本地可不配 | S3 对象存储 bucket |
| `COZE_BUCKET_ENDPOINT_URL` | 平台注入 | 本地可不配 | S3 端点 |
| `COZE_SUPABASE_SERVICE_ROLE_KEY` | 平台注入 | 本地可不配 | Supabase 服务密钥 |
| `COZE_LOOP_API_TOKEN` | 平台注入 | 本地可不配 | CozeLoop 追踪 |
| `COZE_LOOP_BASE_URL` | `https://api.coze.cn` | 本地可不配 | CozeLoop 端点 |

> **关于 `PGDATABASE_URL`**：平台不直接注入此环境变量，而是通过 `coze_workload_identity.Client().get_project_env_vars()` 在运行时获取。`db.py` 的 `get_db_url()` 会先检查环境变量，再回退到 workload identity API。本地开发时需在 `.env` 中直接配置。

### 3.4 敏感信息管理

1. `.env`、`coze-local.properties`、真实 token 一律 gitignore（`.gitignore` 已排除 `.env` 和 `.logs/`）。
2. `.env` 文件由 `db.py` 中的 `python-dotenv` 自动加载（`load_dotenv()`），无需额外配置。
3. 仓库提交 `.env.example` 模板（已创建），开发者复制为 `.env` 后填入真实值：

```bash
cp .env.example .env
```

### 3.5 本地 PostgreSQL

建议 Docker：

```bash
docker run -d --name javatutor-pg -e POSTGRES_PASSWORD=local -e POSTGRES_DB=javatutor \
  -p 5432:5432 postgres:16
```

配置环境变量：

```bash
export PGDATABASE_URL="postgresql://postgres:local@127.0.0.1:5432/javatutor"
export COZE_LOG_DIR="<repo root>/.logs"
```

> 若需要 pgvector 支持（RAG 知识库），使用 `pgvector/pgvector:pg16` 镜像替代 `postgres:16`。

### 3.6 服务降级机制（了解）

平台内置多层降级，本地开发时也需了解：

| 组件 | 正常 | 降级 | 触发条件 |
|---|---|---|---|
| 数据库引擎 (`db.py`) | PostgreSQL | SQLite (`/tmp/javatutor_fallback.db`) | `PGDATABASE_URL` 不可用或连接失败 |
| Checkpointer (`memory_saver.py`) | `AsyncPostgresSaver` | `MemorySaver`（内存，重启丢失） | DB 连接失败 |
| RAG 检索 (`knowledge.py`) | pgvector 语义搜索 | 空结果放行 | 检索异常时 `rag_degraded=True` |

## 4. 代码安全规约

1. **禁止 `from src.xxx import ...`**，统一从顶层包导入（`agents`、`graphs`、`tools`、`learning`、`storage` 等）。`src/` 目录已由平台加入 `PYTHONPATH`。
2. 代码中禁止硬编码绝对路径、密钥、Token；一律读环境变量或 `config/` 下配置文件。
3. `build_agent(ctx=None)` 必须保留，返回值必须暴露 `.builder`（`AgentBundle`）；**不得**在 `build_agent()` 内调用 `.compile()` — 编译由平台 `lifespan` 执行（`main.py` 第 270-277 行）。
4. 新增文件命名只允许字母、数字、下划线、短横线。
5. 文件统一 UTF-8，禁止改写既有文件编码。
6. 核心逻辑必须可注入测试替身（如 `model` 参数或 `configurable.chat_model`），测试不依赖真实网络。
7. **系统服务使用 9000 端口，禁止任何情况下杀死 9000 端口的服务**。业务服务使用 `DEPLOY_RUN_PORT`（默认 5000）。

## 5. 提交前验证门槛（强制）

每次 push 前按顺序执行，全部通过才能提交：

### L1 依赖锁

```bash
uv sync --frozen
```

Expected: 无报错。若锁文件不同步，先 `uv lock` 再 `uv sync --frozen`。

### L2 全量测试

```bash
uv run pytest tests/ -v
```

Expected: 全部通过。

### L3 离线构建验证

```bash
export COZE_WORKSPACE_PATH="<repo root>"
export COZE_PROJECT_TYPE="agent"
export COZE_INTEGRATION_MODEL_BASE_URL="http://127.0.0.1:9999/v1"
export COZE_WORKLOAD_IDENTITY_API_KEY="placeholder"
export PGDATABASE_URL="sqlite:////tmp/javatutor_test.db"
PYTHONPATH=src uv run python -c "from agents.agent import build_agent; g = build_agent().builder.compile(); print('ok')"
```

Expected: 输出 `ok`。验证 `build_agent()` 返回值含 `.builder` 且可编译。

> `PYTHONPATH=src` 是必需的——`pyproject.toml` 中的 `pythonpath = ["src"]` 仅对 pytest 生效，普通 `python -c` 需手动指定。无 `PGDATABASE_URL` 或连接失败时 checkpointer 自动降级为 MemorySaver，不影响编译验证。

### L4 本地 HTTP 冒烟

需要本地 PostgreSQL 与模型端点：

```bash
export COZE_WORKSPACE_PATH="<repo root>"
export COZE_PROJECT_TYPE="agent"
export COZE_PROJECT_ENV="DEV"
export COZE_INTEGRATION_MODEL_BASE_URL="<本地模型端点>"
export COZE_WORKLOAD_IDENTITY_API_KEY="<key>"
export PGDATABASE_URL="<本地 PostgreSQL>"
export COZE_LOG_DIR="<repo root>/.logs"
bash scripts/http_run.sh -p 5000 &
sleep 15
curl -fsS http://127.0.0.1:5000/health
curl -fsS http://127.0.0.1:5000/graph_parameter
curl -fsS -X POST http://127.0.0.1:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<config模型名>","messages":[{"role":"user","content":"你好"}]}'
```

Expected: `/health` 返回 `{"status":"ok"}`；`/graph_parameter` 返回 schema JSON；`/v1/chat/completions` 返回模型响应。

> 模型端点未配置时 L4 可标记 SKIP，但提交说明必须注明。

### L5 外壳回归

检查已修改（tracked）和新增（untracked）文件是否落入外壳路径：

```bash
# 已修改的 tracked 文件
git diff --name-only HEAD | grep -E "^(\.coze|scripts/|src/main\.py|src/storage/|src/utils/)"
# 新增的 untracked 文件
git status --porcelain | grep '^??' | awk '{print $2}' | grep -E "^(\.coze|scripts/|src/main\.py|src/storage/|src/utils/)"
```

Expected: 两条命令均无输出（外壳未被修改，外壳目录下无新增文件）。

> `scripts/` 整个目录为平台外壳，业务脚本应放入 `tools/`。`src/storage/` 和 `src/utils/` 同理禁止新增业务文件。

## 6. 提交与推送规约

1. 每个功能一个分支：`feat/<name>`；提交信息遵循 `feat|fix|docs|refactor: 摘要`。
2. 推送前必须通过第 5 节全部门槛。
3. 禁止 `git push --force`；禁止提交 `.env`、日志、`.venv`、`.logs`、`__pycache__`。
4. 部署使用明确分支或 tag（推荐 tag：`v1.x.x`）。

## 7. 快速测试（本地，不部署）

1. 代码层最快验证：

```bash
uv run pytest tests/ -q
```

2. HTTP 层快速验证：按第 5 节 L4 启动本地服务，用 curl 检查 `/health`、`/graph_parameter`、`/v1/chat/completions`；可维护 `tools/local_client.py` 作为本地冒烟客户端。

3. 前端可视化验证：当前 JavaTutor 后端通过 Coze v3 Chat API 调用，本地 Agent 提供 OpenAI 兼容接口，前端不能直接连本地。若需要本地可视化联调，需在 JavaTutor 后端增加 OpenAI 兼容模式（`coze.api.openai-mode=true` + `coze.api.url` 指向本地 Agent），此改造属于 JavaTutor 仓库，不进入本规约的 Coze 侧外壳范围。

在可视化改造完成前，代码与接口验证走 7.1/7.2，前端最终效果通过 Coze 平台部署确认。

## 8. Coze 平台部署规约

1. 部署来源必须是远程仓库指定分支/tag，禁止从本地直接上传导出目录。
2. 平台构建执行 `scripts/setup.sh`：
   - DEV 环境（`COZE_PROJECT_ENV=DEV`）：`uv sync --frozen`（安装到 `.venv`）
   - DEPLOY 环境：`uv export --frozen --no-hashes --no-dev | uv pip install --target $PIP_TARGET`（安装到 `$PIP_TARGET`）
   - 因此 `uv.lock` 必须与 `pyproject.toml` 严格同步。
3. 平台运行执行 `scripts/http_run.sh`，读取 `DEPLOY_RUN_PORT`（平台值 `5000`）。
4. 平台通过 `coze_workload_identity.Client.get_project_env_vars()` 获取项目级环境变量（如 `PGDATABASE_URL`），代码中不得假设它们已作为系统 env var 存在。
5. 部署后如平台预览不可用，先用平台终端/日志确认 `/health` 与依赖安装是否成功，再反馈到本地修复；禁止在平台手工改文件。
6. **日志查看**：平台日志路径为 `/app/work/logs/bypass/app.log`，可通过 `tail -n 20 /app/work/logs/bypass/app.log` 或 `grep -n "Error\|Exception" /app/work/logs/bypass/app.log` 定位问题。

## 9. 评审与修订

1. 本规约由本地开发组与 Coze 平台侧 Agent 共同评审；修改必须提交远程仓库并更新下方版本记录。
2. 任何与 Coze 平台实测行为冲突的条目，以平台实测为准并回写规约。
3. 平台 SDK 升级后需重新审查第 2 节外壳契约和第 3 节环境变量。

### 修订记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v1.0 | 2026-08-11 | 初版：基于 Coze 平台实测环境编写，涵盖外壳契约、环境变量、验证门槛、部署规约 |
| v1.1 | 2026-08-11 | 审查修订：`.coze` 文件类型修正；`PGDATABASE_URL` 获取方式修正；补全 `COZE_PROJECT_TYPE`/`COZE_PROJECT_ENV`；`setup.sh` 双路径说明；新增附录 A 平台架构要点 |
| v1.2 | 2026-08-11 | 本地开发 Agent 反馈修订：① `scripts/` 整个目录列为外壳禁止新增，`seed_knowledge.py` 移至 `tools/`；② `pyproject.toml` Linux 专用依赖补 `sys_platform == 'linux'` 标记；③ 创建 `.env.example` 模板；④ L5 检查改用 `git status --porcelain` 覆盖 untracked 文件；⑤ 新增修订记录表 |

## 附录 A：平台架构要点（影响业务代码的关键事实）

| 要点 | 说明 |
|---|---|
| **项目类型** | `COZE_PROJECT_TYPE=agent` → 使用 `AgentStreamRunner`，流式模式 `stream_mode="messages"` |
| **流式输出** | 平台拦截图中所有 `ChatOpenAI` 调用的 token chunk 并转发给客户端。中间 LLM 调用若使用 `ChatOpenAI`（如 `LLMClient.invoke()`），其输出会泄露到客户端流式响应 |
| **中间 LLM 调用** | 意图分类、评审、修订等不需要流式输出的 LLM 调用，应使用 `llm_complete()`（原始 HTTP，绕过 ChatOpenAI）而非 `LLMClient.invoke()` |
| **图编译** | `main.py` lifespan 调用 `build_agent().builder.compile(checkpointer=...)` 编译图，业务代码不自行编译 |
| **入口路径** | `graph_helper.get_agent_instance("agents.agent", ctx)` → `agents/agent.py` 的 `build_agent()` |
| **OpenAI 兼容接口** | `/v1/chat/completions` 端点由 `OpenAIChatHandler` 处理，支持标准 OpenAI 请求格式 |
| **SSE 流式接口** | `/stream_run` 端点处理 Coze 平台原生 SSE 协议 |

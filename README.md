# memory

面向 agent 的本机记忆存储服务。客户端把对话消息 `POST /add` 写入，之后用自然语言 `POST /search` 按 `user_id` 召回相关历史消息。

- FastAPI + SQLite，单进程，数据就是本地一个 SQLite 文件，不依赖数据库服务与缓存
- 检索：全文（FTS5/trigram）+ 向量双路召回融合，再经 cross-encoder 精排
- 只暴露三个接口：`POST /add`、`POST /search`（需 Bearer token）、`GET /health`（免鉴权）

## 模型选型

| 环节 | 模型 | 服务 | 是否必需 |
|---|---|---|---|
| embedding | `text-embedding-v4` | 阿里云百炼 DashScope OpenAI 兼容模式 | 必需，缺失则服务拒绝启动 |
| rerank | `bge-reranker-v2-m3` | 任意 OpenAI 兼容 `/v1/rerank` 服务 | 可选，不可用时自动降级 |

embedding 用的是 DashScope 兼容模式接口 `https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings`，默认返回 1024 维向量；单次请求最多 10 条文本，超过会报 400，所以配置里 `batch_size` 不能大于 10。

自检 embedding 端点（先确认 key 可用，再往下装）：

```bash
export DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx

curl --location 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings' \
  --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"model":"text-embedding-v4","input":"衣服的质量杠杠的"}'
```

## 环境要求

- Python ≥ 3.12
- 一个 DashScope API key（或任何 OpenAI 兼容的 embedding 服务）
- 可选：一个跑 `bge-reranker-v2-m3` 的 OpenAI 兼容 `/v1/rerank` 服务（本地 llama.cpp、vLLM、SiliconFlow 托管都可以）

## 部署

### 1. 装依赖

```bash
git clone <repo> memorybase && cd memorybase

python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. 写模型配置

配置只认仓库根目录的 `config/config.local.json`（已 gitignore），从示例复制一份：

```bash
cp config/config.example.json config/config.local.json
```

填成下面这样，就是本项目实际在用的组合（DashScope embedding + bge rerank）：

```json
{
  "embedding": {
    "enabled": true,
    "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
    "model": "text-embedding-v4",
    "dimension": 1024,
    "query_template": "{query}",
    "document_template": "{document}",
    "batch_size": 10,
    "batch_max_chars": 16000,
    "max_input_chars": 6000,
    "timeout_seconds": 60,
    "retries": 2,
    "api_key_env": "DASHSCOPE_API_KEY"
  },
  "rerank": {
    "enabled": true,
    "url": "http://127.0.0.1:8080/v1/rerank",
    "model": "bge-reranker-v2-m3",
    "timeout_seconds": 10,
    "retries": 2,
    "batch_size": 64
  }
}
```

没有 rerank 服务就把 `rerank.enabled` 改成 `false`（此时整段 rerank 配置可以保留，也可以只留 `{"enabled": false}`），检索照样可用，只是少了精排。

关键字段：

| 字段 | 说明 |
|---|---|
| `embedding.url` | OpenAI 兼容的 embeddings 端点，必须以 `http(s)://` 开头 |
| `embedding.model` / `dimension` | 模型名与实际返回维度，**必须和接口真实返回一致**，否则所有请求 503 |
| `embedding.query_template` / `document_template` | 送进模型的文本模板，必须分别含 `{query}` / `{document}`；`text-embedding-v4` 不需要指令前缀，保持默认即可 |
| `embedding.batch_size` | DashScope 上限 10，大于 10 会 400 |
| `embedding.max_input_chars` | 单条输入截断长度，`text-embedding-v4` 上下文 8192 token，6000 字符是安全值 |
| `embedding.send_dimensions` | 想用非默认维度（如 512、2048）时设为 `true`，并同步改 `dimension` |
| `embedding.api_key_env` / `rerank.api_key_env` | key 所在的环境变量名；**key 本身不写进配置**，变量缺失时拒绝启动 |
| `rerank.url` / `model` | 精排端点与模型名 |

### 3. 设置密钥与 token

```bash
# embedding 的 key，名字要和配置里的 api_key_env 一致
export DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx

# /add、/search 用的 Bearer token，至少 16 字符、不含空白
export MEMORY_BEARER_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
```

token 也可以写到当前目录的 `env` 文件里（只写 token 原文一行，启动时自动读取，已在 gitignore）：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > env
chmod 600 env
```

### 4. 启动

```bash
python -m app.main
# 默认监听 0.0.0.0:8005，可用 MEMORY_HOST / MEMORY_PORT 覆盖
```

### 5. 冒烟验证

```bash
TOKEN=$(cat env)   # 用环境变量方式设置时改成 TOKEN=$MEMORY_BEARER_TOKEN

curl http://127.0.0.1:8005/health
# {"status":"ok"}

curl -X POST http://127.0.0.1:8005/add \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"req-1","user_id":"u1","session_id":"s1",
       "messages":[{"role":"user","content":"我住在杭州，每天早上都喝一杯美式咖啡"}]}'
# {"success":true,"request_id":"req-1","user_id":"u1","session_id":"s1"}

curl -X POST http://127.0.0.1:8005/search \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"u1","query":"我喜欢喝什么咖啡","top_k":5}'
# {"data":[{"id":"mem_1","content":"我住在杭州，每天早上都喝一杯美式咖啡","score":1.0,"created_at":"..."}]}
```

## rerank 服务要求

客户端只用一种协议：`POST <rerank.url>`，请求体 `{"model": "...", "query": "...", "documents": ["...", ...]}`，响应必须返回**与输入等长**的结果：

```json
{"results": [{"index": 0, "relevance_score": 0.97}, {"index": 1, "relevance_score": 0.12}]}
```

（`results` 也可写 `data`，分数取 `relevance_score`，缺失时取 `score`。）注意不要开启 `top_n` 之类的截断，返回条数不足会被判为无效响应并降级。先自检端点：

```bash
curl -X POST http://127.0.0.1:8080/v1/rerank \
  -H 'Content-Type: application/json' \
  -d '{"model":"bge-reranker-v2-m3","query":"咖啡","documents":["我喜欢美式咖啡","今天天气不错"]}'
```

## 常见问题

- 启动报 `configuration error: ...`：`config/config.local.json` 缺失或字段不合法（`embedding.url` 必须 `http(s)://` 开头、`dimension` ≥ 1、`enabled` 必须为 `true`），或 token/API key 没配、太短。配置不合法时服务拒绝启动。
- 启动报 `DASHSCOPE_API_KEY is not set`：`api_key_env` 指定的环境变量没导出，key 不会从配置文件读。
- `/add`、`/search` 返回 503 `embedding service is unavailable`：embedding 端点不可达、key 无效，或 `dimension` 与接口返回维度不一致（例如按 1536 配了默认 1024 的模型）。
- Docker/服务里跑：数据目录是**启动目录**下的 `data/`，换目录启动等于换一份数据；要固定就在仓库根目录启动并挂载 `data/`。
- 对外暴露时建议 `MEMORY_HOST=127.0.0.1`，前面挂反向代理做 TLS 和来源限制。

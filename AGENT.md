# AGENT.md

面向接手本仓库的 agent 与开发者。以下是硬性规范，不可协商。

## 规范

1. **代码不写注释。** Python 的 `#` 注释、模块/类/函数 docstring，以及 `.toml`、`.sh`、`.cfg`、`.ini`、`.gitignore` 里的注释行都不许出现；删掉 docstring 后函数体为空就写 `pass`。需要解释的行为写进 `AGENT.md`、`README.md`。
2. **改动后必须自检。** 跑 `python3.14 script/check_no_comments.py`，输出以 `OK` 开头才算通过。不许用"临时注释稍后删"或 `# noqa`、`# type: ignore` 绕过。
3. **接口契约不可破坏。** 只暴露 `POST /add`、`POST /search`、`GET /health` 三个路由，与 https://agentmemories.ai/api-guide 一致；字段名、响应结构、错误码都是对外契约，改动前先确认兼容。
4. **鉴权不能放松。** `/add`、`/search` 只接受 `Authorization: Bearer <token>`，token 来自 `MEMORY_BEARER_TOKEN` 或当前目录 `env` / `.env`（环境变量优先），至少 16 字符且不含空白，不合格则拒绝启动；`/health` 免鉴权。token 不得出现在代码、文档、日志、错误响应或 git 中。
5. **仓库只允许两个 markdown 文件：`AGENT.md`、`README.md`**，不得新增其他 `.md`（含子目录）。
6. **凭据不入库。** 真实 API key、bearer token 只放环境变量或本机 `config/config.local.json`（已 gitignore），不得写进代码、README、日志或提交；README 里的配置只能是占位示例。embedding 是必需依赖，配置缺失或不合法时服务拒绝启动，运行期不可用时 `/add`、`/search` 返回 503；rerank 是可选依赖，不可用时降级，不得让 `/search` 失败或影响启动。
7. **禁止过拟合评测数据。** 只允许通用正则、通用字典和结构性规则，不得加入只对某个 benchmark 有效的词表或格式假设。

## 项目是什么

本机运行的记忆存储服务：客户端把对话消息 `POST /add` 写入，之后用自然语言 `POST /search` 按 `user_id` 召回相关历史消息。单进程，FastAPI + SQLite，数据是本地一个 SQLite 文件，不依赖数据库服务与缓存；需要一个 OpenAI 兼容的 embedding 服务。默认监听 `0.0.0.0:8005`，公网部署应 bind `127.0.0.1` 并由反向代理或防火墙限制来源。部署方式见 `README.md`。

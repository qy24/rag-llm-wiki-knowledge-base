# 本地知识库系统（Local Knowledge Base System）

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/qy24/local-knowledge-base/actions/workflows/ci.yml/badge.svg)](https://github.com/qy24/local-knowledge-base/actions/workflows/ci.yml)
🌐 [English README](README.en.md)

> 开源定位：本项目提供知识库系统的**整体思路与可扩展框架**（Retrieval-Augmented Generation / RAG + LLM Wiki 编译范式，FastAPI + Vue3 自托管部署）。它不绑定任何业务——你的资料如何组织、回答长成什么样，取决于你定义的知识与使用方式；本项目只提供机制与骨架。

## 它解决什么问题

文件会越积越多，而回答一次是一次，从不沉淀。这个框架做的事很简单：

1. **把资料变成结构** —— 解析、切分、向量化，再可选地把资料编译成"问题 → 答案"式的结构化条目与图谱，让知识不只可被检索，还能被复用与修订；
2. **把回答锁在真实材料里** —— 回答始终溯源到参考知识，三重防幻觉机制（系统事实检测、证据真实性约束、重大承诺必须人工核实）让模型无法拿"顺口编造"糊弄；
3. **让多端安全地共享同一套知识** —— 每端独立密钥、服务端强制隔离，提供 REST / OpenAI 兼容 / MCP 三种接入方式，局域网部署、数据不出内网；
4. **让系统越用越好** —— 每次问答留痕可标注好坏：好的回答自动提炼沉淀为经验，后续生成自动参考相似好案例；坏的记录导出复盘，不再重犯。

> 一个朴素的信念：**检索给回答以速度与出处，编译给知识以沉淀与质量。** 两者结合，知识库才从"翻书工具"变成"会积累的大脑"。

## 核心能力

| 能力 | 说明 |
|---|---|
| 知识图谱 | LLM 实体/关系抽取（按库可开关），G6 画布人工校准：编辑 / 合并 / 确认 / 位置记忆 / 分层布局 |
| 只读账号 | viewer 可查看一切，修改入口前端隐藏 + 后端 403 双重拦截 |
| 多租户密钥 | 独立密钥绑定知识范围，可过期 / 吊销，哈希存储，全程审计 |
| 三层提示词 | 密钥 / 全局 / 内置三级；口吻、语言与风格由使用者定义 |
| 接入方式 | `POST /api/v1/knowledge/search`、`/api/v1/chat/completions`（OpenAI 兼容，支持视觉）、**MCP Server**（`POST /mcp`） |

### 关键机制（详解）

- **文档流水线**：PDF / DOCX / MD / TXT / HTML / PPTX / XLSX / 图片 → 解析 → 切分（保留页码与标题，标题进入块内）→ 向量化 →（可选）知识图谱抽取。
- **混合检索**：向量 + 知识图谱双路融合（**GraphRAG 式检索增强**，结果可溯源）；图谱检索按真实关系收紧，支持排除语义（"除了 X"）与全量枚举（"所有数据"），意图由 LLM 解析。
- **会话级记忆**：传入任意 `session_id`（客户 ID / 线程 ID / 任意会话标识）：服务端自动恢复该会话上次上下文，按「密钥 + 会话」双键隔离互不串扰；不带即无状态（完全兼容）。
- **对话上下文理解**：传入一段多方往来记录（无需标注角色），系统自动分辨各方、找出其中**尚未回应的问题**并连贯作答，不重复已确认内容——适合先读懂整条线索再继续。
- **模式化回答视角**：通过 `consult_type` / `is_after_sale` 之类的请求字段切换回答视角（知识侧重 / 口吻 / 约束），具体语义由你的知识库与提示词定义，框架不做业务假设。
- **结构化知识编译**：资料可被整理为"问题 → 如何处理"条目库；原始素材可投喂给 AI 提炼成结构化经验；条目 + 图谱 + 沉淀案例形成可复利的编译层（见下节）。
- **三重防幻觉**：生成前先"自我核查"，把事实与想象分开：① **事实层**——消息里是否真的含图片等附件由系统检测并如实告知模型，模型只基于真实存在的内容作答，绝不"脑补"看到/收到；② **规则层**——只承认输入中实际提供的信息，把"声称"与"事实"严格区分；③ **决策层**——需要拍板、承诺的结论（赔付、变更、答复承诺等）不由模型代替使用者决定，一律转人工核实。回答全程可溯源、可审计，出现偏差可被定位并复盘修正。
- **审计驱动进化**：每次问答留痕（问题+回答）可一键标注 好/差：好的自动提炼沉淀，生成时自动参考相似好案例（few-shot）；差的导出复盘清单。
## RAG 与 LLM Wiki：编译式知识

2026 年社区热议的 **LLM Wiki 范式**用编译器类比点破了 RAG 的天花板：RAG 像**解释器**——每次提问都临时检索、拼凑片段，问完即忘；LLM Wiki 像**编译器**——先把原始资料编译成结构化、互联的页面，之后所有查询都基于编译产物。

本项目把两者结合为可落地的形态：

| RAG（实时检索层） | 编译层（结构化知识） |
|---|---|
| 原始文档切块向量化，低延迟检索 | 资料被编译成"问题 → 答案"式结构化条目 |
| 回答溯源到切分块（来源/页码可见） | 投喂原始素材 → AI 提炼可复用经验 |
| 幻觉只发生在当次回答，能被审计抓回 | 好案例自动沉淀，知识随使用复利增长 |
| 适合海量、常变资料 | 适合小规模、高价值、需精修的知识 |

同时规避 LLM Wiki 的最大风险（编译产物中"烤进"幻觉）：编译层条目**经人审后入库**；生成始终溯源并展示依据；所有回答可标注复盘。**检索给速度与出处，编译给沉淀与质量**——无论你的场景是内部知识问答、业务助手还是垂直领域的智能应答，这套骨架都适用。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy |
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + AntV G6 |
| 存储 | SQLite（开发）/ PostgreSQL + Qdrant + Neo4j（生产） |
| 向量化 | 任意 OpenAI 兼容接口（含本地 Ollama 等） |
| 大模型 | 任意 OpenAI 兼容端点（DeepSeek / Qwen / GLM / NVIDIA / OpenAI 等） |
| 任务队列 | 进程内 asyncio + tasks 表（无 Redis 依赖） |

## 快速开始（开发模式，无需外部服务）

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
# 复制 .env.example 为 .env 并按需修改（离线开发可设 EMBEDDING_MODE=dummy）
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```powershell
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173 ，/api 代理到 8000
```

生产模式：`npm run build` 后由后端自动托管 `frontend/dist`（打开 http://127.0.0.1:8000 即界面）。

- API 文档：http://127.0.0.1:8000/docs
- 初始管理员：`admin / admin123`（首次启动自动创建，**生产务必修改**）

## 接入示例

### OpenAI 兼容聚合端点（检索本地知识 + 调用你的大模型回答）

```bash
curl -X POST http://<服务器>:8000/api/v1/chat/completions \
  -H "Authorization: Bearer <该端的密钥>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "把这个问题用你自己的知识回答"}]}'
```

响应与 OpenAI 格式一致；回答基于密钥授权范围内的知识，检索依据（命中块 / 图谱 / 内部图片）在 `sources` / `graph` / `internal_images` 中返回，供展示与校验。

**会话记忆**：传 `session_id` 让同一会话的下一条消息自动衔接上文：

```json
{"messages": [{"role": "user", "content": "接着上面说，请给结论"}],
 "session_id": "my-session-001"}
```

**对话上下文理解**：整段往来记录放 `context`，系统找出未回应的问题作答：

```json
{"messages": [{"role": "user", "content": "最后还是没解决，下一步怎么办？"}],
 "context": ["此前消息…", "上一轮回复…", "另一方的说明…"]}
```

**回答视角切换**：`consult_type` / `is_after_sale` 等字段由你自定义语义（如"模式 A/B"），配合对应知识库与提示词即可改变回答方式：

```json
{"messages": [{"role": "user", "content": "介绍这个模式"}],
 "is_after_sale": false}
```

### MCP Server

支持 MCP 的客户端（Claude Desktop / Cursor / Dify / 自研 Agent）通过 URL + 密钥接入：

```
URL:      http://<服务器>:8000/mcp
传输:     Streamable HTTP
鉴权:     Authorization: Bearer <该端密钥>
工具:     list_knowledge_bases / search_knowledge_base / get_graph_subgraph / list_documents
```

## 多租户权限说明

- 每次请求服务端解析密钥 → 得到授权知识库集合，向量检索与图谱遍历都在授权范围内执行；
- 客户端传参无法扩大范围；密钥哈希存储、可吊销；全部操作落审计。

## 测试与部署

```powershell
.\scripts\run_tests.ps1   # 冒烟 + 云端链路/MCP/10 并发（P95<2s）
.\scripts\backup.ps1      # SQLite + 文档 + 本地向量/图谱 → zip
```

生产：`backend/.env` 可切 PostgreSQL + Qdrant + Neo4j，或 `docker compose -f deploy/docker-compose.yml up -d` 一键编排。

## 目录结构

```
knowledge-base/
├── backend/       # FastAPI 应用：api / services / stores / workers / tests
├── frontend/      # Vue3 管理台：知识库/文档/图谱/检索调试/对话测试台/密钥/审计/设置
├── deploy/        # Docker Compose
└── scripts/       # run_tests / backup / ppt_to_md / graph_layout
```

## 开源说明

MIT 协议，定位**参考实现**：提供从解析、切分、向量化、知识图谱、混合检索到多租户隔离、结构化编译、进化学习、MCP 接入的完整链路与可扩展骨架。Fork 后按你的业务定义知识与提示词即可。欢迎 Issues / PR / 想法。

## 联系作者

- 作者：qy24
- 邮箱：dakuo1003@163.com

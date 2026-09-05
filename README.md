# 本地知识库系统（Local Knowledge Base System）

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/qy24/local-knowledge-base/actions/workflows/ci.yml/badge.svg)](https://github.com/qy24/local-knowledge-base/actions/workflows/ci.yml)
🌐 [English README](README.en.md)

> 开源定位：本项目提供知识库系统的**整体思路与可扩展框架**，欢迎大家二次开发。

**本地优先、私有数据不出内网**：部署在单机 Windows 的可视化知识库系统，管理员上传文档，系统自动完成 **解析 → 切分 → 向量化 → 知识图谱构建 → 结构化知识编译**；对外提供 **REST / OpenAI 兼容聚合端点 / MCP**，供多台远程电脑上的云端大模型 / AI Agent 调用本地知识，生成**真实、可控、像真人客服**的回答。

**多租户权限隔离（核心）**：每台电脑持独立 API 密钥，只能检索绑定给它的知识库数据（服务端强制过滤，无法越权）。

**不只是 RAG，更是 RAG × LLM Wiki**：在实时向量检索之上叠加了一层"编译式"结构化知识（手册 / 经验库 / 图谱 / 进化学习），既保留检索的溯源与低延迟，又获得知识沉淀与复利——详见 [与 LLM Wiki 的结合](#-为什么值得-starrag-骨架--llm-wiki-式知识编译)。

## 功能一览

| 模块 | 说明 |
|---|---|
| 文档管理 | 上传 PDF/DOCX/MD/TXT/HTML/PPTX/XLSX/**图片(JPG/PNG/WebP/GIF)**，任务状态实时可见，删除/重解析 |
| 文本切分 | 按知识库配置 chunk_size / overlap，保留页码、标题元数据 |
| 向量化 | 默认云端 OpenAI 兼容 embedding API；离线开发可用 dummy 占位 |
| 知识图谱 | LLM 自动抽取实体/关系（可配置开关），前端 G6 画布人工编辑/确认 |
| **图片进图谱** | 上传图片自动生成"图片实体"，可与同名实体自动建立**配图**关系，画布点击图片实体直接查看原图 |
| **图谱实体面板** | 点击实体可**连续添加多个关系**（方向/类型/目标可选），列出并编辑/删除该实体全部关系，**节点位置自动记忆**（拖拽即保存） |
| 混合检索 | 向量 + 图谱两路融合，返回带来源引用的结果。**图谱检索按真实关系收紧**：点名实体时，类型/关系类型召回只取与之相连的实体（1 跳内），不跨主题串扰；纯列举查询只返回该类型实体，不扩展邻居；检索调试台可视化展示命中的实体与关系 |
| **排除语义** | 支持"除了X/排除X/不要X"类查询：LLM 意图解析识别排除对象，结果剔除排除对象及其 1 跳相连实体；"X的所有/全部数据"枚举查询自动沿关系全量展开后剔除，返回完整且不越主题的数据 |
| **视觉 RAG** | `/v1/chat/completions` 末条消息支持 OpenAI 视觉格式（text + image_url data URL / http(s)）→ 图片理解成文字 → 检索内部数据 + 内部相关图片 → 视觉模型生成回答；图片发云端前自动压缩（Pillow，最长边 1024px），内部图片仅限授权知识库 |
| **对话测试台** | Web 界面模拟远程调用：选 API 密钥（检索范围=密钥绑定知识库，不越权）、多轮对话、展开查看检索依据（文本块/图谱实体关系/内部图片）与本次生效提示词 |
| **提示词可配置** | 回答提示词三级配置：**密钥级**（密钥管理页按密钥分配）> **全局默认**（系统设置页）> 内置默认（真人客服口吻）；系统自动拼接检索上下文 |
| **图谱画布分层布局** | 一键"自动布局"：入度 0 的顶级节点排最上、逐层向下，同级按名称排序，Barycenter 算法减少连线交叉，节点大小统一、间距自适应防遮挡；节点位置拖拽自动记忆 |
| 密钥管理 | 每租户独立密钥，绑定知识库范围，可过期、可吊销、用量审计 |
| 审计日志 | 所有检索/管理操作留痕 |
| 对外接口 | `POST /api/v1/knowledge/search`、`/api/v1/knowledge/graph/query`、OpenAI 兼容 `POST /api/v1/chat/completions`、**MCP Server（`POST /mcp`）** |
| 图谱人工校准 | G6 画布编辑/删除实体关系、**实体合并**、`verified` 确认标记（已确认实体命中加权） |
| **多客户会话记忆** | `/chat/completions` 传 `session_id`（客户/会话唯一 ID）：服务端自动恢复该客户上次对话上下文接着处理，按「密钥 + 客户 ID」双键隔离、互不串扰；不传即无状态（完全兼容旧调用）；管理端可查看/清空任意会话 |
| **对话上下文自动理解** | 支持把一段**多方往来记录**（邮件/聊天文本，无角色标注）随请求传入 `context`，或直接整段放入消息：系统自动分辨各方消息、找出其中**尚未回复的问题**并连贯作答，不重复已确认过的内容——适合"回复一封新邮件前先读懂整条往来线" |
| **售前 / 售后咨询模式** | 请求可传 `consult_type` 或布尔 `is_after_sale`：售后=订单已存在、直接按问题给解决方案（不再索要订单号）；售前=按问题给产品介绍/建议；知识库数据层同步约束 |
| **审计驱动进化学习** | 每次问答留痕（客户问题 + 回复，可一键打标 好/差）；标记「好」的回复**自动提炼为结构化经验沉淀进知识库**，后续回答时自动检索相似好案例作为参考（few-shot），越用越准；标记「差」的记录可导出复盘清单，防止再犯 |
| **LLM Wiki 式知识沉淀** | 不只是存原始切分块：可把资料**编译成结构化"问题 → 如何处理"条目库**（手册/经验库），支持投喂原始回复 → AI 提炼中文处理经验；结构化条目 + 图谱互联 + 好案例自动沉淀，形成可复利的编译知识层（见下文专节） |
| **防幻觉三层防线** | ①系统侧**附件事实注入**：本次消息是否真的含图片由系统检测并明确告知模型，客户说"已上传"但无附件时绝不假装看到；②提示词**证据真实性**规则：只承认实际提供的内容；③**重大决策不擅自承诺**：补发/退款/丢件索赔等一律安抚 + 转人工核实，杜绝"已为您安排补发"式虚假承诺 |
| 只读账号 | 角色化权限（admin / viewer）：只读账号可查看全部数据并体验测试，所有修改入口前端隐藏 + 后端 403 双重拦截 |

## 为什么值得 Star：RAG 骨架 × LLM Wiki 式知识编译

2026 年社区热议的 **LLM Wiki 范式**（Karpathy 提出）用一个编译器类比点破了 RAG 的天花板：RAG 像**解释器**——每次提问都临时检索、拼凑片段，问完即忘，知识从未真正"沉淀"；LLM Wiki 像**编译器**——先把原始资料交给 LLM 编译成结构化、互联的 Wiki 页面，之后所有查询都基于编译产物。

**本项目把两者结合成了可落地的形态**：

| RAG（实时检索层） | LLM Wiki（编译式知识层） |
|---|---|
| 原始文档切分向量化，每次低延迟检索 | 资料被**编译成"问题 → 如何处理"的结构化条目库** |
| 输出可溯源到切分块（含来源文档/页码） | 投喂原始回复 → AI **提炼中文处理经验**沉淀 |
| 幻觉只发生在"当次回答"、能被审计抓回 | 好案例自动编译沉淀，知识随使用**复利增长** |
| 适合海量、常变文档 | 适合小规模、高价值、需频繁精修的垂直知识 |

并且**规避了 LLM Wiki 的最大风险**——"编译产物里被烤进幻觉"：
- 编译层（手册/经验条目）由**人工精修确认**后才入库，不是 LLM 一次生成的"黑盒事实"；
- 回答生成始终**溯源到参考知识**并展示检索依据，模型无法借"权威编译产物"掩盖错误；
- 所有回答留痕可打标，坏案例可复盘反哺知识。

> 一句话：**RAG 给速度与溯源，编译层给沉淀与质量**。适合客服、售后、设备运维等"文档不多但回答必须靠谱"的业务知识库。

## 技术栈

- 后端：Python 3.11+ / FastAPI / SQLAlchemy / SQLite（默认）或 PostgreSQL / Qdrant（生产）/ Neo4j（生产）
- 前端：Vue 3 + TypeScript + Vite + Element Plus + AntV G6
- 任务队列：进程内 asyncio + tasks 表（无 Redis 依赖）

## 快速开始（开发模式，无需外部服务）

### 1. 启动后端

```powershell
cd knowledge-base\backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
# 复制 .env.example 为 .env，按需修改（离线开发可设 EMBEDDING_MODE=dummy）
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> 注意：若 8000 端口被本机其他程序占用（本机即有此情况），改用空闲端口如 `--port 8002`。

- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health
- 初始管理员：`.env` 中 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（默认 admin / admin123，首次启动自动创建，**生产务必修改**）

### 2. 启动前端（开发模式）

```powershell
cd knowledge-base\frontend
npm install
npm run dev        # http://127.0.0.1:5173 ，/api 代理到 8000
```

生产模式：`npm run build` 后，后端会自动托管 `frontend/dist`（访问 http://127.0.0.1:8000 即界面）。

### 3. 跑测试

```powershell
cd knowledge-base
.\scripts\run_tests.ps1     # 依次运行冒烟测试 + 云端集成/MCP/并发测试
```

覆盖：上传 → 解析/切分/向量化 → 检索 → **多租户隔离** → 吊销 → 审计 → 级联删除；以及云端 OpenAI 兼容代码路径（fake 服务器）、LLM 图谱抽取、实体合并、MCP 协议、**10 并发压测（P95<2s）**。

> 说明：两个测试模块各自设置独立环境变量，须分进程运行（脚本已处理）；不要在同一 pytest 会话中同时收集两个文件。

## 使用流程

1. 管理员登录 Web 界面（默认 admin/admin123）；
2. 「知识库管理」新建知识库（每个租户一个或多个）；
3. 「文档管理」选择知识库上传文档，等待状态变为「完成」；
4. 「检索调试台」验证混合检索效果：上方显示实际生效范围与命中统计，**下方表格展示文本命中（带分数/来源）与图谱命中的实体、关系**；支持按实体**类型**召回、按**关系类型**召回；图谱检索按实体间**真实关系收紧**——点名实体的查询只返回与之相连的数据，列举类查询不扩展邻居，避免无关数据干扰回答；支持"除了X"排除语义与"X的所有数据"枚举展开；
5. 「密钥管理」为每台电脑创建密钥并绑定其知识库（可选：为该密钥配置专属回答提示词）；
6. 「对话测试台」选择密钥模拟真实调用：输入客服/业务场景问题，查看多轮回复与检索依据，确认权限范围与提示词生效情况；
7. 把密钥发给对应电脑，对方按下方示例调用。

### 配置嵌入模型（首次使用前必做）

系统向量化与语义检索依赖嵌入模型，部署后需先配置 `EMBEDDING_*` 系列配置项（`backend/.env` 或前端「系统设置」页面）。包括：

- 各云端厂商（OpenAI / 智谱 / 阿里）配置示例与向量维度对照；
- 本地 OpenAI 兼容服务（如 Ollama）的可选配置；
- **切换嵌入模型后必须「重解析」已有文档**的注意事项；
- 常见问题排查（分数无意义、维度不一致、401/超时等）。

📘 **完整教程见：[嵌入模型配置教程](docs/embedding-config-tutorial.md)**

## 对外接口示例（给远程电脑上的大模型）

### 混合检索

```bash
curl -X POST http://<服务器>:8000/api/v1/knowledge/search \
  -H "Authorization: Bearer <该电脑的密钥>" \
  -H "Content-Type: application/json" \
  -d '{"query": "设备的日常维护周期是多久？", "top_k": 8, "graph_depth": 1}'
```

返回：命中的切分块（带来源文档/页码/分数）+ 相关图谱子图 + 本次实际生效范围 `permission_scope`。

### OpenAI 兼容聚合端点（本地检索 + 调云端大模型直接回答）

```bash
curl -X POST http://<服务器>:8000/api/v1/chat/completions \
  -H "Authorization: Bearer <该电脑的密钥>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "设备的日常维护周期是多久？"}]}'
```

响应格式与 OpenAI 完全一致；回答基于该密钥授权范围内的知识，**以真人客服口吻输出（不含 [1][2] 来源编号）**；检索依据（命中的切分块 / 图谱子图 / 内部图片）在响应 `sources` / `graph` / `internal_images` 字段中返回，供调用方自行展示。

**多客户会话记忆**：传入 `session_id`，同一客户（如买家邮箱/订单号）的下一条消息自动衔接上次对话：

```json
{"messages": [{"role": "user", "content": "刚才的问题还没解决，现在又开不了机了"}],
 "session_id": "buyer@example.com"}
```

**对话上下文自动理解（回复未答复的问题）**：把整段往来记录放入 `context`（或直接整段作为消息），系统通读后针对最新一条未回复消息作答，不重复已确认内容：

```json
{"messages": [{"role": "user", "content": "I already checked and the package was still not found."}],
 "context": ["客户此前消息…", "客服上一封回复…", "平台转达…"]}
```

**售前 / 售后模式**：`consult_type: "presale" | "aftersale"`（或布尔 `is_after_sale`）控制回答视角——售后直接给解决方案、不索要订单号；售前按咨询介绍产品：

```json
{"messages": [{"role": "user", "content": "这款产品最高速度多少？"}],
 "is_after_sale": false}
```

**带图提问（视觉 RAG）**：末条消息 content 使用 OpenAI 视觉格式：

```json
{"messages": [{"role": "user", "content": [
  {"type": "text", "text": "这个产品在库里有相关资料吗？"},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]}]}
```

系统会理解图片、检索内部数据与**内部相关图片**，结合后由视觉模型生成回答（需配置支持视觉的大模型）。

**回答提示词按密钥分配**：在「密钥管理」中为某个密钥配置专属提示词（如客服口吻/品牌风格），该密钥的所有调用（REST / MCP / 对话测试台）都生效；未配置的密钥使用全局默认或内置提示词。

### MCP Server（AI 客户端直接接入）

支持 MCP 的客户端（Claude Desktop / Cursor / Dify / 自研 Agent）通过一个 URL + 密钥即可接入：

```
URL:     http://<服务器>:8000/mcp
传输:    Streamable HTTP
鉴权:    Authorization: Bearer <该电脑的密钥>
工具:    list_knowledge_bases / search_knowledge_base / get_graph_subgraph / list_documents
```

示例（Claude Desktop `claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "local-kb": {
      "url": "http://<服务器>:8000/mcp",
      "headers": { "Authorization": "Bearer sk-xxxx" }
    }
  }
}
```

每个 MCP 连接使用独立密钥，自动继承租户权限隔离（只检索绑定知识库的数据）。

## 多租户权限说明（防越权）

- 每次检索请求：服务端解析 `Bearer` 密钥 → 查库得到授权 `kb_ids`；
- 向量检索强制附加 `kb_id ∈ 授权集合` 过滤（Qdrant payload 过滤 / 本地向量库过滤）；
- 图谱遍历 Cypher/本地 BFS 同样只允许在授权知识库内展开；
- 客户端传参无法扩大范围；密钥只存哈希；吊销立即生效；全部请求落审计日志。

## 生产部署（切换 Qdrant / Neo4j / PostgreSQL）

编辑 `backend/.env`：

```ini
DATABASE_URL=postgresql+psycopg2://user:pass@localhost/kb
VECTOR_BACKEND=qdrant
QDRANT_URL=http://localhost:6333
GRAPH_BACKEND=neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=xxxx
EMBEDDING_MODE=openai
EMBEDDING_API_KEY=sk-xxx
LLM_API_KEY=sk-xxx
```

Windows 原生安装：PostgreSQL 官方安装包 / Qdrant `qdrant.exe` / Neo4j Windows 服务（需 JDK 17）。
Docker 路线：`deploy/docker-compose.yml`（postgres + qdrant + neo4j + backend 一键编排）：

```powershell
cd knowledge-base
copy deploy\..\backend\.env.example backend\.env   # 填写密钥
docker compose -f deploy/docker-compose.yml up -d  # 访问 http://localhost:8000
```

## 备份与恢复

```powershell
cd knowledge-base
.\scripts\backup.ps1          # 备份 SQLite + 文档 + 本地向量/图谱到 backups\ 下 zip
```

生产组件备份（Qdrant snapshot / Neo4j dump / pg_dump）命令见脚本注释；建议加入 Windows 任务计划程序每日执行。

## 目录结构

```
knowledge-base/
├── backend/
│   ├── app/
│   │   ├── api/          # admin / knowledge 路由
│   │   ├── services/     # 解析、切分、向量、图谱、流水线、检索
│   │   ├── stores/       # 向量库/图库抽象（local / qdrant / neo4j）
│   │   ├── core 配置      # config / database / models / security / deps
│   │   └── workers.py    # 进程内任务队列
│   ├── tests/            # 冒烟测试
│   └── requirements.txt
├── frontend/
│   └── src/views/        # 工作台/知识库/文档/切分块/图谱/检索调试台/对话测试台/密钥/审计/设置
├── scripts/              # run_tests / backup / ppt_to_md（PPT转MD）/ graph_layout（图谱分层布局）
├── deploy/               # 部署脚本（规划中）
└── README.md
```

## 开源说明与二次开发

本项目以 **MIT 协议**开源，定位为**参考实现**：提供知识库系统的**整体思路与可扩展框架**——从文档解析、文本切分、向量化、知识图谱、混合检索，到多租户密钥权限、审计日志与 MCP 接入的完整链路。欢迎大家 **Fork 并在其基础上二次开发**，定制属于自己的知识库系统；欢迎提交 Issues、PR 与改进建议。

## 联系作者 / Contact

- 作者：qy24
- 邮箱：dakuo1003@163.com
- 欢迎 Issues / PR / 交流使用问题

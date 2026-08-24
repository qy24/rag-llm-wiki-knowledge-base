# Local Knowledge Base System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/qy24/local-knowledge-base/actions/workflows/ci.yml/badge.svg)](https://github.com/qy24/local-knowledge-base/actions/workflows/ci.yml)

> Open-source positioning: this project provides the **overall design ideas and an extensible framework** for knowledge base systems — feel free to build upon it.

A **self-hosted, visual knowledge base system** that runs on a single Windows machine (no GPU required). Upload documents, and the system automatically performs **parsing → chunking → vectorization → knowledge graph construction**, then serves the knowledge to cloud LLMs / AI agents through **REST, OpenAI-compatible, and MCP** interfaces for knowledge-augmented Q&A.

> The web UI is a **data management & visualization console** (not a chat frontend). Answer generation is done by each client's own cloud LLM, which calls this system to retrieve knowledge.

## What it does

- **Document pipeline**: PDF / DOCX / Markdown / HTML / TXT / PPTX / XLSX → text blocks → chunks (with page/heading metadata) → embeddings → knowledge graph (entities & relations extracted by LLM)
- **Hybrid retrieval**: vector similarity + knowledge graph traversal, fused and ranked, with source citations; graph retrieval is tightened by real relations (type/relation seeds only return entities connected to named entities, no cross-topic leakage)
- **Exclusion semantics**: queries like "all data except X" are parsed by the LLM intent layer; excluded objects and their 1-hop neighbors are removed from results; "all/全部 data" enumeration queries expand along relations before exclusion
- **Multi-tenant permission isolation (core)**: each client holds an independent API key bound to its own knowledge bases; retrieval is **enforced server-side** by `kb_id` filters (vector store payload + graph Cypher) — clients cannot exceed their scope
- **Three integration interfaces**:
  - `POST /api/v1/knowledge/search` — hybrid retrieval REST API
  - `POST /api/v1/chat/completions` — OpenAI-compatible aggregate endpoint (local retrieval + cloud LLM generation)
  - **MCP Server** at `POST /mcp` — works with Claude Desktop / Cursor / Dify / custom agents
- **Vision RAG**: the chat endpoint accepts OpenAI vision-format content (text + `image_url` data URL / http(s)); the system understands the image, retrieves internal data and related internal images, and answers with a vision-capable model; images are compressed locally (Pillow, max 1024px) before upload
- **Configurable answer prompts**: three levels — per-key prompt (assigned in the key management page) > global default (settings page) > built-in (natural customer-service tone); the system appends the retrieved context automatically
- **Chat test console**: pick an API key in the web UI to simulate real remote calls (scope = the key's bound KBs, no privilege escalation); multi-turn chat with expandable retrieval evidence and the effective prompt
- **Layered graph layout**: one-click "auto layout" — top-level nodes (in-degree 0) on top, layers downward, same-level sorted by name, Barycenter heuristic reduces edge crossings; node sizes uniform, spacing auto-adaptive; drag positions are remembered
- **Human-in-the-loop graph curation**: review, edit, delete and **merge entities** in a G6 canvas; mark them `verified` to boost retrieval ranking
- **Images in the knowledge graph**: uploading an image auto-creates an "image entity" and can auto-link it to same-named entities via a `配图` (illustration) relation; click the image entity to view the original image
- **Entity detail panel**: click an entity to **add multiple relations in a row** (direction/type/target), list/edit/delete all its relations, and **remember node positions** (auto-saved on drag)
- **Audit log** for every search/admin operation; API keys are revocable, expirable and stored hashed

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ / FastAPI / SQLAlchemy |
| Frontend | Vue 3 + TypeScript + Vite + Element Plus + AntV G6 |
| Storage | SQLite (dev) / PostgreSQL + Qdrant + Neo4j (production) |
| Embedding | Cloud OpenAI-compatible API (default) / local bge-m3 (fallback) |
| LLM | Any OpenAI-compatible endpoint (DeepSeek / Qwen / GLM / OpenAI / Kimi...) |
| Task queue | In-process asyncio + tasks table (no Redis) |

## Quick start (dev mode, no external services)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
# copy .env.example to .env; offline dev can set EMBEDDING_MODE=dummy
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```powershell
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173, proxies /api to :8000
```

Production: `npm run build`, then the backend serves `frontend/dist` automatically (open `http://127.0.0.1:8000`).

- API docs: `http://127.0.0.1:8000/docs`
- Default admin: `admin / admin123` (created on first start — **change it in production**)

## Tests

```powershell
cd knowledge-base
.\scripts\run_tests.ps1    # smoke test + cloud-integration/MCP/10-concurrency test
```

Covers: upload → parse/chunk/vectorize → retrieval → **tenant isolation** → key revocation → audit → cascade delete; OpenAI-compatible code paths (against a fake server), LLM graph extraction, entity merge, MCP protocol, and a **10-concurrent-request benchmark (P95 < 2s)**.

## Multi-tenant permissions

- Every request resolves the `Bearer` key to its authorized `kb_ids` server-side
- Vector search and graph traversal are both filtered by the authorized scope — client parameters cannot widen it
- Keys are stored as hashes; revocation takes effect immediately; everything is audited

## Production deployment

```ini
# backend/.env
DATABASE_URL=postgresql+psycopg2://user:pass@localhost/kb
VECTOR_BACKEND=qdrant
GRAPH_BACKEND=neo4j
EMBEDDING_MODE=openai
LLM_API_KEY=sk-xxx
```

Or use Docker: `docker compose -f deploy/docker-compose.yml up -d` (postgres + qdrant + neo4j + backend).

Backup: `.\scripts\backup.ps1` (SQLite + documents + local vector/graph data → zip).

## Project layout

```
knowledge-base/
├── backend/       # FastAPI app, services, stores, tests
├── frontend/      # Vue 3 management console
├── deploy/        # Docker Compose + Dockerfile
└── scripts/       # start bat, backup, tests, format demo
```

## Open Source & Secondary Development

This project is open-sourced under the **MIT license** and positioned as a **reference implementation**: it provides the **overall design ideas and an extensible framework** for building a knowledge base system — from document parsing, chunking, vectorization, knowledge graph and hybrid retrieval, to multi-tenant API-key isolation, audit logging and MCP integration. Feel free to **fork and build your own** knowledge base on top of it; Issues, PRs and suggestions are welcome.

## License

[MIT](LICENSE)

## Contact

- Author: qy24
- Email: dakuo1003@163.com
- Issues and PRs are welcome

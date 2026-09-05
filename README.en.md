# Local Knowledge Base System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/qy24/local-knowledge-base/actions/workflows/ci.yml/badge.svg)](https://github.com/qy24/local-knowledge-base/actions/workflows/ci.yml)
🌐 [中文 README](README.md)

> Open-source positioning: this project provides the **overall design ideas and an extensible framework** for knowledge base systems — feel free to build upon it.

**Local-first, private by default**: a self-hosted visual knowledge base system that runs on a single machine (no GPU required). Upload documents and the system automatically performs **parsing → chunking → vectorization → knowledge graph construction → structured knowledge compilation**, then serves knowledge to cloud LLMs / AI agents through **REST, OpenAI-compatible, and MCP** interfaces — producing answers that are **grounded, controllable, and natural like a human agent**.

**Multi-tenant permission isolation (core)**: each client holds an independent API key bound to its own knowledge bases; retrieval is **enforced server-side** — clients can never exceed their scope.

**Not just RAG — RAG × LLM Wiki**: on top of real-time vector retrieval we add a "compiled" structured knowledge layer (handbooks / experience entries / graph / evolving learning). You keep RAG's traceability and low latency, and gain knowledge compounding — see [RAG & LLM Wiki: Compiled Knowledge](#rag--llm-wiki-compiled-knowledge).

## Feature Highlights

| Feature | Description |
|---|---|
| Document pipeline | PDF / DOCX / MD / TXT / HTML / PPTX / XLSX / **images (JPG/PNG/WebP/GIF)** → blocks → chunks (page & heading metadata) → embeddings → graph |
| Text chunking | Configurable `chunk_size` / `overlap` per KB; **Markdown headings are kept inside chunks** so each chunk is self-contained with its title |
| Knowledge graph | LLM entity/relation extraction (**per-KB switch**), G6 canvas for manual curation |
| Hybrid retrieval | Vector + graph fusion with citations; graph hits are **tightened by real relations** (type/relation seeds only return entities connected to named entities — no cross-topic leakage); multi-condition intersection & enumeration ("all data except X") supported |
| Exclusion semantics | LLM intent parsing handles "except / exclude / all-of" queries; excluded objects and their 1-hop neighbors are removed server-side |
| Vision RAG | Chat endpoint accepts OpenAI vision-format messages (text + `image_url` data URL / http(s)) → image understanding → internal retrieval + related internal images → vision model answers; images compressed locally (Pillow, max 1024px) before upload |
| **Per-customer session memory** | Pass `session_id` (buyer email / order id / thread id) — the server restores that customer's previous turns and continues seamlessly; isolated by **key + customer id**, never cross-contaminated; omit it for stateless mode (backward compatible); view/clear sessions in admin |
| **Conversation context understanding** | Supply a whole back-and-forth log (emails / chats, no roles needed) via `context`, or as the message itself: the system identifies each side, finds the **question that is still unanswered**, and replies coherently without repeating what was already confirmed — ideal before replying to a new email in an existing thread |
| **Presale / aftersale mode** | `consult_type` or boolean `is_after_sale` per request: aftersale → solve the problem directly (order already exists, no order-number nagging); presale → product intro & advice; the knowledge data layer enforces the same rules |
| **Audit-driven evolving learning** | Every Q&A is logged (question + answer) and can be tagged **good / bad**. Tagged-good replies are **auto-compiled into structured experience entries** in the KB; later answers automatically reference similar good cases (few-shot) — the system gets better with use. Bad records can be exported for review so mistakes don't repeat |
| **LLM-Wiki-style knowledge compilation** | Not just raw chunks: materials can be **compiled into structured "question → how to handle" entries**; you can feed raw replies and the AI distills them into reusable experience; structured entries + curated graph + auto-compiled good cases form a compounding knowledge layer (see the dedicated section) |
| **Anti-hallucination defense (3 layers)** | ① Server-side **attachment-fact injection**: whether a message truly contains images is detected by the system and told to the model — if a customer says "attached photos" but none arrived, the agent never pretends to see them; ② prompt **evidence-truthfulness** rule: only acknowledge what was actually provided; ③ **no unilateral commitments** on refunds/replacements/lost-package claims — reassure the customer and escalate to a human instead of fabricating "we've already processed your replacement" |
| Read-only account | Role-based accounts (admin / viewer): a viewer can browse everything and try the test console, while every mutation is hidden in the UI **and** rejected with 403 server-side |
| Audit console | Per-request logs with question + reply; tag good/bad with notes; click through to full details in a scrollable dialog |
| Keys & prompts | Per-tenant keys (bind KBs, expiry, revoke, hashed) + **3-level answer prompts**: key-level > global default > built-in customer-service tone |
| Interfaces | `POST /api/v1/knowledge/search`, `/api/v1/knowledge/graph/query`, OpenAI-compatible `POST /api/v1/chat/completions`, and an **MCP Server** (`POST /mcp`) |

## RAG & LLM Wiki: Compiled Knowledge

The community buzzword **"LLM Wiki"** (Karpathy, 2026) put a finger on RAG's ceiling with a compiler analogy: RAG is like an **interpreter** — every query re-retrieves fragments at runtime and forgets them after; LLM Wiki is like a **compiler** — raw sources are pre-compiled by an LLM into structured, interlinked wiki pages, and all later queries run against that compiled artifact.

**This project combines both into a workable form:**

| RAG layer (real-time retrieval) | Compiled layer (LLM-Wiki-style knowledge) |
|---|---|
| Raw docs chunked & embedded for low-latency retrieval | Materials **compiled into structured "question → how to handle" entries** |
| Answers traceable to chunks (source doc / page) | Feed raw replies → AI **distills reusable experience** |
| Hallucination stays local to a single answer and is caught by audit | Good cases auto-compile into the KB; knowledge **compounds with use** |
| Best for large, frequently changing corpora | Best for small, high-value, frequently curated vertical knowledge |

And it **avoids LLM Wiki's biggest risk** — hallucination baked into the "compiled artifact":
- Compiled entries (handbooks / experience items) are **human-reviewed before they are stored**, not an LLM-generated black box;
- Generation always **traces back to reference knowledge** and surfaces the evidence, so a "compiled fact" cannot launder an error;
- Every answer is logged and taggable; bad ones feed a review loop that improves the knowledge.

> In one line: **RAG gives speed and traceability; the compiled layer gives depth and quality.** Great fit for customer service, after-sales, and equipment-maintenance knowledge bases where there aren't many documents but answers must be right.

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ / FastAPI / SQLAlchemy |
| Frontend | Vue 3 + TypeScript + Vite + Element Plus + AntV G6 |
| Storage | SQLite (dev) / PostgreSQL + Qdrant + Neo4j (production) |
| Embedding | Any OpenAI-compatible API (incl. local Ollama / bge-m3) |
| LLM | Any OpenAI-compatible endpoint (DeepSeek / Qwen / GLM / NVIDIA / OpenAI / Kimi…) |
| Task queue | In-process asyncio + tasks table (no Redis) |

## Quick Start (dev mode, no external services)

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

## API Examples

### OpenAI-compatible chat (local retrieval + cloud LLM answer)

```bash
curl -X POST http://<server>:8000/api/v1/chat/completions \
  -H "Authorization: Bearer <the key of this machine>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "How often should this device be maintained?"}]}'
```

The response format matches OpenAI; the answer is grounded in the key's authorized KBs, written in a natural customer-service tone (no `[1][2]` markers). Evidence (chunks / graph / internal images) is returned in `sources` / `graph` / `internal_images`.

**Vision messages** (text + image):

```json
{"messages": [{"role": "user", "content": [
  {"type": "text", "text": "Is this product documented in the KB?"},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]}]}
```

**Per-customer session memory** — continue a conversation from where it left off:

```json
{"messages": [{"role": "user", "content": "Still not fixed, now it won't power on."}],
 "session_id": "buyer@example.com"}
```

**Conversation context** — read a whole back-and-forth and answer the newest unanswered message:

```json
{"messages": [{"role": "user", "content": "I already checked and the package was still not found."}],
 "context": ["earlier customer message…", "previous agent reply…", "platform notification…"]}
```

**Presale / aftersale mode**:

```json
{"messages": [{"role": "user", "content": "What is the max speed of this product?"}],
 "is_after_sale": false}
```

### MCP Server

Works with MCP clients (Claude Desktop / Cursor / Dify / custom agents) via one URL + key:

```
URL:     http://<server>:8000/mcp
Transport: Streamable HTTP
Auth:    Authorization: Bearer <the key>
Tools:   list_knowledge_bases / search_knowledge_base / get_graph_subgraph / list_documents
```

## Tests

```powershell
cd knowledge-base
.\scripts\run_tests.ps1    # smoke + cloud-integration/MCP/10-concurrency tests
```

Covers: upload → parse/chunk/vectorize → retrieval → **tenant isolation** → key revocation → audit → cascade delete; OpenAI-compatible code paths (fake server), LLM graph extraction, entity merge, MCP protocol, and a **10-concurrent benchmark (P95 < 2s)**.

## Multi-tenant Permissions

- Every request resolves the `Bearer` key to its authorized `kb_ids` server-side
- Vector search and graph traversal are both filtered by the authorized scope — client parameters cannot widen it
- Keys stored as hashes; revocation immediate; everything is audited

## Production Deployment

```ini
# backend/.env
DATABASE_URL=postgresql+psycopg2://user:pass@localhost/kb
VECTOR_BACKEND=qdrant
GRAPH_BACKEND=neo4j
EMBEDDING_MODE=openai
LLM_API_KEY=sk-xxx
```

Or Docker: `docker compose -f deploy/docker-compose.yml up -d` (postgres + qdrant + neo4j + backend).
Backup: `.\scripts\backup.ps1` (SQLite + documents + local vector/graph → zip).

## Project Layout

```
knowledge-base/
├── backend/       # FastAPI app, services, stores, workers, tests
├── frontend/      # Vue 3 management & visualization console
├── deploy/        # Docker Compose + Dockerfile
└── scripts/       # start bat, backup, tests, ppt_to_md, graph_layout
```

## Open Source & Secondary Development

Open-sourced under the **MIT license** and positioned as a **reference implementation**: it demonstrates the full chain — parsing, chunking, vectorization, knowledge graph, hybrid retrieval, multi-tenant key isolation, audit logging, evolving learning and MCP integration. Fork it and build your own knowledge base on top of it; Issues, PRs and ideas are welcome.

## License

[MIT](LICENSE)

## Contact

- Author: qy24
- Email: dakuo1003@163.com
- Issues and PRs are welcome

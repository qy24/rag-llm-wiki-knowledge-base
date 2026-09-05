# Local Knowledge Base System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/qy24/local-knowledge-base/actions/workflows/ci.yml/badge.svg)](https://github.com/qy24/local-knowledge-base/actions/workflows/ci.yml)
🌐 [中文 README](README.md)

> Open-source positioning: this project offers the **overall ideas and an extensible framework** (Retrieval-Augmented Generation / RAG + the LLM Wiki compilation paradigm, self-hosted on FastAPI + Vue3) for knowledge base systems. It is **not bound to any business** — how you organize your materials and what answers look like is up to the knowledge and usage you define. This project only provides the machinery.

## The problem it solves

Files pile up, and every answer is a one-off that never compounds. This framework does four simple things:

1. **Turn materials into structure** — parse, chunk, vectorize, and optionally compile materials into "question → answer"-style entries plus a graph, so knowledge is not just retrievable but reusable and revisable;
2. **Keep answers anchored to real material** — every answer traces back to reference knowledge; a three-layer anti-hallucination defense (server-side fact detection, evidence-truthfulness rules, and no unilateral commitments without human review) keeps the model honest;
3. **Share one knowledge base safely across many endpoints** — per-endpoint keys with server-enforced isolation, exposed via REST / OpenAI-compatible / MCP, deployable on a LAN so data never leaves your network;
4. **Get better with use** — every Q&A is logged and can be tagged good / bad: good answers are distilled into experience entries and referenced as few-shot examples later; bad ones are exported for review so mistakes are not repeated.

> A simple conviction: **retrieval gives answers speed and provenance; compilation gives knowledge depth and compounding.** Together, a knowledge base stops being a "page-turner" and becomes a "memory that grows."

## Core Capabilities

| Capability | Description |
|---|---|
| Document pipeline | PDF / DOCX / MD / TXT / HTML / PPTX / XLSX / images → parse → chunk (keeps page & heading; heading inside the chunk) → embed → (optional) graph extraction |
| Knowledge graph | LLM entity/relation extraction (**switchable per KB**); G6 canvas for manual curation: edit / merge / verify / position memory / layered auto-layout |
| Hybrid retrieval | Vector + knowledge-graph fusion (**GraphRAG-style**), traceable results; graph hits tightened by real relations; exclusion semantics ("all data except X") and enumeration parsed by an LLM intent layer |
| **Session-level memory** | Pass any `session_id` (customer id / thread id / arbitrary session label): the server restores that session's previous turns and continues seamlessly, isolated by **key + session** — never cross-contaminated; omit it for stateless mode (fully backward compatible) |
| **Conversation-context understanding** | Feed a whole back-and-forth log (no roles needed) via `context`, or as the message itself: the system identifies each side, finds the **still-unanswered question** and replies coherently without repeating what was confirmed |
| **Mode-switchable answering** | Switch answer perspective via request fields such as `consult_type` / `is_after_sale` — the exact semantics are defined by *your* knowledge & prompts; the framework makes no business assumptions |
| **Structured knowledge compilation** | Materials can be organized into "question → how to handle" entry libraries; raw material can be fed to the AI to be distilled into reusable structured experience; entries + graph + distilled cases form a compounding compiled layer (see below) |
| **Anti-hallucination (self-checked & honest)** | Generation starts with a self-check that keeps claims apart from facts: ① **facts** — whether attachments/images truly exist is detected by the server and stated to the model, which answers only from what really exists and never "imagines" seeing or receiving anything; ② **rules** — only information actually provided by the input is acknowledged; ③ **decisions** — conclusions that commit the user (payouts, changes, promises) are never made by the model on the user's behalf but escalated for human review. Every answer stays traceable and auditable, so drift can be located and corrected |
| **Audit-driven evolution** | Every Q&A is logged (question + answer) and can be tagged good / bad with one click: good ones are distilled automatically and referenced as few-shot examples; bad ones are exported as a review checklist |
| Read-only account | Role-based accounts: a read-only viewer can browse everything and try the console, while every mutation is hidden in the UI **and** rejected with 403 server-side |
| Multi-tenant keys | Independent keys bound to knowledge scopes, expirable / revocable / hashed, fully audited |
| Three-level prompts | Answer prompts configurable per key / global / built-in — tone, language and style are yours to define; the framework guarantees "grounded, clean output" |
| Interfaces | `POST /api/v1/knowledge/search`, `/api/v1/chat/completions` (OpenAI-compatible, vision-capable), **MCP Server** (`POST /mcp`) |

## RAG & LLM Wiki: Compiled Knowledge

The 2026 **LLM Wiki** discourse put its finger on RAG's ceiling with a compiler analogy: RAG is like an **interpreter** — it re-retrieves fragments at runtime for every query and forgets them after; LLM Wiki is like a **compiler** — raw sources are first compiled into structured, interlinked pages, and every later query runs against the compiled artifact.

This project combines the two into a workable form:

| RAG layer (real-time) | Compiled layer (structured knowledge) |
|---|---|
| Raw docs chunked & embedded for low-latency retrieval | Materials compiled into "question → answer" entries |
| Answers traceable to chunks (source / page visible) | Raw material distilled by AI into reusable experience |
| Hallucination stays local to one answer, caught by audit | Good cases auto-compile; knowledge compounds with use |
| Best for large, changing corpora | Best for small, high-value, frequently curated knowledge |

And it avoids LLM Wiki's biggest risk (hallucination baked into the compiled artifact): compiled entries are **human-reviewed before storage**; generation always traces back to and shows the evidence; every answer is taggable for review. **Retrieval gives speed and provenance; compilation gives depth and quality** — whether your scenario is internal Q&A, a business assistant, or a domain-specific answering system.

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ / FastAPI / SQLAlchemy |
| Frontend | Vue 3 + TypeScript + Vite + Element Plus + AntV G6 |
| Storage | SQLite (dev) / PostgreSQL + Qdrant + Neo4j (production) |
| Embedding | Any OpenAI-compatible API (incl. local Ollama) |
| LLM | Any OpenAI-compatible endpoint (DeepSeek / Qwen / GLM / NVIDIA / OpenAI …) |
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

Production: `npm run build`, then the backend serves `frontend/dist` (open `http://127.0.0.1:8000`).

- API docs: `http://127.0.0.1:8000/docs`
- Default admin: `admin / admin123` (created on first start — **change it in production**)

## API Examples

### OpenAI-compatible chat (retrieve local knowledge + answer with your LLM)

```bash
curl -X POST http://<server>:8000/api/v1/chat/completions \
  -H "Authorization: Bearer <the key of this endpoint>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Answer this from your own knowledge"}]}'
```

The response format matches OpenAI; answers are grounded in the key's authorized KBs; evidence is returned in `sources` / `graph` / `internal_images`.

**Session memory** — continue from where a session left off:

```json
{"messages": [{"role": "user", "content": "Following up, please give the conclusion."}],
 "session_id": "my-session-001"}
```

**Conversation context** — read a whole back-and-forth and answer the still-unanswered question:

```json
{"messages": [{"role": "user", "content": "Still unresolved, what is the next step?"}],
 "context": ["earlier message…", "previous reply…", "another party's note…"]}
```

**Switching answer perspective** — fields like `consult_type` / `is_after_sale` carry whatever semantics you define, combined with the matching KB and prompts:

```json
{"messages": [{"role": "user", "content": "Introduce this mode."}],
 "is_after_sale": false}
```

### MCP Server

Works with MCP clients (Claude Desktop / Cursor / Dify / custom agents) via URL + key:

```
URL:       http://<server>:8000/mcp
Transport: Streamable HTTP
Auth:      Authorization: Bearer <the key>
Tools:     list_knowledge_bases / search_knowledge_base / get_graph_subgraph / list_documents
```

## Multi-tenant Permissions

- Every request resolves the `Bearer` key to its authorized KB set server-side; vector search and graph traversal stay within scope
- Client parameters cannot widen the scope; keys are hashed, revocable, expirable; everything is audited

## Tests & Deployment

```powershell
.\scripts\run_tests.ps1   # smoke + cloud path / MCP / 10-concurrency (P95 < 2s)
.\scripts\backup.ps1      # SQLite + documents + local vector/graph → zip
```

Production: switch `backend/.env` to PostgreSQL + Qdrant + Neo4j, or run `docker compose -f deploy/docker-compose.yml up -d`.

## Project Layout

```
knowledge-base/
├── backend/       # FastAPI app: api / services / stores / workers / tests
├── frontend/      # Vue 3 console: KBs / documents / graph / search / chat / keys / audit / settings
├── deploy/        # Docker Compose
└── scripts/       # run_tests / backup / ppt_to_md / graph_layout
```

## Open Source

MIT license, positioned as a **reference implementation**: it demonstrates the full chain — parsing, chunking, vectorization, knowledge graph, hybrid retrieval, multi-tenant isolation, structured compilation, evolving learning and MCP integration. Fork it and define your own knowledge and prompts for your business. Issues, PRs and ideas are welcome.

## Contact

- Author: qy24
- Email: dakuo1003@163.com

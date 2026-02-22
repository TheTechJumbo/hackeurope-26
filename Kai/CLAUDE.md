# AgentFlow — Implementation Plan & Project Guide

> **"Type what you want automated. We build and run it."**
> The Lovable for AI Agents — 193 blocks, 7 categories, infinite automations.

---

## Project Vision

AgentFlow is a platform where users describe automations in plain English. Two AI agents
(Orchestra + Builder) decompose requests into composable Blocks, wire them into executable
Pipelines (DAGs), and run them — creating new blocks on-the-fly when none exist.

The block taxonomy covers 7 categories: TRIGGER, PERCEIVE, THINK, ACT, COMMUNICATE,
REMEMBER, and CONTROL FLOW — totaling ~193 blocks that can express any automation.

---

## Architecture Overview

```
User (natural language) → Orchestra Agent (decompose + wire)
                              ↓
                    Block Registry (193 blocks)
                              ↓
              Builder Agent (creates missing blocks)
                              ↓
              Pipeline Executor (LangGraph DAG)
                              ↓
            Memory + Miro + Voice + Stripe + APIs
```

**Tech Stack:**
- Backend: FastAPI (Python 3.11+)
- AI Orchestration: LangGraph + Claude API (Anthropic)
- Multimodal: Google Gemini API
- Voice: ElevenLabs TTS
- Payments: Stripe SDK
- Visual Memory: Miro API
- Frontend: Next.js + Tailwind + React Flow
- Database: SQLite (MVP) → Supabase (prod)
- Scheduling: APScheduler
- Web scraping: httpx + BeautifulSoup / Firecrawl

---

## Implementation Phases

### PHASE 0: Project Scaffolding
**Goal:** Set up the project structure, dependencies, and dev tooling.

**Tasks:**
- [ ] Create Python project with `pyproject.toml` (or `requirements.txt`)
- [ ] Set up FastAPI app skeleton (`app/main.py`)
- [ ] Create directory structure (see below)
- [ ] Set up `.env` template for API keys
- [ ] Create SQLite database initialization
- [ ] Add basic logging configuration
- [ ] Set up pytest infrastructure

**Directory Structure:**
```
Kai/
├── CLAUDE.md                    # This file
├── app/
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # Settings & env vars
│   ├── database.py              # SQLite setup
│   │
│   ├── models/                  # Pydantic data models
│   │   ├── block.py             # BlockDefinition, BlockReference
│   │   ├── pipeline.py          # Pipeline, PipelineNode, PipelineEdge
│   │   ├── execution.py         # ExecutionState, ExecutionResult
│   │   └── memory.py            # MemoryEntry, MemoryQuery
│   │
│   ├── blocks/                  # Block system
│   │   ├── registry.py          # Block CRUD + search
│   │   ├── executor.py          # Generic block executor
│   │   ├── loader.py            # Load block definitions from JSON/DB
│   │   └── definitions/         # Block definition JSON files by category
│   │       ├── triggers.json
│   │       ├── perceive.json
│   │       ├── think.json
│   │       ├── act.json
│   │       ├── communicate.json
│   │       ├── remember.json
│   │       └── control_flow.json
│   │
│   ├── blocks/implementations/  # Actual block execution code
│   │   ├── triggers/            # trigger_cron, trigger_manual, etc.
│   │   ├── perceive/            # web_search, gemini_analyze_image, etc.
│   │   ├── think/               # claude_decide, claude_summarize, etc.
│   │   ├── act/                 # stripe_pay, email_send, etc.
│   │   ├── communicate/         # elevenlabs_speak, notify_in_app, etc.
│   │   ├── remember/            # memory_read, memory_write, miro_*, etc.
│   │   └── control_flow/        # conditional_branch, loop_for_each, etc.
│   │
│   ├── agents/                  # AI agents
│   │   ├── orchestra.py         # Orchestra Agent (decompose + wire)
│   │   └── builder.py           # Builder Agent (create blocks)
│   │
│   ├── engine/                  # Pipeline execution engine
│   │   ├── graph_builder.py     # Build LangGraph from pipeline definition
│   │   ├── state.py             # OrchestrationState (LangGraph TypedDict)
│   │   ├── runner.py            # Pipeline runner (start, pause, resume)
│   │   └── scheduler.py         # APScheduler trigger management
│   │
│   ├── memory/                  # Memory subsystem
│   │   ├── store.py             # Key-value memory store
│   │   └── manager.py           # Memory manager (read, write, search)
│   │
│   ├── integrations/            # External service clients
│   │   ├── anthropic_client.py  # Claude API wrapper
│   │   ├── gemini_client.py     # Gemini API wrapper
│   │   ├── elevenlabs_client.py # ElevenLabs TTS wrapper
│   │   ├── stripe_client.py     # Stripe payments wrapper
│   │   ├── miro_client.py       # Miro board API wrapper
│   │   ├── web_client.py        # HTTP + scraping utilities
│   │   └── email_client.py      # SendGrid email wrapper
│   │
│   └── api/                     # FastAPI route handlers
│       ├── pipelines.py         # CRUD + execute pipelines
│       ├── blocks.py            # Block registry endpoints
│       ├── chat.py              # Natural language → pipeline
│       └── webhooks.py          # Incoming webhook triggers
│
├── tests/                       # Test suite
│   ├── conftest.py              # Shared fixtures
│   ├── test_models.py           # Model validation tests
│   ├── test_blocks/             # Block unit tests
│   ├── test_engine/             # Engine integration tests
│   ├── test_agents/             # Agent tests (mocked LLM)
│   └── test_api/                # API endpoint tests
│
└── frontend/                    # Next.js app (Phase 5)
    └── (Next.js scaffolding)
```

**Testing:** `pytest` runs, project imports correctly, FastAPI starts on `localhost:8000`.

---

### PHASE 1: Core Data Models & Block Registry
**Goal:** Define the type system and block storage. Everything is data first.

**Tasks:**
- [ ] Define `BlockDefinition` Pydantic model (id, name, description, category, organ, input_schema, output_schema, api_type, tier, examples)
- [ ] Define `BlockCategory` enum (trigger, perceive, think, act, communicate, remember, control)
- [ ] Define `BlockOrgan` enum (gemini, claude, elevenlabs, stripe, miro, system)
- [ ] Define `Pipeline` model (id, user_intent, trigger, nodes, edges, memory_keys, status)
- [ ] Define `PipelineNode` model (id, block_id, inputs mapping, outputs mapping)
- [ ] Define `PipelineEdge` model (from_node, to_node, condition?)
- [ ] Define `ExecutionState` model (pipeline_id, current_node, shared_context, status, errors)
- [ ] Implement `BlockRegistry` class (load, get, search, register, list_by_category)
- [ ] Create Tier 1 block definition JSON files (30 blocks — definitions only, no code yet)
- [ ] Implement block search by description (fuzzy/semantic matching for Orchestra)

**Testing:**
- Models validate correctly (valid + invalid inputs)
- Registry loads all 30 Tier 1 block definitions
- Search returns relevant blocks for natural language queries
- Round-trip: create → store → retrieve → validate

```bash
pytest tests/test_models.py tests/test_blocks/test_registry.py -v
```

---

### PHASE 2: Block Executor & First 10 Blocks
**Goal:** Execute individual blocks. Build the 10 most critical blocks with real implementations.

**Priority blocks to implement (Tier 1 core):**
1. `trigger_manual` — Simplest trigger, just passes through user input
2. `trigger_cron` — APScheduler-based scheduled trigger
3. `web_search` — Serper API or similar search
4. `web_scrape` — httpx + BeautifulSoup page scraping
5. `claude_decide` — Claude API: pick best option from a set
6. `claude_summarize` — Claude API: condense content
7. `memory_read` — Read from KV store
8. `memory_write` — Write to KV store
9. `notify_in_app` — Simple in-app notification (log/websocket)
10. `conditional_branch` — If/else routing

**Tasks:**
- [ ] Implement generic `BlockExecutor` class
  - Takes `BlockDefinition` + `input_data` → `output_data`
  - Resolves template variables (`{{node_id.field}}`, `{{memory.key}}`)
  - Handles errors gracefully (returns error result, doesn't crash)
  - Enforces input/output schema validation
- [ ] Implement each of the 10 blocks as async Python functions
- [ ] Create integration wrappers (Anthropic client, web client)
- [ ] Implement Memory Store (SQLite-backed KV with namespaces)

**Testing:**
- Each block tested in isolation with mock inputs
- Claude blocks tested with mocked API responses
- Web blocks tested with httpx mock responses
- Memory store: write → read → verify round-trip
- Executor validates schemas before/after execution

```bash
pytest tests/test_blocks/ -v
```

---

### PHASE 3: Pipeline Engine (LangGraph)
**Goal:** Wire blocks into executable DAGs. A pipeline is a graph of blocks.

**Tasks:**
- [ ] Define `OrchestrationState` (LangGraph TypedDict with reducers)
  - `shared_context: dict` — accumulated block outputs
  - `current_step: str` — which node is executing
  - `execution_log: list` — history of executed blocks
  - `errors: list` — any errors encountered
  - `memory: dict` — loaded memory values
- [ ] Implement `GraphBuilder` — takes Pipeline definition → LangGraph StateGraph
  - Create nodes for each PipelineNode (using generic executor)
  - Create edges from PipelineEdge definitions
  - Handle conditional edges (for `conditional_branch` blocks)
  - Add START → first node and last node → END edges
- [ ] Implement `PipelineRunner` — execute a compiled graph
  - Load memory before execution
  - Run graph with initial state
  - Save memory after execution
  - Return execution result with full log
- [ ] Implement template resolution in block inputs
  - `{{prev.field}}` → output of previous node
  - `{{memory.key}}` → value from memory store
  - `{{trigger.field}}` → trigger input data
- [ ] Implement `Scheduler` for cron/interval triggers (APScheduler)

**Testing:**
- Linear pipeline: A → B → C executes in order
- Branching pipeline: A → (condition) → B or C
- Loop pipeline: A → foreach(items) → B → merge
- Template resolution resolves all variable types
- Pipeline with memory: write in run 1, read in run 2
- Error handling: block failure → graceful pipeline stop with error log

```bash
pytest tests/test_engine/ -v
```

---

### PHASE 4: Orchestra & Builder Agents
**Goal:** The AI brain. Orchestra decomposes user intent; Builder creates new blocks.

**Tasks:**
- [ ] Implement Orchestra Agent
  - System prompt: knows block registry (names, descriptions, I/O schemas)
  - Input: user's natural language request
  - Output: `Pipeline` definition (trigger, nodes, edges, memory_keys)
  - Process:
    1. Parse user intent (what, when, how)
    2. Search block registry for matching blocks
    3. If blocks missing → request Builder to create them
    4. Wire blocks into pipeline (define edges, map inputs/outputs)
    5. Return pipeline for user approval
- [ ] Implement Builder Agent
  - System prompt: knows available APIs, code templates, block schema
  - Input: block spec (name, description, required I/O schema)
  - Output: new `BlockDefinition` + implementation code
  - Process:
    1. Receive spec from Orchestra
    2. Decide implementation strategy (API, scrape, or logic)
    3. Generate async Python function
    4. Validate against schema
    5. Register in block registry
- [ ] Implement agent communication protocol (Orchestra ↔ Builder)
- [ ] Add block gap detection (Orchestra identifies what's missing)

**Testing:**
- Orchestra: "Buy milk every Tuesday" → valid pipeline with correct blocks
- Orchestra: unknown task → identifies missing blocks, requests Builder
- Builder: given spec → generates valid block with correct schemas
- End-to-end: user request → Orchestra → Builder (if needed) → Pipeline → execution
- Test with mocked Claude API responses for deterministic testing
- Test with real Claude API for integration verification

```bash
pytest tests/test_agents/ -v
```

---

### PHASE 5: Remaining Tier 1 Blocks (30 total)
**Goal:** Implement all 30 Tier 1 blocks so hackathon demos work end-to-end.

**Blocks to implement (beyond the 10 from Phase 2):**

```
TRIGGERS:
  - trigger_file_upload      → Accept file via API endpoint
  - trigger_webhook          → FastAPI dynamic webhook route

PERCEIVE:
  - web_scrape_structured    → Extract specific fields from page
  - gemini_analyze_image     → Gemini Vision API
  - gemini_ocr               → Gemini text extraction from image
  - gemini_read_receipt      → Receipt photo → line items
  - social_hackernews_top    → HN API top stories
  - product_get_price        → Scrape price from product URL

THINK:
  - claude_analyze           → Deep analysis prompt
  - claude_recommend         → Recommendation with preferences
  - claude_categorize        → Classification prompt

ACT:
  - stripe_pay               → Stripe payment intent
  - email_send               → SendGrid API
  - commerce_place_order     → Mock order placement
  - code_run_python          → Sandboxed Python execution

COMMUNICATE:
  - elevenlabs_speak         → ElevenLabs TTS API
  - ask_user_confirm         → Pause pipeline, wait for user yes/no
  - present_summary_card     → Format data as summary response

REMEMBER:
  - memory_append            → Append to list in KV store
  - miro_add_node            → Add node to Miro board
  - miro_add_connection      → Connect two Miro nodes

CONTROL FLOW:
  - filter_threshold         → Value comparison (>, <, ==, etc.)
  - data_transform           → Reshape/map data fields
  - loop_for_each            → Iterate over list items
  - data_diff                → Compare old vs new data
```

**Testing:**
- Each block tested individually with realistic inputs
- Integration test: full pipeline for each demo scenario
- Demo scenario 1: "Track Bitcoin price and alert if below $60k"
- Demo scenario 2: "Summarize top HN posts every morning"
- Demo scenario 3: "Monitor competitor pricing and alert on changes"

```bash
pytest tests/test_blocks/ tests/test_integration/ -v
```

---

### PHASE 6: API Endpoints & WebSocket
**Goal:** Expose everything via REST API + real-time updates.

**Endpoints:**
```
POST   /api/chat                → Natural language → pipeline (via Orchestra)
GET    /api/pipelines           → List user's pipelines
POST   /api/pipelines           → Create pipeline directly
GET    /api/pipelines/{id}      → Get pipeline details
POST   /api/pipelines/{id}/run  → Execute pipeline
DELETE /api/pipelines/{id}      → Delete pipeline
GET    /api/pipelines/{id}/logs → Get execution logs

GET    /api/blocks              → List all blocks
GET    /api/blocks/{id}         → Get block details
POST   /api/blocks/search       → Search blocks by description

POST   /api/webhooks/{path}     → Incoming webhook trigger
POST   /api/upload              → File upload trigger

WS     /ws/execution/{id}       → Real-time execution updates
WS     /ws/chat                 → Streaming chat with Orchestra
```

**Testing:**
- API endpoint tests with httpx test client
- WebSocket connection and message flow tests
- End-to-end: POST /api/chat → pipeline created → execute → get results

```bash
pytest tests/test_api/ -v
```

---

### PHASE 7: Frontend (Next.js + React Flow)
**Goal:** Visual interface for creating and monitoring automations.

**Pages:**
1. **Chat page** — Text input: "What do you want to automate?"
   - Streaming response from Orchestra
   - Pipeline preview before execution
   - Approval flow (confirm/edit/reject)

2. **Pipeline visualizer** — React Flow DAG view
   - Blocks as nodes with category-colored borders
   - Edges showing data flow
   - Real-time execution status (running/done/error per block)
   - Click block to see inputs/outputs

3. **Dashboard** — Active automations list
   - Status (active/paused/error)
   - Last run time, next run time
   - Quick actions (run now, pause, delete)

4. **Block library** — Browse all available blocks
   - Filter by category
   - Search by description
   - View block details and I/O schemas

**Testing:**
- Component rendering tests (React Testing Library)
- WebSocket integration test (mock server)
- Visual regression tests for pipeline view

---

### PHASE 8: Tier 2 Blocks & Polish (if time allows)
**Goal:** Add 20 more impressive blocks and polish the experience.

**Tier 2 blocks:**
- `trigger_interval`, `trigger_content_change`
- `gemini_analyze_video`, `gemini_identify_product`
- `social_twitter_search`, `finance_stock_price`
- `weather_current`, `location_nearby_places`
- `claude_sentiment`, `claude_write`, `claude_plan`, `claude_score`
- `stripe_create_virtual_card`, `slack_send_message`, `calendar_create_event`
- `elevenlabs_speak_multilingual`, `generate_chart`
- `miro_create_timeline`, `miro_create_chart`, `memory_detect_pattern`
- `parallel_execute`, `try_catch`

**Polish:**
- Error messages and recovery
- Loading states and animations
- Voice output in demo
- Miro board visualization in demo

---

## Milestone Checkpoints

| Milestone | Phase | Success Criteria |
|-----------|-------|------------------|
| **M0: Skeleton** | 0 | FastAPI starts, pytest runs, all dirs exist |
| **M1: Type System** | 1 | 30 block definitions loaded, models validate, search works |
| **M2: Blocks Execute** | 2 | 10 blocks run individually, memory persists, schemas enforced |
| **M3: Pipelines Run** | 3 | 3-block linear pipeline executes, branching works, memory loads |
| **M4: Agents Think** | 4 | Orchestra decomposes "buy milk", Builder creates a block, end-to-end works |
| **M5: Full Tier 1** | 5 | All 30 Tier 1 blocks work, 3 demo scenarios pass |
| **M6: API Live** | 6 | All REST endpoints work, WebSocket streams execution |
| **M7: UI Works** | 7 | Chat → pipeline → visualize → execute loop works in browser |
| **M8: Demo Ready** | 8 | Tier 2 blocks, voice output, Miro viz, polished demo |

---

## Testing Strategy

### Unit Tests (every block, every model)
- Each block has a dedicated test file
- Tests use mocked external APIs (no real API calls in CI)
- Schema validation: valid inputs pass, invalid inputs rejected
- Edge cases: empty inputs, malformed data, timeouts

### Integration Tests (pipelines + agents)
- Multi-block pipelines execute correctly
- Orchestra produces valid pipelines for known inputs
- Builder generates functional blocks
- Memory persists across pipeline runs
- Template variables resolve correctly

### End-to-End Tests (demo scenarios)
- "Track Bitcoin price and alert if below $60k"
- "Summarize top HN posts every morning"
- "Monitor competitor pricing and alert on changes"
- "Order lunch every weekday under 15 euros"
- "Monitor Amazon for PS5 price drops below 400 euros"

### How to run tests
```bash
# All tests
pytest tests/ -v

# Specific phase
pytest tests/test_models.py -v          # Phase 1
pytest tests/test_blocks/ -v            # Phase 2 & 5
pytest tests/test_engine/ -v            # Phase 3
pytest tests/test_agents/ -v            # Phase 4
pytest tests/test_api/ -v               # Phase 6

# With coverage
pytest tests/ --cov=app --cov-report=term-missing

# Integration only
pytest tests/ -m integration -v
```

---

## Block Taxonomy Quick Reference

```
Category         Tier 1    Total    Organ
────────────────────────────────────────────
1. TRIGGER         4        14      APScheduler / FastAPI
2. PERCEIVE        8        55      Gemini + Web + APIs
3. THINK           5        22      Claude (Anthropic)
4. ACT             4        32      Stripe + Services
5. COMMUNICATE     4        20      ElevenLabs + UI
6. REMEMBER        5        23      Miro + KV Store
7. CONTROL FLOW    5        27      Logic Engine
────────────────────────────────────────────
TOTAL             35       193
```

### Tier 1 Blocks (Hackathon MVP — build these first)

**TRIGGERS:** trigger_cron, trigger_manual, trigger_file_upload, trigger_webhook
**PERCEIVE:** web_search, web_scrape, web_scrape_structured, gemini_analyze_image, gemini_ocr, gemini_read_receipt, social_hackernews_top, product_get_price
**THINK:** claude_decide, claude_summarize, claude_analyze, claude_recommend, claude_categorize
**ACT:** stripe_pay, email_send, commerce_place_order, code_run_python
**COMMUNICATE:** elevenlabs_speak, notify_in_app, ask_user_confirm, present_summary_card
**REMEMBER:** memory_read, memory_write, memory_append, miro_add_node, miro_add_connection
**CONTROL FLOW:** conditional_branch, filter_threshold, data_transform, loop_for_each, data_diff

---

## Key Design Decisions

1. **Blocks are DATA, not code** — Block definitions are JSON schemas stored in DB. A generic executor interprets them. This means Builder Agent can create new blocks without writing new node functions.

2. **LangGraph for orchestration** — Provides DAG execution, state management, checkpointing, and conditional routing out of the box.

3. **Two-agent architecture** — Orchestra knows WHAT blocks exist (registry). Builder knows HOW to create new ones (APIs + code). Neither knows the other's domain deeply.

4. **Template variables** — Block inputs can reference other blocks' outputs via `{{node_id.field}}`, memory via `{{memory.key}}`, and trigger data via `{{trigger.field}}`.

5. **Mock-first for risky blocks** — Stripe payments, order placement, and other irreversible actions start as mocks with approval flow, then graduate to real implementations.

6. **Shared context bus** — All blocks read from and write to a shared context dict. LangGraph reducers merge updates automatically.

---

## Environment Variables Required

```env
# AI
OPENAI_API_KEY=sk-...
GOOGLE_GEMINI_API_KEY=...

# Voice
ELEVENLABS_API_KEY=...

# Payments
STRIPE_SECRET_KEY=sk_test_...

# Communication
SENDGRID_API_KEY=...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...

# Web Search
SERPER_API_KEY=...

# Visual Memory
MIRO_API_TOKEN=...
MIRO_BOARD_ID=...

# Database
DATABASE_URL=sqlite:///./agentflow.db
```

---

## Current Status

- [x] Phase 0: Project scaffolding — DONE
- [x] Phase 1: Core data models & block registry — DONE (35 blocks, 28 tests)
- [x] Phase 2: Block executor & first 10 blocks — DONE (10 implementations, 53 tests)
- [x] Phase 3: Pipeline engine (LangGraph) — DONE (linear, branching, memory, 59 tests)
- [x] Phase 4: Orchestra & Builder agents — DONE (decompose, create, e2e, 77 tests)
- [x] Phase 5: Remaining Tier 1 blocks — DONE (35 total implementations, 89 tests)
- [x] Phase 6: API endpoints — DONE (chat, pipelines, blocks, webhooks, upload)
- [x] Phase 7: Frontend — DONE (Next.js 16 + React Flow + Tailwind dark theme, 5 routes)
- [ ] Phase 8: Tier 2 blocks & polish

---

## Reference Documents

- `Kai/blank.txt` — Original AgentFlow spec (vision, block registry, demo scenarios)
- `Magnus/ARCHITECTURE.md` — LangGraph architecture (state, executor, graph builder)
- This file — Implementation plan, phases, testing, milestones

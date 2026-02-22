# AgentFlow — System Overview for Integration

> Written for: teammate building the execution chains + Docker package
> Goal: Understand how our system works so you can build on top of it and we can merge cleanly.

---

## What the System Does (30-second version)

User types: *"Check Bitcoin price every hour and alert me if it drops below $60k"*

Our system:
1. **Orchestra Agent** (Claude) reads the request and produces a pipeline definition (JSON) — a list of blocks wired together as a DAG.
2. The pipeline is stored in the DB.
3. The **Pipeline Engine** (LangGraph) executes the DAG — running each block in order, passing outputs between nodes.
4. The **Frontend** visualizes the DAG live and shows real-time execution progress.

---

## Architecture Map

```
User (natural language)
        ↓
  POST /api/chat
        ↓
  OrchestraAgent.decompose()    ← Claude API
        ↓
  Pipeline JSON (nodes + edges)
        ↓
  POST /api/pipelines            ← saves to SQLite
        ↓ (trigger fires)
  PipelineRunner.run()
        ↓
  GraphBuilder.build_graph()     ← builds LangGraph DAG
        ↓
  compiled.astream()             ← executes node by node
        ↓
  BlockExecutor.execute()        ← per-node: resolves templates → calls implementation
        ↓
  WebSocket broadcasts           ← real-time frontend updates
        ↓
  ExecutionResult stored to DB
```

---

## Core Data Structures

### Pipeline (the central object)

```python
# app/models/pipeline.py

Pipeline:
  id: str                      # UUID
  user_intent: str             # original NL request
  trigger: TriggerConfig       # when/how it starts
  nodes: list[PipelineNode]    # the blocks
  edges: list[PipelineEdge]    # connections between blocks
  memory_keys: list[str]       # keys this pipeline reads/writes
  status: PipelineStatus       # CREATED | APPROVED | RUNNING | PAUSED | COMPLETED | FAILED

TriggerConfig:
  type: TriggerType            # CRON | INTERVAL | MANUAL | WEBHOOK | FILE_UPLOAD | EVENT
  schedule: str | None         # cron expression e.g. "0 9 * * MON-FRI"
  interval_seconds: int | None # e.g. 3600
  webhook_path: str | None     # e.g. "/hooks/my-endpoint"
```

### PipelineNode — a single block in the graph

```python
PipelineNode:
  id: str                      # unique within this pipeline, e.g. "node_1"
  block_id: str                # references BlockDefinition, e.g. "web_search"
  inputs: dict                 # template-mapped inputs — see "Template Variables" below
  config: dict                 # static config (e.g. API keys, model settings)
```

### PipelineEdge — connection between two nodes

```python
PipelineEdge:
  from_node: str               # node_id of source
  to_node: str                 # node_id of destination
  condition: str | None        # optional routing expression e.g. "{{node_2.branch}} == 'true'"
```

Edges are what the frontend renders as arrows. They also define execution order in LangGraph.

### BlockDefinition — a reusable block type

```python
BlockDefinition:
  id: str                      # snake_case, unique e.g. "claude_summarize"
  name: str
  description: str
  category: BlockCategory      # TRIGGER | PERCEIVE | THINK | ACT | COMMUNICATE | REMEMBER | CONTROL
  organ: BlockOrgan            # CLAUDE | GEMINI | ELEVENLABS | STRIPE | MIRO | SYSTEM | WEB | EMAIL
  input_schema: dict           # JSON Schema for inputs
  output_schema: dict          # JSON Schema for outputs
  api_type: str                # "real" | "mock"
  tier: int                    # 1 = MVP, 2 = full, 3 = future
  examples: list[dict]
```

Block definitions live in `/app/blocks/definitions/*.json` (35 blocks currently loaded).

### ExecutionResult

```python
ExecutionResult:
  pipeline_id: str
  run_id: str                  # UUID for this specific run
  status: ExecutionStatus      # PENDING | RUNNING | COMPLETED | FAILED
  shared_context: dict         # {node_id: {output_field: value}}  ← all outputs accumulated here
  node_results: list[NodeResult]
  errors: list[str]

NodeResult:
  node_id: str
  block_id: str
  status: ExecutionStatus
  output: dict                 # block's return dict
  error: str | None
  duration_ms: int
```

---

## Template Variables (how nodes pass data to each other)

Block inputs can reference prior outputs using double-brace templates:

```
{{node_1.search_results}}     → output field "search_results" from node_1
{{memory.my_key}}             → value from persistent memory store
{{trigger.webhook_payload}}   → data that triggered this run
```

The `BlockExecutor` resolves all templates before calling the implementation.
This is how the DAG "wires" data between blocks.

---

## How the Visualization is So Accurate

The frontend DAG (React Flow) is built directly from the `nodes` and `edges` arrays in the Pipeline.

- Each `PipelineNode` becomes a React Flow node.
- Each `PipelineEdge` becomes a React Flow edge (arrow).
- Node layout uses **dagre** (auto-layout library) to position nodes in a top-down graph.
- Node colors are determined by `BlockCategory` (e.g. TRIGGER = blue, THINK = purple, ACT = red).
- During execution, node status comes via WebSocket: `node_complete` messages update color (green = done, red = failed, pulsing = running).

**The connection accuracy comes from two things:**
1. Orchestra Agent (Claude) maps inputs/outputs using the block schemas — it knows what each block outputs and what the next block needs.
2. Template variables create explicit data links that the executor follows.

---

## How Triggers Work

### Trigger Types

| Type | How it fires |
|------|-------------|
| `manual` | User clicks "Run" in the UI → POST `/api/pipelines/{id}/run` |
| `cron` | APScheduler fires at cron expression (e.g. `0 9 * * *`) |
| `interval` | APScheduler fires every N seconds |
| `webhook` | Incoming HTTP POST to `/api/webhooks/{path}` |
| `file_upload` | File posted to `/api/upload` endpoint |
| `event` | Not implemented yet |

### Scheduling (cron/interval)

When a pipeline is saved via `POST /api/pipelines`, if the trigger is `cron` or `interval`:
1. `schedule_pipeline(pipeline_id, schedule, interval_seconds)` is called.
2. This registers an APScheduler job in `agentflow_jobs.db` (separate SQLite DB for persistence).
3. On server restart, `rehydrate_schedules()` re-registers all saved jobs.
4. When the job fires, `_execute_pipeline_job(pipeline_id)` is called — this loads the pipeline and calls `PipelineRunner.run()`.

Relevant file: `app/engine/scheduler.py`

### Webhook Triggers

`POST /api/webhooks/{path}`:
1. Looks up pipeline where `trigger.webhook_path == path`.
2. Calls `PipelineRunner.run(pipeline, trigger_data={"payload": body, ...})`.
3. The `trigger_data` is injected into the first block's context.

---

## How Execution Works (Step by Step)

### 1. Graph Building (`app/engine/graph_builder.py`)

```python
build_graph(pipeline, registry) → compiled LangGraph StateGraph
```

- Finds start nodes (no incoming edges) and end nodes (no outgoing edges).
- For each node, creates a closure function that: resolves templates → executes block → updates shared_context.
- Wires: `START → start_nodes → ... → end_nodes → END`
- Conditional edges: if an edge has `condition`, a router reads the branch output and routes accordingly.

### 2. LangGraph State (`app/engine/state.py`)

LangGraph uses a TypedDict with reducers that accumulate state across nodes:

```python
PipelineState:
  shared_context: dict      # merge_dicts reducer — always grows, never overwrites
  execution_log: list       # append_list reducer — ordered record of executed nodes
  errors: list              # append_list reducer — any errors
  memory: dict              # loaded at start, not updated during run
  pipeline_def: dict        # full pipeline definition
  trigger_data: dict        # trigger input (webhook payload, file info, etc.)
  checkpoint: dict          # previous run's shared_context (for diff-based watching)
```

### 3. Block Execution (`app/blocks/executor.py`)

Per node:
1. Resolve template variables in `node.inputs` using `shared_context`, `memory`, `trigger_data`.
2. Coerce types (LLMs often return strings when an int is expected — we fix this).
3. Look up implementation by `block_id`.
4. `await impl_function(resolved_inputs)` → `output_dict`.
5. Store `shared_context[node_id] = output_dict`.
6. Return `NodeResult`.

### 4. Real-time Updates (WebSocket)

The runner broadcasts to two channels:
- `/ws/execution/{run_id}` — for tracking a specific run
- `/ws/execution/{pipeline_id}` — so clients can subscribe before knowing run_id

Messages:
```json
{"type": "run_start", "run_id": "...", "pipeline_id": "..."}
{"type": "node_complete", "node_id": "node_1", "status": "completed", "output": {...}}
{"type": "run_complete", "status": "completed", "result": {...}}
{"type": "run_error", "error": "..."}
```

---

## API Endpoints Summary

```
POST /api/chat                    NL → pipeline (via Orchestra Agent)
GET  /api/pipelines               List all pipelines
POST /api/pipelines               Save pipeline + auto-schedule if cron/interval
GET  /api/pipelines/{id}          Get pipeline definition
POST /api/pipelines/{id}/run      Execute pipeline now
DEL  /api/pipelines/{id}          Delete + unschedule
GET  /api/pipelines/{id}/logs     Execution history

GET  /api/blocks                  List all block definitions
POST /api/blocks/search           Search blocks by NL query

POST /api/webhooks/{path}         Incoming webhook trigger
POST /api/upload                  File upload trigger

GET  /api/schedules               Active scheduled jobs

WS   /ws/execution/{id}           Real-time updates (run_id or pipeline_id)
```

---

## Database Schema (SQLite)

```sql
-- Main app DB: agentflow.db

pipelines (
  id TEXT PRIMARY KEY,
  user_intent TEXT,
  definition TEXT,      -- JSON: full Pipeline object
  status TEXT,
  created_at TEXT,
  updated_at TEXT
)

execution_logs (
  id INTEGER PRIMARY KEY,
  pipeline_id TEXT,
  run_id TEXT,
  node_id TEXT,
  status TEXT,
  output_data TEXT,     -- JSON
  error TEXT,
  finished_at TEXT
)

chat_sessions (
  id TEXT PRIMARY KEY,
  history TEXT,         -- JSON: [{role, content}]
  updated_at TEXT
)

memory_store (
  namespace TEXT,
  key TEXT,
  value TEXT,           -- JSON
  updated_at TEXT
)

-- Separate DB for scheduling persistence: agentflow_jobs.db
-- Managed by APScheduler, do not touch manually
```

---

## How Orchestra Builds Accurate Pipelines

The Orchestra Agent (Claude with a detailed system prompt) receives:
- The user's NL request
- The full block registry (all 35 block IDs, descriptions, input/output schemas)

It outputs a JSON object with:
```json
{
  "type": "pipeline",
  "trigger_type": "interval",
  "trigger": {"type": "interval", "interval_seconds": 3600},
  "nodes": [
    {"id": "node_1", "block_id": "perceive_web_search", "inputs": {"query": "Bitcoin price"}},
    {"id": "node_2", "block_id": "think_claude_decide", "inputs": {"data": "{{node_1.results}}", "threshold": 60000}},
    {"id": "node_3", "block_id": "communicate_notify_in_app", "inputs": {"message": "{{node_2.decision}}"}}
  ],
  "edges": [
    {"from_node": "node_1", "to_node": "node_2"},
    {"from_node": "node_2", "to_node": "node_3"}
  ],
  "memory_keys": []
}
```

The accuracy comes from Claude understanding the block schemas and correctly mapping `{{node_id.field}}` to the actual output fields of each block.

---

## Directory Structure (Key Files)

```
Kai/
├── app/
│   ├── main.py                           FastAPI entry point
│   ├── config.py                         Env vars / settings
│   │
│   ├── models/
│   │   ├── block.py                      BlockDefinition, BlockCategory, BlockOrgan
│   │   ├── pipeline.py                   Pipeline, PipelineNode, PipelineEdge, TriggerConfig
│   │   └── execution.py                  ExecutionResult, NodeResult, ExecutionStatus
│   │
│   ├── blocks/
│   │   ├── registry.py                   BlockRegistry (load, get, search, register)
│   │   ├── executor.py                   BlockExecutor (template resolution + execution)
│   │   ├── loader.py                     Loads JSON definitions from disk
│   │   ├── definitions/                  35 block definition JSON files
│   │   └── implementations/              Actual async Python implementations
│   │       ├── triggers/
│   │       ├── perceive/
│   │       ├── think/
│   │       ├── act/
│   │       ├── communicate/
│   │       ├── remember/
│   │       └── control_flow/
│   │
│   ├── agents/
│   │   ├── orchestra.py                  Orchestra Agent (NL → Pipeline JSON)
│   │   └── builder.py                    Builder Agent (spec → new BlockDefinition + code)
│   │
│   ├── engine/
│   │   ├── state.py                      LangGraph PipelineState TypedDict
│   │   ├── graph_builder.py              Pipeline → compiled LangGraph DAG
│   │   ├── runner.py                     Execute DAG + broadcast WebSocket updates
│   │   └── scheduler.py                  APScheduler cron/interval management
│   │
│   ├── memory/
│   │   ├── store.py                      SQLite-backed key-value store
│   │   └── manager.py                    Read/write/search memory
│   │
│   └── api/
│       ├── pipelines.py                  CRUD + run endpoints
│       ├── chat.py                       NL → pipeline endpoint
│       ├── blocks.py                     Block registry endpoints
│       ├── webhooks.py                   Incoming webhook triggers
│       └── activity.py                   Execution logs + notifications
│
└── frontend/src/
    ├── app/
    │   ├── chat/page.tsx                 Main chat UI (single-turn + multi-turn + DAG preview)
    │   ├── dashboard/page.tsx            Active pipelines list
    │   ├── pipelines/[id]/page.tsx       Pipeline detail + run + visualization
    │   └── blocks/page.tsx              Block library browser
    ├── lib/
    │   ├── types.ts                      All TypeScript interfaces
    │   ├── api.ts                        API client (fetch wrappers)
    │   └── constants.ts                 Category colors, labels, etc.
    └── components/
        └── pipeline/PipelineResultDisplay.tsx
```

---

## How to Run the System

```bash
# Backend (port 8000)
cd Kai/
python -m uvicorn app.main:app --reload

# Frontend (port 3000)
cd Kai/frontend/
npm run dev
```

Required env vars (`.env` in Kai/):
```
OPENAI_API_KEY=sk-...
GOOGLE_GEMINI_API_KEY=...
ELEVENLABS_API_KEY=...
STRIPE_SECRET_KEY=sk_test_...
SENDGRID_API_KEY=...
SERPER_API_KEY=...
MIRO_API_TOKEN=...
MIRO_BOARD_ID=...
DATABASE_URL=sqlite:///./agentflow.db
```

---

## Integration Points for Your Docker/Execution Package

When you build the execution chains and Docker package, here's what to hook into:

### Option A — Replace/extend `PipelineRunner`
File: `app/engine/runner.py`
Method: `async def run(pipeline, trigger_data, broadcast_updates) -> ExecutionResult`
This is where execution happens. You can:
- Wrap it to run in a Docker container
- Intercept and redirect block execution to your worker pool
- Add sandboxing per-node

### Option B — Replace/extend `BlockExecutor`
File: `app/blocks/executor.py`
Method: `async def execute(block, inputs, shared_context, memory, node_id) -> NodeResult`
This is where individual blocks run. You can:
- Redirect execution to a Docker sidecar
- Add timeouts, resource limits, audit logging per block

### Option C — Add a new execution backend
Register your Docker executor as an alternative `organ` type (alongside `CLAUDE`, `GEMINI`, etc.) and handle it in the executor dispatch logic.

### Key things to preserve for the frontend to keep working:
1. **WebSocket message format** — `node_complete`, `run_complete`, etc. (frontend parses these)
2. **`shared_context` structure** — `{node_id: {output_field: value}}` (frontend displays this)
3. **`ExecutionResult` schema** — returned by `POST /api/pipelines/{id}/run`
4. **Block `input_schema` / `output_schema`** — used for template resolution and visualization

---

## Tests

```bash
pytest tests/ -v                         # all 89 tests
pytest tests/test_api/ -v               # API layer
pytest tests/test_engine/ -v            # LangGraph engine
pytest tests/test_agents/ -v            # Orchestra + Builder
pytest tests/test_blocks/ -v            # Block implementations
```

---

*Last updated: 2026-02-21*

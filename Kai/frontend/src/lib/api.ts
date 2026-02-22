import type {
  ChatRequest,
  ChatResponse,
  BlockDefinition,
  PipelineListItem,
  PipelineNode,
  PipelineEdge,
  TriggerConfig,
  ExecutionResult,
  ExecutionRun,
  ExecutionDetail,
  Notification,
  ScheduleItem,
} from "./types";
import { streamSSE, type SSEEventHandler } from "./sse";

const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "http://localhost:8000"
).replace(/\/$/, "");

function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, init);
}

export async function sendChat(req: ChatRequest): Promise<ChatResponse> {
  const payload: Record<string, unknown> = {
    message: req.message,
    auto_execute: req.auto_execute,
  };
  if (req.session_id) payload.session_id = req.session_id;

  const res = await apiFetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Chat failed: ${res.status}`);
  return res.json();
}

// ── Intent Clarification ──
export async function clarifyIntent(
  message: string,
  history: Array<{ role: string; content: string }>
): Promise<{ ready: boolean; refined_intent?: string; question?: string }> {
  const res = await apiFetch("/api/clarify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
  });
  if (!res.ok) throw new Error(`Clarify failed: ${res.status}`);
  return res.json();
}

// ── Thinker Streaming ──
export function createAgentStream(
  intent: string,
  userId: string,
  onEvent: SSEEventHandler,
  onError?: (error: Error) => void,
  onComplete?: () => void
): Promise<void> {
  return streamSSE(
    "/api/create-agent/stream",
    { intent, user_id: userId },
    onEvent,
    onError,
    onComplete
  );
}

export async function listPipelines(): Promise<PipelineListItem[]> {
  const res = await apiFetch("/api/pipelines");
  if (!res.ok) throw new Error(`List pipelines failed: ${res.status}`);
  return res.json();
}

export async function getPipeline(id: string): Promise<Record<string, unknown>> {
  const res = await apiFetch(`/api/pipelines/${id}`);
  if (!res.ok) throw new Error(`Get pipeline failed: ${res.status}`);
  return res.json();
}

export async function runPipeline(id: string): Promise<ExecutionResult> {
  const res = await apiFetch(`/api/pipelines/${id}/run`, { method: "POST" });
  if (!res.ok) throw new Error(`Run pipeline failed: ${res.status}`);
  return res.json();
}

export async function deletePipeline(id: string): Promise<void> {
  const res = await apiFetch(`/api/pipelines/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Delete pipeline failed: ${res.status}`);
}

interface SavePipelinePayload {
  id: string;
  user_intent: string;
  trigger: TriggerConfig;
  nodes: PipelineNode[];
  edges: PipelineEdge[];
}

export async function savePipeline(pipeline: SavePipelinePayload): Promise<{ id: string }> {
  const res = await apiFetch("/api/pipelines", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pipeline }),
  });
  if (!res.ok) throw new Error(`Save pipeline failed: ${res.status}`);
  return res.json();
}

export async function listBlocks(category?: string): Promise<BlockDefinition[]> {
  const url = category ? `/api/blocks?category=${category}` : "/api/blocks";
  const res = await apiFetch(url);
  if (!res.ok) throw new Error(`List blocks failed: ${res.status}`);
  return res.json();
}

export async function searchBlocks(query: string): Promise<BlockDefinition[]> {
  const res = await apiFetch("/api/blocks/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error(`Search blocks failed: ${res.status}`);
  return res.json();
}

export async function listExecutions(limit = 50): Promise<ExecutionRun[]> {
  const res = await apiFetch(`/api/executions?limit=${limit}`);
  if (!res.ok) throw new Error(`List executions failed: ${res.status}`);
  return res.json();
}

export async function getExecution(runId: string): Promise<ExecutionDetail> {
  const res = await apiFetch(`/api/executions/${runId}`);
  if (!res.ok) throw new Error(`Get execution failed: ${res.status}`);
  return res.json();
}

export async function listNotifications(limit = 50): Promise<Notification[]> {
  const res = await apiFetch(`/api/notifications?limit=${limit}`);
  if (!res.ok) throw new Error(`List notifications failed: ${res.status}`);
  return res.json();
}

export async function markNotificationRead(id: number): Promise<void> {
  const res = await apiFetch(`/api/notifications/${id}/read`, { method: "POST" });
  if (!res.ok) throw new Error(`Mark notification read failed: ${res.status}`);
}

export async function listSchedules(): Promise<ScheduleItem[]> {
  const res = await apiFetch("/api/schedules");
  if (!res.ok) throw new Error(`List schedules failed: ${res.status}`);
  return res.json();
}

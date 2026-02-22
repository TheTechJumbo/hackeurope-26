"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send,
  X,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  HelpCircle,
  RotateCcw,
  LayoutDashboard,
  FlaskConical,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { sendChat, savePipeline, runPipeline } from "@/lib/api";
import { PipelineGraph } from "@/components/pipeline/PipelineGraph";
import { PipelineResultDisplay } from "@/components/pipeline/PipelineResultDisplay";
import { ThinkingPanel } from "@/components/pipeline/ThinkingPanel";
import { setBlockMetadata, getBlockMeta } from "@/lib/utils";
import { listBlocks } from "@/lib/api";
import { CATEGORY_BG } from "@/lib/constants";
import type { ChatResponse, ExecutionResult } from "@/lib/types";

type Phase = "idle" | "loading" | "preview" | "clarifying" | "executing" | "complete" | "error" | "saved";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  pipeline?: ChatResponse;
  result?: ExecutionResult;
  error?: string;
  clarification?: { message: string; questions: string[] };
}

interface State {
  phase: Phase;
  messages: Message[];
  currentPipeline: ChatResponse | null;
  nodeStatuses: Record<string, string>;
  sessionId: string | null;
  showThinkingPanel: boolean;
}

type Action =
  | { type: "SEND_MESSAGE"; content: string }
  | { type: "RECEIVE_PIPELINE"; pipeline: ChatResponse }
  | { type: "RECEIVE_CLARIFICATION"; message: string; questions: string[]; sessionId: string }
  | { type: "START_EXECUTION" }
  | { type: "UPDATE_NODE_STATUS"; nodeId: string; status: string }
  | { type: "EXECUTION_COMPLETE"; result: ExecutionResult }
  | { type: "ERROR"; error: string }
  | { type: "REJECT" }
  | { type: "RESET" }
  | { type: "SAVED_TO_DASHBOARD" };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "SEND_MESSAGE":
      return {
        ...state,
        phase: "loading",
        messages: [
          ...state.messages,
          { id: Date.now().toString(), role: "user", content: action.content },
        ],
      };
    case "RECEIVE_PIPELINE":
      return {
        ...state,
        phase: "preview",
        currentPipeline: action.pipeline,
        nodeStatuses: {},
        sessionId: null,
        showThinkingPanel: true,
        messages: [
          ...state.messages,
          {
            id: Date.now().toString(),
            role: "assistant",
            content: `I'll create a pipeline with ${action.pipeline.nodes.length} blocks to: "${action.pipeline.user_intent}"`,
            pipeline: action.pipeline,
          },
        ],
      };
    case "RECEIVE_CLARIFICATION":
      return {
        ...state,
        phase: "clarifying",
        sessionId: action.sessionId,
        messages: [
          ...state.messages,
          {
            id: Date.now().toString(),
            role: "assistant",
            content: action.message,
            clarification: { message: action.message, questions: action.questions },
          },
        ],
      };
    case "START_EXECUTION":
      return { ...state, phase: "executing", nodeStatuses: {} };
    case "UPDATE_NODE_STATUS":
      return {
        ...state,
        nodeStatuses: { ...state.nodeStatuses, [action.nodeId]: action.status },
      };
    case "EXECUTION_COMPLETE": {
      const lastMsg = state.messages[state.messages.length - 1];
      const updatedMessages = state.messages.slice(0, -1);
      updatedMessages.push({ ...lastMsg, result: action.result });
      const allDone: Record<string, string> = {};
      state.currentPipeline?.nodes.forEach((n) => {
        allDone[n.id] = action.result.status === "completed" ? "completed" : "failed";
      });
      return {
        ...state,
        phase: "complete",
        messages: updatedMessages,
        nodeStatuses: allDone,
      };
    }
    case "ERROR":
      return {
        ...state,
        phase: "error",
        showThinkingPanel: false,
        messages: [
          ...state.messages,
          {
            id: Date.now().toString(),
            role: "assistant",
            content: action.error,
            error: action.error,
          },
        ],
      };
    case "SAVED_TO_DASHBOARD":
      return { ...state, phase: "saved" };
    case "REJECT":
    case "RESET":
      return {
        ...state,
        phase: "idle",
        currentPipeline: null,
        nodeStatuses: {},
        sessionId: null,
        showThinkingPanel: false,
      };
    default:
      return state;
  }
}

const INITIAL_STATE: State = {
  phase: "idle",
  messages: [],
  currentPipeline: null,
  nodeStatuses: {},
  sessionId: null,
  showThinkingPanel: false,
};

export default function ChatPage() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const [input, setInput] = useState("");
  const [blocksLoaded, setBlocksLoaded] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pipelineSavedRef = useRef(false);
  const router = useRouter();

  // Load block metadata on mount
  useEffect(() => {
    listBlocks().then((blocks) => {
      setBlockMetadata(blocks);
      setBlocksLoaded(true);
    }).catch(() => setBlocksLoaded(true));
  }, []);

  // Auto-scroll to bottom (only for messages view)
  useEffect(() => {
    if (!state.showThinkingPanel) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [state.messages, state.phase, state.showThinkingPanel]);

  // Cleanup WS on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  const connectWebSocket = useCallback((runId: string) => {
    const backendUrl = (process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000").replace(/^http/, "ws");
    const ws = new WebSocket(`${backendUrl}/ws/execution/${runId}`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "node_complete") {
          dispatch({ type: "UPDATE_NODE_STATUS", nodeId: data.node_id, status: "completed" });
        } else if (data.type === "node_start") {
          dispatch({ type: "UPDATE_NODE_STATUS", nodeId: data.node_id, status: "running" });
        }
      } catch { /* ignore non-JSON messages like pong */ }
    };

    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 30000);

    ws.onclose = () => clearInterval(pingInterval);

    return ws;
  }, []);

  const handleSend = useCallback(async () => {
    const message = input.trim();
    if (!message || state.phase === "loading") return;

    setInput("");
    pipelineSavedRef.current = false;
    dispatch({ type: "SEND_MESSAGE", content: message });

    try {
      const response = await sendChat({
        message,
        auto_execute: false,
        session_id: state.sessionId || undefined,
      });

      if (response.response_type === "clarification") {
        dispatch({
          type: "RECEIVE_CLARIFICATION",
          message: response.clarification_message || "I need a bit more detail.",
          questions: response.questions?.length ? response.questions : [response.clarification_message || ""],
          sessionId: response.session_id || state.sessionId || "",
        });
        return;
      }

      const nodes = (response.nodes || []).map((n) => ({
        ...n,
        config: n.config || {},
      }));
      const edges = (response.edges || []).map((e) => ({
        from_node: (e as any).from_node ?? (e as any).from,
        to_node: (e as any).to_node ?? (e as any).to,
        condition: (e as any).condition ?? null,
      }));

      dispatch({
        type: "RECEIVE_PIPELINE",
        pipeline: {
          ...response,
          nodes,
          edges,
          user_intent: response.user_intent || message,
        },
      });
    } catch (error) {
      dispatch({
        type: "ERROR",
        error: error instanceof Error
          ? error.message
          : "Failed to process your request. Is the backend running?",
      });
    }
  }, [input, state.phase, state.sessionId, state.messages]);

  const buildSavePayload = useCallback(() => {
    const p = state.currentPipeline!;
    return {
      id: p.pipeline_id,
      user_intent: p.user_intent,
      trigger: p.trigger,
      nodes: p.nodes,
      edges: p.edges,
    };
  }, [state.currentPipeline]);

  const handleExecute = useCallback(async () => {
    if (!state.currentPipeline) return;
    dispatch({ type: "START_EXECUTION" });

    try {
      const saved = await savePipeline(buildSavePayload());
      pipelineSavedRef.current = true;

      connectWebSocket(saved.id);

      const result = await runPipeline(saved.id);
      dispatch({ type: "EXECUTION_COMPLETE", result });
    } catch {
      dispatch({
        type: "EXECUTION_COMPLETE",
        result: {
          pipeline_id: state.currentPipeline.pipeline_id,
          run_id: "error",
          status: "failed",
          shared_context: {},
          node_results: [],
          errors: ["Execution failed. Check that the backend is running."],
        },
      });
    }
  }, [state.currentPipeline, connectWebSocket, buildSavePayload]);

  const handleAddToDashboard = useCallback(async () => {
    if (!state.currentPipeline) return;

    try {
      if (!pipelineSavedRef.current) {
        await savePipeline(buildSavePayload());
      }
      dispatch({ type: "SAVED_TO_DASHBOARD" });
    } catch {
      dispatch({ type: "ERROR", error: "Failed to save pipeline." });
    }
  }, [state.currentPipeline, buildSavePayload]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isInputDisabled = state.phase === "loading" || state.phase === "executing";
  const showSplitView = state.showThinkingPanel && state.currentPipeline && blocksLoaded;
  const lastMessage = state.messages[state.messages.length - 1];
  const executionResult = lastMessage?.result;

  return (
    <div className="flex flex-col h-screen">
      {/* Header with user intent when in split view */}
      {showSplitView ? (
        <div className="border-b border-gray-800 px-6 py-3 flex items-center gap-3 flex-shrink-0">
          <Sparkles className="w-4 h-4 text-blue-400 flex-shrink-0" />
          <span className="text-sm text-gray-300 truncate flex-1">
            {state.currentPipeline!.user_intent}
          </span>
          <button
            onClick={() => dispatch({ type: "RESET" })}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            Reset
          </button>
        </div>
      ) : (
        <div className="border-b border-gray-800 px-6 py-4 flex-shrink-0">
          <h1 className="text-lg font-semibold">Chat</h1>
          <p className="text-sm text-gray-500">Describe what you want to automate</p>
        </div>
      )}

      {/* Split view: ThinkingPanel + PipelineGraph */}
      {showSplitView ? (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 flex overflow-hidden">
            {/* Left: Thinking Panel */}
            <div className="w-[40%] border-r border-gray-800 flex flex-col overflow-hidden">
              <ThinkingPanel pipeline={state.currentPipeline!} isActive={true} />
            </div>

            {/* Right: Pipeline Graph */}
            <div className="flex-1 flex flex-col overflow-hidden">
              <PipelineGraph
                nodes={state.currentPipeline!.nodes}
                edges={state.currentPipeline!.edges}
                nodeStatuses={state.nodeStatuses}
                fullHeight
              />
            </div>
          </div>

          {/* Bottom bar: Approval / Executing / Result */}
          <div className="border-t border-gray-800 flex-shrink-0">
            {state.phase === "preview" && (
              <div className="px-6 py-3 flex items-center gap-3">
                <button
                  onClick={handleAddToDashboard}
                  className="flex items-center gap-1.5 px-5 py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-lg transition-colors"
                >
                  <LayoutDashboard className="w-3.5 h-3.5" />
                  Add to Dashboard
                </button>
                <button
                  onClick={handleExecute}
                  className="flex items-center gap-1.5 px-4 py-2 border border-gray-600 hover:border-gray-500 text-gray-300 hover:text-white text-sm rounded-lg transition-colors"
                >
                  <FlaskConical className="w-3.5 h-3.5" />
                  Test Run
                </button>
                <button
                  onClick={() => dispatch({ type: "REJECT" })}
                  className="flex items-center gap-1.5 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm rounded-lg transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                  Reject
                </button>
                <span className="text-xs text-gray-500 ml-auto">
                  {state.currentPipeline!.nodes.length} blocks &middot;{" "}
                  {state.currentPipeline!.edges.length} edges
                </span>
              </div>
            )}

            {state.phase === "executing" && (
              <div className="px-6 py-3 flex items-center gap-2 text-blue-400 text-sm">
                <Loader2 className="w-4 h-4 animate-spin" />
                Running pipeline...
              </div>
            )}

            {executionResult && state.phase === "complete" && (
              <div className="px-6 py-3">
                <div
                  className={`rounded-lg p-4 border ${
                    executionResult.status === "completed"
                      ? "bg-green-500/10 border-green-500/30"
                      : "bg-red-500/10 border-red-500/30"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-2">
                    {executionResult.status === "completed" ? (
                      <CheckCircle2 className="w-4 h-4 text-green-400" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-red-400" />
                    )}
                    <span
                      className={`text-sm font-medium ${
                        executionResult.status === "completed" ? "text-green-400" : "text-red-400"
                      }`}
                    >
                      {executionResult.status === "completed" ? "Test run completed" : "Test run failed"}
                    </span>
                  </div>

                  {executionResult.errors.length > 0 && (
                    <div className="text-xs text-red-300 mb-2">
                      {executionResult.errors.join(", ")}
                    </div>
                  )}

                  {Object.keys(executionResult.shared_context).length > 0 && (
                    <PipelineResultDisplay
                      sharedContext={executionResult.shared_context as Record<string, Record<string, unknown>>}
                      errors={executionResult.errors}
                    />
                  )}
                </div>

                <div className="mt-3 flex items-center gap-3">
                  <button
                    onClick={handleAddToDashboard}
                    className="flex items-center gap-1.5 px-5 py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    <LayoutDashboard className="w-3.5 h-3.5" />
                    Add to Dashboard
                  </button>
                  <button
                    onClick={() => dispatch({ type: "RESET" })}
                    className="flex items-center gap-1.5 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm rounded-lg transition-colors"
                  >
                    Discard
                  </button>
                </div>
              </div>
            )}

            {state.phase === "saved" && (
              <div className="px-6 py-3">
                <div className="rounded-lg p-4 border bg-green-500/10 border-green-500/30">
                  <div className="flex items-center gap-2 mb-2">
                    <CheckCircle2 className="w-4 h-4 text-green-400" />
                    <span className="text-sm font-medium text-green-400">
                      Pipeline added to dashboard
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-2">
                    <button
                      onClick={() => router.push("/dashboard")}
                      className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
                    >
                      <LayoutDashboard className="w-3.5 h-3.5" />
                      Go to Dashboard
                    </button>
                    <button
                      onClick={() => dispatch({ type: "RESET" })}
                      className="text-xs text-gray-400 hover:text-gray-300 transition-colors"
                    >
                      Create another
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        /* Normal messages view */
        <>
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
            {state.messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <Sparkles className="w-12 h-12 text-blue-500/50 mb-4" />
                <h2 className="text-xl font-semibold text-gray-300 mb-2">
                  What do you want to automate?
                </h2>
                <p className="text-gray-500 max-w-md">
                  Describe your automation in plain English. I&apos;ll break it into blocks,
                  wire them into a pipeline, and execute it.
                </p>
                <div className="mt-6 flex flex-wrap gap-2 justify-center max-w-lg">
                  {[
                    "Search for AI news every morning",
                    "Track Bitcoin price and alert if below $60k",
                    "Summarize top Hacker News posts",
                    "Find the best laptop deals under $1000",
                  ].map((example) => (
                    <button
                      key={example}
                      onClick={() => { setInput(example); inputRef.current?.focus(); }}
                      className="text-xs px-3 py-1.5 rounded-full border border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-500 transition-colors"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <AnimatePresence>
              {state.messages.map((msg) => (
                <motion.div
                  key={msg.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}
                  className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-2xl rounded-2xl px-4 py-3 ${
                      msg.role === "user"
                        ? "bg-blue-600 text-white"
                        : msg.error
                          ? "bg-red-500/10 border border-red-500/30 text-red-300"
                          : "bg-gray-800 text-gray-200"
                    }`}
                  >
                    <p className="text-sm">{msg.content}</p>

                    {/* Clarification questions */}
                    {msg.clarification && (
                      <div className="mt-3 border-t border-gray-700 pt-3">
                        <div className="flex items-center gap-1.5 text-xs text-blue-400 mb-2">
                          <HelpCircle className="w-3.5 h-3.5" />
                          Questions
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {msg.clarification.questions.map((q, i) => (
                            <button
                              key={i}
                              onClick={() => {
                                setInput(q);
                                inputRef.current?.focus();
                              }}
                              className="text-xs px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 hover:border-blue-500/50 transition-colors text-left"
                            >
                              {q}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>

            {/* Loading indicator */}
            {state.phase === "loading" && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex justify-start"
              >
                <div className="bg-gray-800 rounded-2xl px-4 py-3 flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                  <span className="text-sm text-gray-400">Analyzing your request...</span>
                </div>
              </motion.div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input bar */}
          <div className="border-t border-gray-800 p-4 flex-shrink-0">
            <div className="max-w-3xl mx-auto relative">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  state.phase === "clarifying"
                    ? "Answer the question above..."
                    : "Describe your automation..."
                }
                disabled={isInputDisabled}
                className="w-full px-4 py-3 pr-12 bg-gray-900 border border-gray-700 rounded-xl text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 disabled:opacity-50 transition-all shadow-lg shadow-blue-500/5"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || isInputDisabled}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-gray-400 hover:text-blue-400 disabled:opacity-30 transition-colors"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

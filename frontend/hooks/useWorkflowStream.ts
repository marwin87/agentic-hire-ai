"use client";

import { useCallback, useRef, useState } from "react";
import {
  AgentMessageData,
  makeInitialState,
  NodeName,
  NODE_ORDER,
  OrchestrateResponse,
  WorkflowState,
} from "@/lib/workflow-types";

function findOrCreateMessage(
  messages: AgentMessageData[],
  node: NodeName
): { messages: AgentMessageData[]; index: number } {
  // Walk backwards — find last message for this node
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].node === node) {
      // Reuse if still running; otherwise start a new one (rescout)
      if (messages[i].status === "running") {
        return { messages, index: i };
      }
      break;
    }
  }
  // Create new message for this node run
  const runIndex = messages.filter((m) => m.node === node).length + 1;
  const newMsg: AgentMessageData = {
    id: `${node}-${Date.now()}-${Math.random()}`,
    node,
    runIndex,
    status: "running",
    logs: [],
    summary: {},
  };
  return { messages: [...messages, newMsg], index: messages.length };
}

function applyEvent(
  state: WorkflowState,
  event: { node: string; status: string; data: Record<string, unknown> }
): WorkflowState {
  const node = event.node as NodeName;

  if (event.status === "log") {
    const message = (event.data.message as string) ?? "";
    const { messages, index } = findOrCreateMessage(state.messages, node);
    const updated = [...messages];
    updated[index] = { ...updated[index], logs: [...updated[index].logs, message] };
    return { ...state, messages: updated };
  }

  if (event.status === "complete" && NODE_ORDER.includes(node)) {
    const { messages, index } = findOrCreateMessage(state.messages, node);
    const updated = [...messages];
    updated[index] = { ...updated[index], status: "complete", summary: event.data };
    return { ...state, messages: updated };
  }

  if (event.status === "error") {
    const errorMsg = (event.data.message as string) ?? "Unknown error";
    if (NODE_ORDER.includes(node)) {
      const { messages, index } = findOrCreateMessage(state.messages, node);
      const updated = [...messages];
      updated[index] = { ...updated[index], status: "error", errorMessage: errorMsg };
      return { ...state, messages: updated, isStreaming: false };
    }
    return { ...state, error: errorMsg, isStreaming: false };
  }

  return state;
}

export function useWorkflowStream() {
  const [state, setState] = useState<WorkflowState>(makeInitialState);
  const abortRef = useRef<AbortController | null>(null);

  const startWorkflow = useCallback(async (criteria: string, scoreThreshold?: number) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState({ ...makeInitialState(), isStreaming: true });

    try {
      const res = await fetch("/api/workflow/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          criteria,
          ...(scoreThreshold !== undefined && { score_threshold: scoreThreshold }),
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "stream_error" }));
        setState((prev) => ({ ...prev, error: err.error ?? "Failed to start workflow", isStreaming: false }));
        return;
      }

      if (!res.body) {
        setState((prev) => ({ ...prev, error: "No response body", isStreaming: false }));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let event: { node: string; status: string; data: Record<string, unknown> };
          try {
            event = JSON.parse(raw);
          } catch {
            continue;
          }

          if (event.node === "workflow" && event.status === "complete") {
            setState((prev) => ({
              ...prev,
              finalResult: event.data as unknown as OrchestrateResponse,
              isStreaming: false,
            }));
            return;
          }

          setState((prev) => applyEvent(prev, event));
        }
      }

      setState((prev) => ({ ...prev, isStreaming: false }));
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setState((prev) => ({ ...prev, error: (err as Error).message ?? "Stream error", isStreaming: false }));
    }
  }, []);

  const abortWorkflow = useCallback(() => {
    abortRef.current?.abort();
    setState(makeInitialState());
  }, []);

  return { state, startWorkflow, abortWorkflow };
}

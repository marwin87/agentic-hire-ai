"use client";

import { useCallback, useRef, useState } from "react";
import {
  makeInitialState,
  NEXT_NODE,
  NodeName,
  NODE_ORDER,
  OrchestrateResponse,
  TileData,
  WorkflowState,
} from "@/lib/workflow-types";

export function useWorkflowStream() {
  const [state, setState] = useState<WorkflowState>(makeInitialState);
  const abortRef = useRef<AbortController | null>(null);

  const startWorkflow = useCallback(
    async (criteria: string, scoreThreshold?: number) => {
      // Cancel any in-flight request
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      // Reset to initial state with scout as the first running tile
      setState((prev) => {
        const next = makeInitialState();
        next.tiles["scout"] = { ...next.tiles["scout"], status: "running" };
        return { ...next, isStreaming: true };
      });

      try {
        const res = await fetch("/api/workflow/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            criteria,
            ...(scoreThreshold !== undefined && {
              score_threshold: scoreThreshold,
            }),
          }),
          signal: controller.signal,
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ error: "stream_error" }));
          setState((prev) => ({
            ...prev,
            error: err.error ?? "Failed to start workflow",
            isStreaming: false,
          }));
          return;
        }

        if (!res.body) {
          setState((prev) => ({
            ...prev,
            error: "No response body",
            isStreaming: false,
          }));
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

            if (event.status === "error") {
              const errorMsg =
                (event.data.message as string) ?? "Unknown error";
              setState((prev) => {
                const tiles = { ...prev.tiles };
                const nodeName = event.node as NodeName;
                if (NODE_ORDER.includes(nodeName)) {
                  tiles[nodeName] = {
                    ...tiles[nodeName],
                    status: "error",
                    errorMessage: errorMsg,
                  };
                }
                // Mark remaining nodes pending
                let found = false;
                for (const n of NODE_ORDER) {
                  if (n === nodeName) { found = true; continue; }
                  if (found) tiles[n] = { ...tiles[n], status: "pending", summary: {} };
                }
                return { ...prev, tiles, isStreaming: false };
              });
              return;
            }

            // Normal node completion
            const nodeName = event.node as NodeName;
            if (!NODE_ORDER.includes(nodeName)) continue;

            setState((prev) => {
              const tiles: Record<NodeName, TileData> = { ...prev.tiles };
              tiles[nodeName] = {
                ...tiles[nodeName],
                status: "complete",
                summary: event.data,
              };
              // Advance the next node to running
              const nextNode = NEXT_NODE[nodeName];
              if (nextNode) {
                tiles[nextNode] = { ...tiles[nextNode], status: "running" };
              }
              return { ...prev, tiles };
            });
          }
        }

        // Stream ended without a workflow_complete event — mark streaming done
        setState((prev) => ({ ...prev, isStreaming: false }));
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setState((prev) => ({
          ...prev,
          error: (err as Error).message ?? "Stream error",
          isStreaming: false,
        }));
      }
    },
    []
  );

  const abortWorkflow = useCallback(() => {
    abortRef.current?.abort();
    setState(makeInitialState());
  }, []);

  return { state, startWorkflow, abortWorkflow };
}

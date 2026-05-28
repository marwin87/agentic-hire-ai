export type NodeName = "scout" | "validate_jobs" | "orchestrator" | "tailor";
export type TileStatus = "pending" | "running" | "complete" | "error";

export interface TileData {
  node: NodeName;
  status: TileStatus;
  summary: Record<string, unknown>;
  errorMessage?: string;
}

export interface OrchestrateJobResult {
  id: string;
  title: string;
  company: string;
  url: string;
  match_score: number;
  analysis: string | null;
  evaluation: string | null;
  error: string | null;
}

export interface OrchestrateResponse {
  all_jobs: OrchestrateJobResult[];
  shortlisted_jobs: OrchestrateJobResult[];
  rejected_jobs: OrchestrateJobResult[];
  status: string;
  error_count: number;
}

export interface WorkflowState {
  tiles: Record<NodeName, TileData>;
  finalResult: OrchestrateResponse | null;
  error: string | null;
  isStreaming: boolean;
}

// Graph topology: which node becomes "running" after each node completes
export const NEXT_NODE: Partial<Record<NodeName, NodeName>> = {
  scout: "validate_jobs",
  validate_jobs: "orchestrator",
  orchestrator: "tailor",
};

export const NODE_ORDER: NodeName[] = [
  "scout",
  "validate_jobs",
  "orchestrator",
  "tailor",
];

export function makeInitialState(): WorkflowState {
  const tiles = NODE_ORDER.reduce(
    (acc, node) => {
      acc[node] = { node, status: "pending", summary: {} };
      return acc;
    },
    {} as Record<NodeName, TileData>
  );
  return { tiles, finalResult: null, error: null, isStreaming: false };
}

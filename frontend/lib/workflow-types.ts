export type NodeName = "scout" | "validate_jobs" | "orchestrator" | "tailor";
export type TileStatus = "running" | "complete" | "error";

export interface AgentMessageData {
  id: string;
  node: NodeName;
  runIndex: number;
  status: TileStatus;
  logs: string[];
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
  messages: AgentMessageData[];
  finalResult: OrchestrateResponse | null;
  error: string | null;
  isStreaming: boolean;
}

export const NODE_ORDER: NodeName[] = [
  "scout",
  "validate_jobs",
  "orchestrator",
  "tailor",
];

export function makeInitialState(): WorkflowState {
  return { messages: [], finalResult: null, error: null, isStreaming: false };
}

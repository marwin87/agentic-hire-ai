import { NodeName } from "./workflow-types";

export interface AgentConfig {
  node: NodeName;
  label: string;
  role: string;
  color: string;        // Tailwind bg color class for the avatar fallback
  textColor: string;    // Tailwind text color for the avatar fallback
  initials: string;
  avatarSrc: string;    // path relative to /public
  isSystem: boolean;    // true = right-aligned (automated/system step, not an agent)
}

export const AGENT_CONFIGS: Record<NodeName, AgentConfig> = {
  scout: {
    node: "scout",
    label: "Scout",
    role: "Job Discovery",
    color: "bg-violet-600",
    textColor: "text-white",
    initials: "SC",
    avatarSrc: "/images/scout_avatar.jpg",
    isSystem: false,
  },
  validate_jobs: {
    node: "validate_jobs",
    label: "Validator",
    role: "Quality Check",
    color: "bg-sky-500",
    textColor: "text-white",
    initials: "VL",
    avatarSrc: "/images/cpu_avatar.jpg",
    isSystem: true,
  },
  orchestrator: {
    node: "orchestrator",
    label: "Orchestrator",
    role: "Scoring & Matching",
    color: "bg-emerald-600",
    textColor: "text-white",
    initials: "OR",
    avatarSrc: "/images/orch_avatar.jpg",
    isSystem: false,
  },
  tailor: {
    node: "tailor",
    label: "Tailor",
    role: "Evaluation",
    color: "bg-orange-500",
    textColor: "text-white",
    initials: "TL",
    avatarSrc: "/images/tailor_avatar.jpg",
    isSystem: false,
  },
};

export const NODE_ORDER_CONFIGS: AgentConfig[] = [
  AGENT_CONFIGS.scout,
  AGENT_CONFIGS.validate_jobs,
  AGENT_CONFIGS.orchestrator,
  AGENT_CONFIGS.tailor,
];

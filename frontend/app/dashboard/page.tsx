"use client";

import {useEffect, useRef, useState} from "react";
import {useWorkflowState} from "@/context/workflow-state";
import Image from "next/image";
import {useWorkflowStream} from "@/hooks/useWorkflowStream";
import {
    AgentMessageData,
    NodeName,
    OrchestrateJobResult,
    OrchestrateResponse,
} from "@/lib/workflow-types";
import {AGENT_CONFIGS, AgentConfig} from "@/lib/agent-config";
import {scoreBadgeClasses} from "@/lib/score-badge";

// ── CV upload hook ────────────────────────────────────────────────────────────

type CvStatus =
    | { type: "idle" }
    | { type: "checking" }
    | { type: "uploading" }
    | { type: "processing"; filename: string }
    | { type: "success"; filename: string }
    | { type: "error"; message: string };

function useCvUpload() {
    const [status, setStatus] = useState<CvStatus>({type: "checking"});
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    function stopPolling() {
        if (pollRef.current !== null) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
    }

    function startPolling(filename: string) {
        stopPolling();
        pollRef.current = setInterval(async () => {
            try {
                const res = await fetch("/api/cv/status", {cache: "no-store"});
                if (!res.ok) return;
                const data = await res.json();
                if (data.ingestion_status === "completed") {
                    stopPolling();
                    setStatus({type: "success", filename: data.filename ?? filename});
                } else if (data.ingestion_status === "failed") {
                    stopPolling();
                    setStatus({type: "error", message: data.ingestion_error ?? "CV processing failed. Please try again."});
                }
            } catch { /* network blip — keep polling */ }
        }, 2500);
    }

    // Check on mount whether the user already has a CV (and its ingestion state)
    useEffect(() => {
        fetch("/api/cv/status")
            .then((r) => r.json())
            .then((data) => {
                if (!data.has_cv) {
                    setStatus({type: "idle"});
                } else if (data.ingestion_status === "completed") {
                    setStatus({type: "success", filename: data.filename ?? "resume.pdf"});
                } else if (data.ingestion_status === "failed") {
                    setStatus({type: "idle"});
                } else {
                    // still processing from a previous session
                    const filename = data.filename ?? "resume.pdf";
                    setStatus({type: "processing", filename});
                    startPolling(filename);
                }
            })
            .catch(() => setStatus({type: "idle"}));
        return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    async function upload(file: File) {
        if (file.type !== "application/pdf") {
            setStatus({type: "error", message: "Only PDF files are accepted."});
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            setStatus({
                type: "error",
                message: `File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Max 10 MB.`,
            });
            return;
        }
        setStatus({type: "uploading"});
        stopPolling();
        const formData = new FormData();
        formData.append("file", file);
        try {
            const res = await fetch("/api/cv/upload", {method: "POST", body: formData});
            const data = await res.json();
            if (!res.ok) {
                setStatus({type: "error", message: data.detail ?? "Upload failed."});
                return;
            }
            // 202 — file saved, ingestion running in background
            setStatus({type: "processing", filename: file.name});
            startPolling(file.name);
        } catch {
            setStatus({type: "error", message: "Upload failed. Please try again."});
        }
    }

    const hasCv = status.type === "success";
    return {status, upload, hasCv};
}

// ── CV Upload panel ───────────────────────────────────────────────────────────

function CvUploadPanel({
    status,
    upload,
}: {
    status: CvStatus;
    upload: (file: File) => Promise<void>;
}) {
    const inputRef = useRef<HTMLInputElement>(null);
    const [dragging, setDragging] = useState(false);

    function handleDrop(e: React.DragEvent) {
        e.preventDefault();
        setDragging(false);
        const file = e.dataTransfer.files[0];
        if (file) upload(file);
    }

    const isSuccess = status.type === "success";
    const isChecking = status.type === "checking";
    const isProcessing = status.type === "processing";

    return (
        <div className="bg-surface rounded-2xl border border-border shadow-sm p-4 space-y-3">
            <p className="text-sm font-semibold text-muted-strong">CV / Resume</p>

            {isChecking ? (
                <div className="flex items-center gap-2 px-6 py-4 text-sm text-muted">
                    <span className="w-4 h-4 rounded-full border-2 border-border border-t-transparent animate-spin"/>
                    Checking…
                </div>
            ) : isProcessing ? (
                <div className="flex items-center gap-3 px-3 py-3">
                    <div className="w-10 h-10 rounded-full bg-accent-soft border border-accent flex items-center justify-center text-xl shrink-0">
                        💻
                    </div>
                    <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-muted-strong truncate">
                            {(status as { type: "processing"; filename: string }).filename}
                        </p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                            <span className="w-3 h-3 rounded-full border-2 border-accent border-t-transparent animate-spin shrink-0"/>
                            <span className="text-xs text-accent">Reading and embedding your CV…</span>
                        </div>
                    </div>
                </div>
            ) : !isSuccess ? (
                <div
                    role="button"
                    tabIndex={0}
                    onClick={() => inputRef.current?.click()}
                    onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
                    onDragOver={(e) => {
                        e.preventDefault();
                        setDragging(true);
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={handleDrop}
                    className={`flex items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-4 cursor-pointer transition select-none text-sm ${
                        dragging
                            ? "border-success bg-success-soft text-success"
                            : status.type === "uploading"
                                ? "border-accent bg-accent-soft text-accent cursor-wait"
                                : "border-border bg-surface-alt hover:bg-surface-alt/70 text-muted"
                    }`}
                >
                    {status.type === "uploading" ? (
                        <>
                            <span className="w-4 h-4 rounded-full border-2 border-accent border-t-transparent animate-spin"/>
                            Uploading…
                        </>
                    ) : (
                        <>
                            <span className="text-lg">📄</span>
                            <span>Drop your PDF here, or <span className="text-accent font-medium">browse</span></span>
                            <span className="text-xs text-muted">· max 10 MB</span>
                        </>
                    )}
                </div>
            ) : (
                <div className="flex flex-col items-start gap-2">
                    <p className="text-xs text-muted flex items-center gap-1">
                        <span className="text-success font-medium flex items-center gap-1"><span>✓</span>{(status as { type: "success"; filename: string }).filename}</span>
                    </p>
                    <button
                        onClick={() => inputRef.current?.click()}
                        className="rounded-xl px-4 py-2 text-sm border border-border text-muted hover:bg-surface-alt transition"
                    >
                        Replace CV
                    </button>
                </div>
            )}

            {status.type === "error" && (
                <p className="text-xs text-danger">{status.message}</p>
            )}

            <input
                ref={inputRef}
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) upload(file);
                    e.target.value = "";
                }}
            />
        </div>
    );
}

// ── Summary formatters ────────────────────────────────────────────────────────

function formatSummary(node: AgentMessageData["node"], summary: Record<string, unknown>): string {
    switch (node) {
        case "scout":
            return `Found ${summary.jobs_found ?? 0} jobs`;
        case "validate_jobs":
            return `${summary.jobs_valid ?? 0} valid · ${summary.jobs_rejected ?? 0} rejected`;
        case "orchestrator":
            return `${summary.jobs_shortlisted ?? 0} shortlisted above threshold`;
        case "tailor":
            return `${summary.evaluations ?? 0} evaluations written`;
        default:
            return JSON.stringify(summary);
    }
}

// ── Avatar ────────────────────────────────────────────────────────────────────

function Avatar({config, pulse}: { config: AgentConfig; pulse?: boolean }) {
    return (
        <div
            className={`relative w-14 h-14 rounded-full shrink-0 overflow-hidden ${
                pulse
                    ? "ring-2 ring-offset-2 ring-ring animate-pulse"
                    : "ring-1 ring-border"
            }`}
        >
            <Image
                src={config.avatarSrc}
                alt={config.label}
                fill
                className="object-cover"
                sizes="56px"
            />
        </div>
    );
}

// ── Thinking dots ─────────────────────────────────────────────────────────────

function ThinkingDots() {
    return (
        <span className="flex items-center gap-1 h-5">
      {[0, 150, 300].map((delay) => (
          <span
              key={delay}
              className="w-1.5 h-1.5 rounded-full bg-muted animate-bounce"
              style={{animationDelay: `${delay}ms`}}
          />
      ))}
    </span>
    );
}

// ── Agent message bubble ──────────────────────────────────────────────────────

function AgentMessage({message, config}: { message: AgentMessageData; config: AgentConfig }) {
    const isRunning = message.status === "running";
    const isError = message.status === "error";
    const isComplete = message.status === "complete";
    const right = config.isSystem;
    const label = message.runIndex > 1 ? `${config.label} (Run ${message.runIndex})` : config.label;

    const bubble = (
        <div
            className={`inline-block px-4 py-3 text-sm max-w-prose transition-all ${
                right ? "rounded-2xl rounded-tr-sm" : "rounded-2xl rounded-tl-sm"
            } ${
                isRunning
                    ? "bg-surface-alt border border-border text-muted"
                    : isError
                        ? "bg-danger-soft border border-danger text-danger"
                        : right
                            ? "bg-info-soft border border-info shadow-sm text-info"
                            : "bg-surface border border-border shadow-sm text-muted-strong"
            }`}
        >
            {/* Live log lines */}
            {message.logs.length > 0 && (
                <div className="space-y-0.5 mb-2 font-mono text-xs text-muted-strong">
                    {message.logs.map((line, i) => (
                        <p key={i}>{line}</p>
                    ))}
                </div>
            )}
            {/* Thinking dots when running with no logs yet */}
            {isRunning && message.logs.length === 0 && (
                <span className="flex items-center gap-3">
                    <ThinkingDots/>
                    <span className="text-muted text-xs">Working…</span>
                </span>
            )}
            {/* Running indicator after logs appear */}
            {isRunning && message.logs.length > 0 && (
                <span className="flex items-center gap-1.5 mt-1">
                    <ThinkingDots/>
                </span>
            )}
            {isError && (
                <span>
                    <span className="font-medium">Error: </span>
                    {message.errorMessage ?? "Something went wrong"}
                </span>
            )}
            {isComplete && (
                <span className="flex items-center gap-2 mt-1 text-xs font-medium">
                    <span className="text-success">✓</span>
                    <span>{formatSummary(message.node, message.summary)}</span>
                </span>
            )}
        </div>
    );

    return (
        <div
            className={`flex items-start gap-3 ${right ? "flex-row-reverse" : ""}`}
            style={{animation: "fadeSlideIn 0.35s ease-out both"}}
        >
            <Avatar config={config} pulse={isRunning}/>
            <div className={`flex-1 min-w-0 ${right ? "flex flex-col items-end" : ""}`}>
                <div className={`flex items-baseline gap-2 mb-1.5 ${right ? "flex-row-reverse" : ""}`}>
                    <span className="text-sm font-semibold text-muted-strong">{label}</span>
                    <span className="text-xs text-muted">{config.role}</span>
                </div>
                {bubble}
            </div>
        </div>
    );
}

// ── Job card ──────────────────────────────────────────────────────────────────

function JobCard({job}: { job: OrchestrateJobResult }) {
    const pct = Math.round(job.match_score * 100);

    return (
        <div
            className="rounded-xl border border-border bg-surface p-4 space-y-2 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <p className="font-semibold text-foreground text-sm leading-tight">{job.title}</p>
                    <p className="text-xs text-muted mt-0.5">{job.company}</p>
                </div>
                <span className={`text-xs font-bold px-2.5 py-1 rounded-full shrink-0 ${scoreBadgeClasses(pct)}`}>
          {pct}%
        </span>
            </div>
            {job.evaluation && (
                <p className="text-xs text-muted-strong leading-relaxed border-t border-border pt-2">
                    {job.evaluation}
                </p>
            )}
            <a
                href={job.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-accent hover:text-accent-hover hover:underline inline-flex items-center gap-1 transition-colors"
            >
                View posting <span aria-hidden>→</span>
            </a>
        </div>
    );
}

// ── Results panel ─────────────────────────────────────────────────────────────

function ResultsPanel({result}: { result: OrchestrateResponse | null }) {
    if (!result) return null;

    const sorted = [...result.shortlisted_jobs].sort((a, b) => b.match_score - a.match_score);

    return (
        <div
            className="flex items-start gap-3"
            style={{animation: "fadeSlideIn 0.4s ease-out both"}}
        >
            <div
                className="w-11 h-11 rounded-full bg-accent flex items-center justify-center text-accent-contrast text-xs font-bold shrink-0 ring-1 ring-ring">
                AI
            </div>
            <div className="flex-1 min-w-0 space-y-3">
                <div className="flex items-baseline gap-2 mb-1.5">
                    <span className="text-sm font-semibold text-muted-strong">AgenticHire</span>
                    <span className="text-xs text-muted">Pipeline complete</span>
                </div>
                <div
                    className="inline-block rounded-2xl rounded-tl-sm px-4 py-3 text-sm bg-accent-soft border border-accent shadow-sm text-accent-text">
                    Done! Found{" "}
                    <strong>{sorted.length} matching position{sorted.length !== 1 ? "s" : ""}</strong>
                    {result.rejected_jobs.length > 0 && (
                        <span className="text-accent"> ({result.rejected_jobs.length} below threshold)</span>
                    )}.
                </div>
                {sorted.length > 0 && (
                    <div className="grid gap-3 max-w-lg">
                        {sorted.map((job) => <JobCard key={job.id} job={job}/>)}
                    </div>
                )}
                {sorted.length === 0 && (
                    <div className="rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted">
                        No jobs met the score threshold. Try lowering it or broadening your criteria.
                    </div>
                )}
            </div>
        </div>
    );
}

// ── Empty state avatars (Orchestrator, Scout, Tailor) ─────────────────────────

const EMPTY_STATE_NODES: NodeName[] = ["orchestrator", "scout", "tailor"];

// ── Dashboard ─────────────────────────────────────────────────────────────────

export default function DashboardPage() {
    const {state, startWorkflow, abortWorkflow, clearResults} = useWorkflowStream();
    const {status: cvStatus, upload: cvUpload, hasCv} = useCvUpload();
    const {register} = useWorkflowState();

    useEffect(() => {
        register({isStreaming: state.isStreaming, abort: abortWorkflow});
    }, [state.isStreaming, abortWorkflow, register]);
    const [criteria, setCriteria] = useState(() => {
        try { return sessionStorage.getItem("ah_last_criteria") ?? ""; } catch { return ""; }
    });
    const [threshold, setThreshold] = useState(() => {
        try { return sessionStorage.getItem("ah_last_threshold") ?? "0.6"; } catch { return "0.6"; }
    });
    const feedRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        feedRef.current?.scrollTo({top: feedRef.current.scrollHeight, behavior: "smooth"});
    }, [state.messages, state.finalResult]);

    function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        if (!criteria.trim()) return;
        try {
            sessionStorage.setItem("ah_last_criteria", criteria.trim());
            sessionStorage.setItem("ah_last_threshold", threshold);
        } catch { /* ignore */ }
        startWorkflow(criteria.trim(), parseFloat(threshold) || 0.6);
    }

    const hasActivity = state.messages.length > 0;

    return (
        <div className="flex flex-col gap-5 max-w-4xl mx-auto">
            {/* CV upload */}
            <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                    <span
                        className="w-5 h-5 rounded-full bg-accent text-accent-contrast text-xs font-bold flex items-center justify-center shrink-0">1</span>
                    <p className="text-sm font-semibold text-muted-strong">Upload your CV</p>
                </div>
                <p className="text-xs text-muted pl-7">
                    Upload your resume as a PDF. It will be parsed and embedded so the AI can match your skills against
                    job listings.
                </p>
            </div>
            <CvUploadPanel status={cvStatus} upload={cvUpload}/>

            {/* Search form */}
            <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                    <span
                        className="w-5 h-5 rounded-full bg-accent text-accent-contrast text-xs font-bold flex items-center justify-center shrink-0">2</span>
                    <p className="text-sm font-semibold text-muted-strong">Describe the role you&apos;re looking for</p>
                </div>
                <p className="text-xs text-muted pl-7">
                    Be as specific as you like — seniority, tech stack, location, industry. The more detail you give,
                    the better the matches.
                </p>
            </div>
            <form
                onSubmit={handleSubmit}
                className="bg-surface rounded-2xl border border-border shadow-sm p-4 space-y-3"
            >
                <p className="text-sm font-semibold text-muted-strong">Job Search</p>
                <textarea
                    rows={2}
                    value={criteria}
                    onChange={(e) => setCriteria(e.target.value)}
                    placeholder="e.g. Senior Python backend engineer, remote, fintech"
                    className="w-full rounded-xl border border-border px-4 py-3 text-sm text-foreground placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                    disabled={state.isStreaming}
                />
                <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1 shrink-0 group relative">
                        <label className="text-xs text-muted cursor-default">Score threshold</label>
                        <span className="w-3.5 h-3.5 rounded-full bg-surface-alt text-muted text-[9px] font-bold flex items-center justify-center cursor-help leading-none">?</span>
                        <div className="absolute bottom-full left-0 mb-2 w-56 rounded-lg bg-foreground text-background text-xs px-3 py-2 leading-relaxed opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-10 shadow-lg">
                            Minimum match score (0–1) a job must reach to be shortlisted. Higher = stricter, fewer but better matches. Lower = more results but less precise.
                            <div className="absolute top-full left-4 border-4 border-transparent border-t-foreground"/>
                        </div>
                    </div>
                    <input
                        type="number"
                        min="0"
                        max="1"
                        step="0.05"
                        value={threshold}
                        onChange={(e) => setThreshold(e.target.value)}
                        className="w-16 rounded-lg border border-border px-2 py-1.5 text-xs text-center focus:outline-none focus:ring-2 focus:ring-ring"
                        disabled={state.isStreaming}
                    />
                    <div className="flex gap-2 ml-auto">
                        {hasActivity && (
                            <button
                                type="button"
                                onClick={clearResults}
                                disabled={state.isStreaming}
                                className="rounded-xl px-4 py-2 text-sm border border-border text-muted hover:bg-surface-alt transition disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                Clear
                            </button>
                        )}
                        {state.isStreaming && (
                            <button
                                type="button"
                                onClick={abortWorkflow}
                                className="rounded-xl px-4 py-2 text-sm border border-danger text-danger hover:bg-danger-soft transition"
                            >
                                Stop
                            </button>
                        )}
                        <button
                            type="submit"
                            disabled={state.isStreaming || !criteria.trim() || !hasCv}
                            className="rounded-xl bg-accent px-5 py-2 text-sm font-semibold text-accent-contrast hover:bg-accent-hover transition disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {state.isStreaming ? (
                                <span className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full border-2 border-accent-contrast border-t-transparent animate-spin"/>
                  Running…
                </span>
                            ) : (
                                "Search"
                            )}
                        </button>
                    </div>
                </div>
                {!hasCv && criteria.trim() && cvStatus.type !== "checking" && (
                    <p className="flex items-center gap-1.5 text-xs text-warning bg-warning-soft border border-warning rounded-lg px-3 py-2">
                        <span>⚠</span>
                        {cvStatus.type === "processing"
                            ? "Your CV is still being processed — Search will unlock once embedding is complete."
                            : "Please upload your CV first — the agents need it to score how well each job matches your experience."}
                    </p>
                )}
            </form>

            {/* Global error */}
            {state.error && (
                <div className="rounded-xl bg-danger-soft border border-danger px-4 py-3 text-sm text-danger">
                    {state.error}
                </div>
            )}

            {/* Conversation feed */}
            {hasActivity && (
                <div ref={feedRef} className="space-y-5 max-h-[60vh] overflow-y-auto pr-1">
                    {state.messages.map((msg) => (
                        <AgentMessage
                            key={msg.id}
                            message={msg}
                            config={AGENT_CONFIGS[msg.node]}
                        />
                    ))}
                    <ResultsPanel result={state.finalResult}/>
                </div>
            )}

            {/* Empty state */}
            {!hasActivity && !state.error && (
                <div className="text-center py-10 text-sm space-y-3">
                    <div className="flex justify-center gap-4 mb-2">
                        {EMPTY_STATE_NODES.map((node) => (
                            <div
                                key={node}
                                className="relative w-14 h-14 rounded-full overflow-hidden ring-1 ring-border"
                            >
                                <Image
                                    src={AGENT_CONFIGS[node].avatarSrc}
                                    alt={AGENT_CONFIGS[node].label}
                                    fill
                                    className="object-cover"
                                    sizes="56px"
                                />
                            </div>
                        ))}
                    </div>
                    <p className="font-medium text-muted-strong">Your agent team is ready.</p>
                    <p className="text-muted max-w-sm mx-auto leading-relaxed">
                        Scout uncovers the best matching opportunities, Orchestrator ranks them against your experience
                        and goals, and Tailor crafts personalised insights for every match so you can apply with
                        confidence.
                    </p>
                </div>
            )}
        </div>
    );
}

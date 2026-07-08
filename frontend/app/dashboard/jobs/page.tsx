"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { scoreBadgeClasses } from "@/lib/score-badge";

interface JobItem {
  id: string;
  title: string;
  company: string;
  url: string;
  match_score: number | null;
}

interface JobsResponse {
  page: number;
  total_count: number;
  page_size: number;
  jobs: JobItem[];
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <span className="text-xs px-2.5 py-1 rounded-full bg-surface-alt text-muted">
        —
      </span>
    );
  }
  const pct = Math.round(score * 100);
  return (
    <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${scoreBadgeClasses(pct)}`}>
      {pct}%
    </span>
  );
}

export default function JobsPage() {
  const [data, setData] = useState<JobsResponse | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [clearingAll, setClearingAll] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/jobs?page=${p}&page_size=10`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "Failed to load" }));
        setError(err.error ?? "Failed to load jobs");
        return;
      }
      const json: JobsResponse = await res.json();
      setData(json);
    } catch {
      setError("Could not reach the server");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(page);
  }, [load, page]);

  async function deleteJob(jobId: string) {
    setDeletingId(jobId);
    try {
      const res = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
      if (res.ok || res.status === 204) {
        // Re-fetch current page; if it becomes empty go back one page
        const newPage = data && data.jobs.length === 1 && page > 1 ? page - 1 : page;
        setPage(newPage);
        await load(newPage);
      } else {
        const err = await res.json().catch(() => ({ error: "delete_failed" }));
        setError(err.error ?? "Failed to delete job");
      }
    } catch {
      setError("Could not reach the server");
    } finally {
      setDeletingId(null);
    }
  }

  async function clearAllJobs() {
    setClearingAll(true);
    setConfirmClear(false);
    try {
      const res = await fetch("/api/jobs", { method: "DELETE" });
      if (res.ok) {
        setPage(1);
        await load(1);
      } else {
        const err = await res.json().catch(() => ({ error: "clear_failed" }));
        setError(err.error ?? "Failed to clear jobs");
      }
    } catch {
      setError("Could not reach the server");
    } finally {
      setClearingAll(false);
    }
  }

  const totalPages = data ? Math.ceil(data.total_count / data.page_size) : 1;
  const hasJobs = data && data.total_count > 0;

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-foreground">Discovered Jobs</h1>
          <p className="text-sm text-muted mt-0.5">
            All positions found during your search sessions, sorted by discovery date.
          </p>
        </div>

        {hasJobs && !loading && (
          confirmClear ? (
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs text-muted">Are you sure?</span>
              <button
                onClick={clearAllJobs}
                disabled={clearingAll}
                className="rounded-lg bg-danger px-3 py-1.5 text-xs font-semibold text-white hover:bg-danger/90 transition disabled:opacity-60"
              >
                {clearingAll ? "Clearing…" : "Yes, clear all"}
              </button>
              <button
                onClick={() => setConfirmClear(false)}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted hover:bg-surface-alt transition"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmClear(true)}
              className="shrink-0 rounded-lg border border-danger px-3 py-1.5 text-xs text-danger hover:bg-danger-soft transition"
            >
              Clear all
            </button>
          )
        )}
      </div>

      {error && (
        <div className="rounded-xl bg-danger-soft border border-danger px-4 py-3 text-sm text-danger">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted py-10 justify-center">
          <span className="w-4 h-4 rounded-full border-2 border-border border-t-accent animate-spin" />
          Loading…
        </div>
      )}

      {!loading && !error && data && data.jobs.length === 0 && (
        <div className="rounded-xl border border-border bg-surface px-6 py-10 text-center space-y-2">
          <p className="text-sm font-medium text-muted-strong">No jobs yet</p>
          <p className="text-xs text-muted">
            Run a search on the{" "}
            <Link href="/dashboard" className="text-accent hover:underline">
              dashboard
            </Link>{" "}
            to discover positions.
          </p>
        </div>
      )}

      {!loading && data && data.jobs.length > 0 && (
        <>
          <p className="text-xs text-muted">
            {data.total_count} position{data.total_count !== 1 ? "s" : ""} total
          </p>

          <div className="space-y-3">
            {data.jobs.map((job) => (
              <div
                key={job.id}
                className="rounded-xl border border-border bg-surface p-4 flex items-start justify-between gap-4 shadow-sm hover:shadow-md transition-shadow"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-foreground text-sm leading-tight truncate">
                    {job.title}
                  </p>
                  <p className="text-xs text-muted mt-0.5">{job.company}</p>
                  <a
                    href={job.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-accent hover:underline mt-1.5 inline-flex items-center gap-1"
                  >
                    View posting <span aria-hidden>→</span>
                  </a>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <ScoreBadge score={job.match_score} />
                  <button
                    onClick={() => deleteJob(job.id)}
                    disabled={deletingId === job.id}
                    title="Remove this job"
                    className="w-7 h-7 rounded-lg flex items-center justify-center text-muted hover:text-danger hover:bg-danger-soft transition disabled:opacity-40"
                  >
                    {deletingId === job.id ? (
                      <span className="w-3.5 h-3.5 rounded-full border-2 border-border border-t-danger animate-spin" />
                    ) : (
                      <span className="text-base leading-none">×</span>
                    )}
                  </button>
                </div>
              </div>
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 pt-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted hover:bg-surface-alt disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                ← Prev
              </button>
              <span className="text-xs text-muted">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted hover:bg-surface-alt disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

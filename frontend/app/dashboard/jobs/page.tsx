"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

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
      <span className="text-xs px-2.5 py-1 rounded-full bg-gray-100 text-gray-400">
        —
      </span>
    );
  }
  const pct = Math.round(score * 100);
  const color =
    pct >= 80
      ? "bg-green-100 text-green-700"
      : pct >= 60
      ? "bg-yellow-100 text-yellow-700"
      : "bg-gray-100 text-gray-500";
  return (
    <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${color}`}>
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
    <div className="max-w-2xl mx-auto space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Discovered Jobs</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            All positions found during your search sessions, sorted by discovery date.
          </p>
        </div>

        {hasJobs && !loading && (
          confirmClear ? (
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs text-gray-500">Are you sure?</span>
              <button
                onClick={clearAllJobs}
                disabled={clearingAll}
                className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 transition disabled:opacity-60"
              >
                {clearingAll ? "Clearing…" : "Yes, clear all"}
              </button>
              <button
                onClick={() => setConfirmClear(false)}
                className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 transition"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmClear(true)}
              className="shrink-0 rounded-lg border border-red-200 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 transition"
            >
              Clear all
            </button>
          )
        )}
      </div>

      {error && (
        <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-400 py-10 justify-center">
          <span className="w-4 h-4 rounded-full border-2 border-gray-300 border-t-indigo-500 animate-spin" />
          Loading…
        </div>
      )}

      {!loading && !error && data && data.jobs.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-6 py-10 text-center space-y-2">
          <p className="text-sm font-medium text-gray-700">No jobs yet</p>
          <p className="text-xs text-gray-500">
            Run a search on the{" "}
            <Link href="/dashboard" className="text-indigo-600 hover:underline">
              dashboard
            </Link>{" "}
            to discover positions.
          </p>
        </div>
      )}

      {!loading && data && data.jobs.length > 0 && (
        <>
          <p className="text-xs text-gray-400">
            {data.total_count} position{data.total_count !== 1 ? "s" : ""} total
          </p>

          <div className="space-y-3">
            {data.jobs.map((job) => (
              <div
                key={job.id}
                className="rounded-xl border border-gray-200 bg-white p-4 flex items-start justify-between gap-4 shadow-sm hover:shadow-md transition-shadow"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-gray-900 text-sm leading-tight truncate">
                    {job.title}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">{job.company}</p>
                  <a
                    href={job.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-indigo-600 hover:underline mt-1.5 inline-flex items-center gap-1"
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
                    className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-300 hover:text-red-500 hover:bg-red-50 transition disabled:opacity-40"
                  >
                    {deletingId === job.id ? (
                      <span className="w-3.5 h-3.5 rounded-full border-2 border-gray-300 border-t-red-400 animate-spin" />
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
                className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                ← Prev
              </button>
              <span className="text-xs text-gray-500">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition"
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

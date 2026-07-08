"use client";

import { useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useWorkflowState } from "@/context/workflow-state";

export default function NavLinks() {
  const router = useRouter();
  const pathname = usePathname();
  const { registration } = useWorkflowState();
  const [pendingHref, setPendingHref] = useState<string | null>(null);

  function navigate(href: string) {
    if (registration.isStreaming && pathname !== href) {
      setPendingHref(href);
    } else {
      router.push(href);
    }
  }

  function confirmLeave() {
    registration.abort();
    router.push(pendingHref!);
    setPendingHref(null);
  }

  const linkClass = (href: string) =>
    `text-sm transition ${
      pathname === href
        ? "text-accent font-medium"
        : "text-muted hover:text-accent"
    }`;

  return (
    <>
      <button onClick={() => navigate("/dashboard")} className={linkClass("/dashboard")}>
        Search
      </button>
      <button onClick={() => navigate("/dashboard/jobs")} className={linkClass("/dashboard/jobs")}>
        My Jobs
      </button>

      {pendingHref && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-overlay backdrop-blur-sm" />
          <div className="relative bg-surface rounded-2xl shadow-xl p-6 max-w-sm w-full mx-4 space-y-4">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-full bg-warning-soft flex items-center justify-center shrink-0 text-lg">
                ⚠️
              </div>
              <div>
                <p className="font-semibold text-foreground text-sm">Workflow in progress</p>
                <p className="text-sm text-muted mt-1 leading-relaxed">
                  The agents are still running. Leaving this page will stop the workflow and results will be lost.
                </p>
              </div>
            </div>
            <div className="flex gap-2 justify-end pt-1">
              <button
                onClick={() => setPendingHref(null)}
                className="rounded-xl px-4 py-2 text-sm border border-border text-muted hover:bg-surface-alt transition"
              >
                Keep running
              </button>
              <button
                onClick={confirmLeave}
                className="rounded-xl px-4 py-2 text-sm bg-danger text-white hover:bg-danger/90 transition font-medium"
              >
                Stop &amp; leave
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

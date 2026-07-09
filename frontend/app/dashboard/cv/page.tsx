"use client";

import { useEffect, useRef, useState } from "react";
import {
  ALLOWED_CV_ACCEPT,
  ALLOWED_CV_MIME_TYPES,
  CV_TYPE_ERROR_MESSAGE,
} from "@/lib/cv-upload";

type UploadStatus =
  | { type: "idle" }
  | { type: "uploading" }
  | { type: "processing" }
  | { type: "success" }
  | { type: "error"; message: string };

export default function CVUploadPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [status, setStatus] = useState<UploadStatus>({ type: "idle" });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopPolling() {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  useEffect(() => stopPolling, []);

  function startPolling() {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch("/api/cv/status", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (data.ingestion_status === "completed") {
          stopPolling();
          setStatus({ type: "success" });
        } else if (data.ingestion_status === "failed") {
          stopPolling();
          setStatus({
            type: "error",
            message: data.ingestion_error ?? "CV processing failed. Please try again.",
          });
        }
      } catch {
        // network blip — keep polling
      }
    }, 2500);
  }

  async function uploadFile(file: File) {
    if (!ALLOWED_CV_MIME_TYPES.includes(file.type)) {
      setStatus({ type: "error", message: CV_TYPE_ERROR_MESSAGE });
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setStatus({
        type: "error",
        message: `File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum is 10 MB.`,
      });
      return;
    }

    setStatus({ type: "uploading" });
    stopPolling();

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/cv/upload", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        setStatus({
          type: "error",
          message: data.detail ?? "Upload failed.",
        });
        return;
      }

      // 202 — file saved, ingestion running in background
      setStatus({ type: "processing" });
      startPolling();
    } catch {
      setStatus({ type: "error", message: "Upload failed. Please try again." });
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  }

  return (
    <div className="max-w-3xl space-y-6">
      <h2 className="text-2xl font-bold text-foreground">Upload CV</h2>
      <p className="text-sm text-muted">
        Upload your CV as a PDF or DOCX. It will be parsed and embedded for
        semantic job matching.
      </p>

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
        className={`flex flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-8 py-12 cursor-pointer transition select-none ${
          dragging
            ? "border-success bg-success-soft"
            : "border-accent bg-accent-soft hover:bg-accent-soft/70"
        }`}
      >
        <span className="text-4xl">📄</span>
        <p className="text-sm font-medium text-muted-strong">
          Drag & drop your CV here, or click to browse
        </p>
        <p className="text-xs text-muted">.pdf, .docx · max 10 MB</p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept={ALLOWED_CV_ACCEPT}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) uploadFile(file);
          e.target.value = "";
        }}
      />

      {status.type === "uploading" && (
        <div className="flex items-center gap-3 rounded-lg bg-accent-soft px-4 py-3 text-sm text-accent-text">
          <span className="animate-spin">⏳</span> Uploading…
        </div>
      )}
      {status.type === "processing" && (
        <div className="flex items-center gap-3 rounded-lg bg-accent-soft px-4 py-3 text-sm text-accent-text">
          <span className="animate-spin">⏳</span> Processing CV — reading and embedding your resume…
        </div>
      )}
      {status.type === "success" && (
        <div className="rounded-lg bg-success-soft border border-success px-4 py-3 text-sm text-success">
          ✅ CV uploaded and embedded successfully.
        </div>
      )}
      {status.type === "error" && (
        <div className="rounded-lg bg-danger-soft border border-danger px-4 py-3 text-sm text-danger">
          ❌ {status.message}
        </div>
      )}
    </div>
  );
}

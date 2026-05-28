"use client";

import { useRef, useState } from "react";

type UploadStatus =
  | { type: "idle" }
  | { type: "uploading" }
  | { type: "success"; chunks: number }
  | { type: "error"; message: string };

export default function CVUploadPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [status, setStatus] = useState<UploadStatus>({ type: "idle" });

  async function uploadFile(file: File) {
    if (file.type !== "application/pdf") {
      setStatus({ type: "error", message: "Only PDF files are accepted." });
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

      setStatus({ type: "success", chunks: data.chunks_stored });
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
    <div className="max-w-xl space-y-6">
      <h2 className="text-2xl font-bold text-gray-800">Upload CV</h2>
      <p className="text-sm text-gray-500">
        Upload your CV as a PDF. It will be parsed and embedded for semantic
        job matching.
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
            ? "border-green-400 bg-green-50"
            : "border-indigo-300 bg-indigo-50 hover:bg-indigo-100"
        }`}
      >
        <span className="text-4xl">📄</span>
        <p className="text-sm font-medium text-gray-700">
          Drag & drop your CV here, or click to browse
        </p>
        <p className="text-xs text-gray-400">.pdf only · max 10 MB</p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) uploadFile(file);
          e.target.value = "";
        }}
      />

      {status.type === "uploading" && (
        <div className="flex items-center gap-3 rounded-lg bg-indigo-50 px-4 py-3 text-sm text-indigo-700">
          <span className="animate-spin">⏳</span> Uploading and embedding…
        </div>
      )}
      {status.type === "success" && (
        <div className="rounded-lg bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-700">
          ✅ CV uploaded successfully — <strong>{status.chunks} chunks</strong>{" "}
          embedded.
        </div>
      )}
      {status.type === "error" && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          ❌ {status.message}
        </div>
      )}
    </div>
  );
}

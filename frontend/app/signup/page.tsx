"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

function passwordHints(password: string) {
  return {
    length: password.length >= 8,
    digit: /\d/.test(password),
    uppercase: /[A-Z]/.test(password),
  };
}

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const hints = passwordHints(password);
  const passwordValid = Object.values(hints).every(Boolean);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!passwordValid) {
      setError("Password does not meet the requirements.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          password_confirm: confirm,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        setError(data.detail ?? "Signup failed. Please try again.");
        return;
      }

      router.push("/dashboard");
      router.refresh();
    } catch {
      setError("Signup failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4"
      style={{ background: "var(--gradient-auth)" }}
    >
      <div className="bg-surface rounded-2xl shadow-2xl w-full max-w-md p-10">
        <h1 className="text-3xl font-bold text-center text-foreground mb-2">
          AgenticHire AI
        </h1>
        <p className="text-center text-muted mb-8 text-sm">
          Create your account
        </p>

        {error && (
          <div className="mb-4 rounded-lg bg-danger-soft border border-danger px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-muted-strong mb-1">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-lg border border-border-strong px-4 py-2.5 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-muted-strong mb-1">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-lg border border-border-strong px-4 py-2.5 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring"
            />
            {password && (
              <ul className="mt-2 space-y-1 rounded-lg bg-surface-alt px-4 py-3 text-xs">
                {[
                  { key: "length", label: "At least 8 characters" },
                  { key: "digit", label: "At least 1 digit (0–9)" },
                  { key: "uppercase", label: "At least 1 uppercase letter (A–Z)" },
                ].map(({ key, label }) => (
                  <li
                    key={key}
                    className={
                      hints[key as keyof typeof hints]
                        ? "text-success"
                        : "text-danger"
                    }
                  >
                    {hints[key as keyof typeof hints] ? "✓" : "✗"} {label}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <label htmlFor="confirm-password" className="block text-sm font-medium text-muted-strong mb-1">
              Confirm Password
            </label>
            <input
              id="confirm-password"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              className="w-full rounded-lg border border-border-strong px-4 py-2.5 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <button
            type="submit"
            disabled={loading || !passwordValid}
            className="w-full rounded-lg bg-accent py-2.5 text-sm font-semibold text-accent-contrast transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? "Creating account…" : "Sign Up"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-muted">
          Already have an account?{" "}
          <Link
            href="/login"
            className="font-semibold text-accent hover:underline"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

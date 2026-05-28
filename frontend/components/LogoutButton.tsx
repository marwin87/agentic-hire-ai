"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LogoutButton({ email }: { email?: string }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handleLogout() {
    setLoading(true);
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    router.push("/login");
    router.refresh();
  }

  return (
    <button
      onClick={handleLogout}
      disabled={loading}
      className="text-sm text-gray-500 hover:text-red-600 transition disabled:opacity-60"
    >
      {loading ? "Signing out…" : email ? `Sign Out (${email})` : "Sign Out"}
    </button>
  );
}

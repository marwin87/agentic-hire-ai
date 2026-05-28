import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import Link from "next/link";
import LogoutButton from "@/components/LogoutButton";
import { ACCESS_TOKEN_COOKIE } from "@/lib/api";

function decodeJwtEmail(token: string): string | undefined {
  try {
    const payload = token.split(".")[1];
    const decoded = Buffer.from(payload, "base64url").toString("utf-8");
    const { email } = JSON.parse(decoded) as { email?: string };
    return email;
  } catch {
    return undefined;
  }
}

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const token = cookieStore.get(ACCESS_TOKEN_COOKIE)?.value;
  if (!token) {
    redirect("/login");
  }

  const email = decodeJwtEmail(token);

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <span className="text-lg font-bold text-indigo-700">
            AgenticHire AI
          </span>
          <Link
            href="/dashboard"
            className="text-sm text-gray-600 hover:text-indigo-600 transition"
          >
            Search
          </Link>
          <Link
            href="/dashboard/jobs"
            className="text-sm text-gray-600 hover:text-indigo-600 transition"
          >
            My Jobs
          </Link>
        </div>
        <LogoutButton email={email} />
      </nav>
      <main className="max-w-5xl mx-auto px-6 py-8">{children}</main>
    </div>
  );
}

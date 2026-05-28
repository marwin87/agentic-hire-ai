import { NextRequest, NextResponse } from "next/server";
import {
  ACCESS_TOKEN_COOKIE,
  API_URL,
  AUTH_COOKIE_OPTIONS,
  REFRESH_TOKEN_COOKIE,
} from "@/lib/api";

export async function POST(request: NextRequest) {
  const body = await request.json();

  const upstream = await fetch(`${API_URL}/api/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!upstream.ok) {
    const error = await upstream.json();
    return NextResponse.json(error, { status: upstream.status });
  }

  const data = await upstream.json();
  const response = NextResponse.json({ success: true });

  response.cookies.set(ACCESS_TOKEN_COOKIE, data.access_token, {
    ...AUTH_COOKIE_OPTIONS,
    maxAge: data.expires_in,
  });

  if (data.refresh_token) {
    response.cookies.set(REFRESH_TOKEN_COOKIE, data.refresh_token, {
      ...AUTH_COOKIE_OPTIONS,
      maxAge: 30 * 24 * 60 * 60,
    });
  }

  return response;
}

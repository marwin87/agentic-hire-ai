// Server-side API URL — never exposed to the browser.
export const API_URL = process.env.API_URL ?? "http://localhost:8001";

// Cookie name used for the JWT access token.
export const ACCESS_TOKEN_COOKIE = "access_token";
export const REFRESH_TOKEN_COOKIE = "refresh_token";

// Default cookie options for httpOnly auth tokens.
export const AUTH_COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: "strict" as const,
  path: "/",
  secure: process.env.NODE_ENV === "production",
};

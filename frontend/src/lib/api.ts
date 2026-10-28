/**
 * Browser API client. Same-origin requests with HttpOnly session cookies; the
 * double-submit CSRF token is read from the `sc_csrf` cookie and sent as a header.
 * On 401 it tries one refresh, then reports the session as expired.
 */

export type Realm = "tenant" | "platform";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public body: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

const REFRESH_PATH: Record<Realm, string> = {
  tenant: "/api/v1/auth/refresh",
  platform: "/api/v1/platform/auth/refresh",
};

function readCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

async function csrfToken(): Promise<string> {
  const existing = readCookie("sc_csrf");
  if (existing) return existing;
  const response = await fetch("/api/v1/auth/csrf", { credentials: "same-origin" });
  const body = (await response.json()) as { csrf_token: string };
  return body.csrf_token;
}

async function send(
  method: string,
  path: string,
  body: unknown,
  extraHeaders: Record<string, string> = {},
): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json", ...extraHeaders };
  if (method !== "GET") {
    headers["X-CSRF-Token"] = await csrfToken();
    headers["Content-Type"] = "application/json";
  }
  return fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(
      response.status,
      String(data.code ?? "error"),
      String(data.detail ?? data.title ?? "Something went wrong"),
      data,
    );
  }
  return data as T;
}

export async function api<T>(
  realm: Realm,
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  let response = await send(method, path, body, headers);
  const isAuthCall = path.includes("/auth/login") || path.includes("/auth/refresh");
  if (response.status === 401 && !isAuthCall) {
    const refreshed = await send("POST", REFRESH_PATH[realm], undefined);
    if (refreshed.ok) response = await send(method, path, body, headers);
  }
  return parse<T>(response);
}

export type Me = {
  user_id: string;
  email: string;
  full_name: string;
  must_change_password: boolean;
  email_verified: boolean;
  tenant_id: string;
  business_name: string;
  roles: string[];
  permissions: string[];
  subscription: {
    status: string | null;
    access: "full" | "read_only" | "blocked";
    expiry_date: string | null;
    days_remaining: number | null;
  };
  memberships: { tenant_id: string; business_name: string }[];
};

export type PlatformMe = {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  must_change_password: boolean;
};

export type SessionResponse = { must_change_password: boolean; tenant_id?: string | null };

export type LoginDetails = {
  login_url: string;
  email: string;
  temporary_password: string | null;
  expires_at: string | null;
  share_message: string | null;
};

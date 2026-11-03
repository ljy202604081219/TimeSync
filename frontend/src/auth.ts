// Login closure for TimeSync. Contract: docs/contracts/auth-flow.md (backend ③).
//
// Two shapes exist and the UI must never guess which one it is in:
//   cloud  (DEMO_MODE=false, SANDBOX_MODE=true)  short-lived sandbox sessions
//   local  (DEMO_MODE=true)                      the four permanent demo tokens
// Every credential travels as `Authorization: Bearer <token>`. A 401 always
// means "log in again"; its body carries a stable `code` field.

export type Member = { id: string; name: string };

export type AuthConfig = {
  demo_mode: boolean;
  sandbox_mode: boolean;
  legacy_token_auth: boolean;
  members: Member[];
  session_ttl_minutes: number | null;
  login_path: string | null;
  logout_path: string | null;
  credential_header: string;
  notice: string;
};

export type AuthSession = {
  token: string;
  kind: "session" | "user" | "manual";
  user: { id: string; name: string } | null;
  expires_at: string | null;
};

const KEY = "timesync-auth";
// ①-era storage. Kept in sync so tools that still read it keep working.
const LEGACY_KEY = "timesync-token";

export class ApiFailure extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function loadAuth(): AuthSession | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as AuthSession;
      if (parsed?.token) return { ...parsed, kind: parsed.kind ?? "manual" };
    }
  } catch {
    // corrupt storage falls through to the legacy key
  }
  const legacy = localStorage.getItem(LEGACY_KEY);
  return legacy ? { token: legacy, kind: "user", user: null, expires_at: null } : null;
}

export function saveAuth(session: AuthSession | null): void {
  if (!session) {
    localStorage.removeItem(KEY);
    localStorage.removeItem(LEGACY_KEY);
    return;
  }
  localStorage.setItem(KEY, JSON.stringify(session));
  localStorage.setItem(LEGACY_KEY, session.token);
}

export async function fetchAuthConfig(): Promise<AuthConfig | null> {
  try {
    const response = await fetch("/api/auth/config", {cache:"no-store"});
    return response.ok ? ((await response.json()) as AuthConfig) : null;
  } catch {
    return null;
  }
}

export async function fetchDemoAccounts(): Promise<Record<string, string>> {
  const response = await fetch("/api/demo/accounts", {cache:"no-store"});
  if (!response.ok) return {};
  const data = await response.json();
  return data?.accounts ?? {};
}

async function readError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    return typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? response.status);
  } catch {
    return `请求失败（HTTP ${response.status}）`;
  }
}

export async function sandboxLogin(member: string): Promise<AuthSession> {
  if (!navigator.onLine) throw new Error("离线时不能登录，请恢复网络后重试。");
  const response = await fetch("/api/sandbox/sessions", {
    cache: "no-store",
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ member }),
  });
  if (!response.ok) throw new ApiFailure(await readError(response), response.status);
  const data = await response.json();
  return {
    token: data.token,
    kind: "session",
    user: data.user ?? null,
    expires_at: data.expires_at ?? null,
  };
}

/** Best effort. A session that is already gone must not block local cleanup. */
export async function sandboxLogout(token: string): Promise<void> {
  try {
    await fetch("/api/sandbox/session", {
      method: "DELETE",
      headers: { Authorization: "Bearer " + token },
    });
  } catch {
    // offline or already expired: the local logout still applies
  }
}

/** Minutes left in the session, or null when the credential does not expire. */
export function remainingMinutes(expiresAt: string | null): number | null {
  if (!expiresAt) return null;
  const left = Math.round((+new Date(expiresAt) - Date.now()) / 60000);
  return left >= 0 ? left : 0;
}

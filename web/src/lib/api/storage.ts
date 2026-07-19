import type { StoredAuthState } from "@/types/auth";
import type { ChatSessionState } from "@/types/session";

const AUTH_KEY = "shopcare.auth";
const SESSION_PREFIX = "shopcare.chat.session.";
export const AUTH_CHANGED_EVENT = "shopcare-auth-changed";

function emitAuthChanged() {
  if (isBrowser()) window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
}

function isBrowser() {
  return typeof window !== "undefined";
}

function isStoredAuthState(value: unknown): value is StoredAuthState {
  if (!value || typeof value !== "object") return false;
  const state = value as Partial<StoredAuthState>;
  const user = state.user as Partial<StoredAuthState["user"]> | undefined;
  return Boolean(
    state.token &&
    user &&
    typeof user.user_id !== "undefined" &&
    typeof user.username === "string" &&
    typeof user.is_admin === "boolean"
  );
}

export function loadAuthState(): StoredAuthState | null {
  if (!isBrowser()) return null;
  try {
    const raw = window.localStorage.getItem(AUTH_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (isStoredAuthState(parsed)) return parsed;
    window.localStorage.removeItem(AUTH_KEY);
    return null;
  } catch {
    window.localStorage.removeItem(AUTH_KEY);
    return null;
  }
}

export function saveAuthState(state: StoredAuthState) {
  if (!isBrowser()) return;
  window.localStorage.setItem(AUTH_KEY, JSON.stringify(state));
  emitAuthChanged();
}

export function clearAuthState() {
  if (!isBrowser()) return;
  window.localStorage.removeItem(AUTH_KEY);
  emitAuthChanged();
}

export function loadSession(customerId: string): ChatSessionState | null {
  if (!isBrowser() || !customerId) return null;
  try {
    const raw = window.localStorage.getItem(`${SESSION_PREFIX}${customerId}`);
    return raw ? (JSON.parse(raw) as ChatSessionState) : null;
  } catch {
    return null;
  }
}

export function saveSession(session: ChatSessionState) {
  if (!isBrowser()) return;
  window.localStorage.setItem(`${SESSION_PREFIX}${session.customer_id}`, JSON.stringify(session));
}

export function clearSession(customerId: string) {
  if (!isBrowser() || !customerId) return;
  window.localStorage.removeItem(`${SESSION_PREFIX}${customerId}`);
}

export function clearAllChatIdentity() {
  if (!isBrowser()) return;
  clearAuthState();
  for (let i = window.localStorage.length - 1; i >= 0; i -= 1) {
    const key = window.localStorage.key(i);
    if (key?.startsWith(SESSION_PREFIX) || key === "ai-support-chat") {
      window.localStorage.removeItem(key);
    }
  }
}

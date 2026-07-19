import type { CurrentUserResponse, LoginResponse, RegisterInput, RegisterResponse, StoredAuthState } from "@/types/auth";
import { apiFetch } from "./client";
import { clearAllChatIdentity, clearAuthState, loadAuthState, saveAuthState } from "./storage";

function persistAuth(response: LoginResponse | RegisterResponse): StoredAuthState {
  const state: StoredAuthState = {
    token: response.access_token,
    user: {
      user_id: response.user_id,
      username: response.username,
      full_name: response.full_name,
      is_admin: response.is_admin,
    },
  };
  saveAuthState(state);
  return state;
}

export async function login(username: string, password: string): Promise<StoredAuthState> {
  const response = await apiFetch<LoginResponse>("/api/v1/login", {
    method: "POST",
    json: { username, password },
  });
  return persistAuth(response);
}

export async function register(input: RegisterInput): Promise<StoredAuthState> {
  const response = await apiFetch<RegisterResponse>("/api/v1/register", {
    method: "POST",
    json: input,
  });
  return persistAuth(response);
}

export async function getCurrentUser(): Promise<CurrentUserResponse> {
  return apiFetch<CurrentUserResponse>("/api/v1/me", { auth: true });
}

export function getStoredAuth(): StoredAuthState | null {
  return loadAuthState();
}

export function logout() {
  clearAuthState();
}

export function clearIdentity() {
  clearAllChatIdentity();
}

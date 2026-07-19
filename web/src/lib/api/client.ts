import { FrontendApiError, messageForStatus } from "./errors";
import { loadAuthState } from "./storage";

export function getApiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");
}

interface ApiFetchOptions extends RequestInit {
  auth?: boolean;
  json?: unknown;
}

async function errorMessageFromResponse(response: Response): Promise<string> {
  try {
    const data = await response.clone().json();
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail) && detail.length > 0) return "账号必须是 8 位数字，密码至少 6 位。";
  } catch {
    // Ignore non-JSON error bodies and use status fallback below.
  }
  return messageForStatus(response.status);
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { auth = false, json, headers, ...init } = options;
  const requestHeaders = new Headers(headers);

  if (json !== undefined && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }

  if (auth) {
    const token = loadAuthState()?.token;
    if (!token) {
      throw new FrontendApiError("登录状态已失效，请重新登录。", { status: 401, code: "AUTH_REQUIRED" });
    }
    requestHeaders.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      headers: requestHeaders,
      body: json !== undefined ? JSON.stringify(json) : init.body,
    });
  } catch {
    throw new FrontendApiError("无法连接售后服务，请检查后端是否正常运行。", { code: "NETWORK_ERROR" });
  }

  if (!response.ok) {
    throw new FrontendApiError(await errorMessageFromResponse(response), { status: response.status, code: `HTTP_${response.status}` });
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiStream(path: string, options: ApiFetchOptions = {}): Promise<Response> {
  const { auth = false, json, headers, ...init } = options;
  const requestHeaders = new Headers(headers);

  if (json !== undefined && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }

  if (auth) {
    const token = loadAuthState()?.token;
    if (!token) {
      throw new FrontendApiError("登录状态已失效，请重新登录。", { status: 401, code: "AUTH_REQUIRED" });
    }
    requestHeaders.set("Authorization", `Bearer ${token}`);
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      headers: requestHeaders,
      body: json !== undefined ? JSON.stringify(json) : init.body,
    });
    if (!response.ok) {
      throw new FrontendApiError(await errorMessageFromResponse(response), { status: response.status, code: `HTTP_${response.status}` });
    }
    return response;
  } catch (error) {
    if (error instanceof FrontendApiError) throw error;
    throw new FrontendApiError("无法连接售后服务，请检查后端是否正常运行。", { code: "NETWORK_ERROR" });
  }
}

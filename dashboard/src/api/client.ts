import { env } from "../config/env";

export interface ApiErrorPayload {
  code: string;
  message: string;
  request_id?: string;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId?: string;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message || `API Error (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.code = payload.code || "API_ERROR";
    this.requestId = payload.request_id;
  }
}

export interface RequestOptions extends RequestInit {
  idempotencyKey?: string;
}

function generateUuid(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export async function apiClient<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const url = `${env.VITE_API_BASE_URL}${path}`;
  const requestId = generateUuid();
  const method = (options.method || "GET").toUpperCase();

  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  headers.set("X-Request-ID", requestId);

  if (options.body && typeof options.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  // Idempotency key on mutating endpoints
  if (["POST", "PATCH", "PUT", "DELETE"].includes(method)) {
    const idemKey = options.idempotencyKey || generateUuid();
    headers.set("Idempotency-Key", idemKey);
  }

  // Auth header if in jwt mode
  if (env.VITE_AUTH_MODE === "dev-bypass") {
    headers.set("X-Dev-Bypass", "true");
  }

  const response = await fetch(url, {
    ...options,
    method,
    headers,
  });

  if (!response.ok) {
    let payload: ApiErrorPayload = {
      code: `HTTP_${response.status}`,
      message: response.statusText || "Request failed",
      request_id: requestId,
    };
    try {
      const errJson = await response.json();
      if (errJson && errJson.error) {
        payload = errJson.error;
      } else if (errJson && errJson.detail) {
        payload.message = typeof errJson.detail === "string" ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      // Body not JSON
    }
    throw new ApiError(response.status, payload);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

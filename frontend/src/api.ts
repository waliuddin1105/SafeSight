let csrf = "";
export function setCsrf(value: string) {
  csrf = value;
}
export async function api<T = Record<string, unknown>>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (typeof options.body === "string")
    headers.set("Content-Type", "application/json");
  if (options.method && options.method !== "GET")
    headers.set("X-CSRF-Token", csrf);
  let response: Response;
  try {
    response = await fetch("/api/v1" + path, {
      ...options,
      headers,
      credentials: "same-origin",
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new Error("Cannot reach the SafeSight backend. Start it with: python -m safesight.backend");
  }
  if (response.status === 401) window.dispatchEvent(new Event("auth-expired"));
  if (response.status === 204 || response.status === 205) return undefined as T;
  const body = await response.text();
  let data: unknown;
  try {
    data = JSON.parse(body);
  } catch {
    const message = response.ok
      ? `The backend returned an invalid or empty JSON response (HTTP ${response.status}).`
      : `The SafeSight backend is unavailable or returned a non-JSON error (HTTP ${response.status}). Check that python -m safesight.backend is running.`;
    throw Object.assign(new Error(message), { status: response.status });
  }
  if (!response.ok) {
    const problem = data as { error?: { message?: string } } | null;
    throw Object.assign(new Error(problem?.error?.message || "Request failed"), {
      status: response.status,
    });
  }
  return data as T;
}

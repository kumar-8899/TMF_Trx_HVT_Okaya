// Fetch wrapper for the Python edge. Relative URLs (dev server proxies them).
// Attaches Bearer; 401 -> the registered logout handler; throws ApiError carrying
// the RFC-7807 problem body for display.

let _token: string | null = null;
let _onUnauthorized: () => void = () => {};

export function setToken(t: string | null): void {
  _token = t;
}
export function setUnauthorizedHandler(fn: () => void): void {
  _onUnauthorized = fn;
}

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, body: any) {
    super(body?.title || body?.detail || `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

interface Opts {
  auth?: boolean;
}

async function request(method: string, path: string, body?: unknown, opts: Opts = {}): Promise<any> {
  const auth = opts.auth ?? true;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && _token) headers["Authorization"] = `Bearer ${_token}`;

  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) _onUnauthorized();

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  get: (path: string, opts?: Opts) => request("GET", path, undefined, opts),
  post: (path: string, body?: unknown, opts?: Opts) => request("POST", path, body, opts),
};

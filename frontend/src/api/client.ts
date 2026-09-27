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

/** GET a binary body (image / PDF) WITH the bearer header — an <img>/<iframe> src can't send one, so
 * callers turn the result into a blob: URL. */
async function getBlob(path: string, opts: Opts = {}): Promise<Blob> {
  const headers: Record<string, string> = {};
  if ((opts.auth ?? true) && _token) headers["Authorization"] = `Bearer ${_token}`;
  const res = await fetch(path, { headers });
  if (res.status === 401) _onUnauthorized();
  if (!res.ok) {
    const text = await res.text();
    let body: any = null;
    try { body = text ? JSON.parse(text) : null; } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, body);
  }
  return res.blob();
}

/** POST a raw binary body (e.g. a PDF) with its own Content-Type; the response is JSON. */
async function postRaw(path: string, body: Blob, contentType: string, opts: Opts = {}): Promise<any> {
  const headers: Record<string, string> = { "Content-Type": contentType };
  if ((opts.auth ?? true) && _token) headers["Authorization"] = `Bearer ${_token}`;
  const res = await fetch(path, { method: "POST", headers, body });
  if (res.status === 401) _onUnauthorized();
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  getBlob,
  postRaw,
  get: (path: string, opts?: Opts) => request("GET", path, undefined, opts),
  post: (path: string, body?: unknown, opts?: Opts) => request("POST", path, body, opts),
  put: (path: string, body?: unknown, opts?: Opts) => request("PUT", path, body, opts),
  patch: (path: string, body?: unknown, opts?: Opts) => request("PATCH", path, body, opts),
  del: (path: string, opts?: Opts) => request("DELETE", path, undefined, opts),
};

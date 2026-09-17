import { QueryClient, useQuery } from '@tanstack/react-query';
let token = '';
export function setToken(value: string) { token = value; }
export class ApiError extends Error {
  constructor(public status: number, message: string, public code = '', public requestId = '') { super(message); }
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try { response = await fetch(path.startsWith('/health') ? path : `/api/v1${path}`, { ...options, headers: { 'Authorization': `Bearer ${token}`, ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } }); }
  catch (error) { if (error instanceof Error && error.name === 'AbortError') throw error; throw new ApiError(0, 'Cannot reach Relay. Check the local API process and your connection.'); }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.error ?? data?.detail ?? data;
    throw new ApiError(response.status, typeof detail?.message === 'string' ? detail.message : `Request failed (${response.status}).`, detail?.code, detail?.request_id ?? data?.request_id);
  }
  return data as T;
}
export const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 1500, retry: (count, error) => count < 2 && (!(error instanceof ApiError) || error.status === 0 || error.status >= 500), retryDelay: n => Math.min(500 * 2 ** n, 2000), refetchOnWindowFocus: true, refetchIntervalInBackground: false }, mutations: { retry: false } } });
export function useApi<T>(path: string, interval: number | false = 5000) {
  return useQuery<T, ApiError>({ queryKey: [path], queryFn: ({ signal }) => request<T>(path, { signal }), refetchInterval: interval });
}
export function post<T>(path: string, body: unknown = {}, key?: string) {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body), headers: key ? { 'Idempotency-Key': key } : undefined });
}
export const terminal = (state: string) => ['succeeded', 'failed', 'canceled'].includes(state);

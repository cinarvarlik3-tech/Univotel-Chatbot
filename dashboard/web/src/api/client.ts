/**
 * Typed fetch wrapper + React Query hooks.
 *
 * Auth is HTTP Basic handled by the browser — no token is stored by this app, so
 * there is nothing here to leak. A 401 means the browser will re-challenge on the
 * next navigation; a 503 means the server has no credentials configured.
 */
import { useQuery, type UseQueryOptions } from '@tanstack/react-query';
import type {
  Breakdowns,
  ConversationDetail,
  ConversationFilters,
  ConversationList,
  ConversationLogs,
  ConversationMessages,
  LogDetail,
  LogFilters,
  LogList,
  Meta,
  StatsSummary,
  TriggerList,
} from './types';

const BASE = '/api/dashboard';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** The server has no DASHBOARD_USER/PASSWORD set — distinct from bad credentials. */
  get isNotConfigured(): boolean {
    return this.status === 503;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

type QueryParams = Record<string, unknown>;

function toQueryString(params: QueryParams): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      // Repeated keys, matching FastAPI's Query(list) binding.
      value.forEach((item) => search.append(key, String(item)));
    } else {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

/**
 * Absolute URL built from `location.origin`, which never carries credentials.
 *
 * A relative path would be resolved against the document URL instead, and if that
 * URL has embedded credentials (http://user:pass@host/…) the resulting URL does
 * too — which `fetch()` rejects outright with "Request cannot be constructed from
 * a URL that includes credentials". Basic auth still travels normally via the
 * browser's own credential cache.
 */
function url(path: string, params: QueryParams): string {
  const origin = typeof window === 'undefined' ? '' : window.location.origin;
  return `${origin}${BASE}${path}${toQueryString(params)}`;
}

async function get<T>(path: string, params: QueryParams = {}): Promise<T> {
  const response = await fetch(url(path, params), {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // Non-JSON error body (e.g. a proxy's HTML page) — keep the status text.
    }
    throw new ApiError(response.status, detail);
  }

  return response.json() as Promise<T>;
}

export const api = {
  meta: () => get<Meta>('/meta'),
  conversations: (filters: ConversationFilters) =>
    get<ConversationList>('/infogatherer/conversations', { ...filters }),
  conversation: (cwid: number) =>
    get<ConversationDetail>(`/infogatherer/conversations/${cwid}`),
  conversationLogs: (cwid: number) =>
    get<ConversationLogs>(`/infogatherer/conversations/${cwid}/logs`),
  conversationMessages: (cwid: number) =>
    get<ConversationMessages>(`/infogatherer/conversations/${cwid}/messages`),
  logs: (filters: LogFilters) => get<LogList>('/infogatherer/logs', { ...filters }),
  logDetail: (logId: string) =>
    get<LogDetail>(`/infogatherer/logs/${encodeURIComponent(logId)}`),
  statsSummary: () => get<StatsSummary>('/infogatherer/stats/summary'),
  breakdowns: () => get<Breakdowns>('/infogatherer/stats/breakdowns'),
  triggers: (limit = 20) =>
    get<TriggerList>('/infogatherer/stats/human-needed-triggers', { limit }),
};

// Lists and stats poll; detail views do not — a panel must not mutate under the
// reader's cursor while they are reading it (§9).
const LIST_OPTIONS = { staleTime: 15_000, refetchInterval: 30_000 } as const;
const DETAIL_OPTIONS = { staleTime: 60_000, refetchInterval: false } as const;

type Options<T> = Omit<UseQueryOptions<T, ApiError>, 'queryKey' | 'queryFn'>;

export function useMeta(options?: Options<Meta>) {
  return useQuery({
    queryKey: ['meta'],
    queryFn: api.meta,
    staleTime: Infinity,
    ...options,
  });
}

export function useConversations(filters: ConversationFilters, options?: Options<ConversationList>) {
  return useQuery({
    queryKey: ['conversations', filters],
    queryFn: () => api.conversations(filters),
    ...LIST_OPTIONS,
    ...options,
  });
}

export function useConversationLogs(cwid: number | null) {
  return useQuery({
    queryKey: ['conversationLogs', cwid],
    queryFn: () => api.conversationLogs(cwid as number),
    enabled: cwid !== null,
    ...DETAIL_OPTIONS,
  });
}

export function useConversationMessages(cwid: number | null) {
  return useQuery({
    queryKey: ['conversationMessages', cwid],
    queryFn: () => api.conversationMessages(cwid as number),
    enabled: cwid !== null,
    ...DETAIL_OPTIONS,
  });
}

export function useLogs(filters: LogFilters, options?: Options<LogList>) {
  return useQuery({
    queryKey: ['logs', filters],
    queryFn: () => api.logs(filters),
    ...LIST_OPTIONS,
    ...options,
  });
}

export function useLogDetail(logId: string | null) {
  return useQuery({
    queryKey: ['logDetail', logId],
    queryFn: () => api.logDetail(logId as string),
    enabled: logId !== null,
    ...DETAIL_OPTIONS,
  });
}

export function useStatsSummary() {
  return useQuery({ queryKey: ['statsSummary'], queryFn: api.statsSummary, ...LIST_OPTIONS });
}

export function useBreakdowns() {
  return useQuery({ queryKey: ['breakdowns'], queryFn: api.breakdowns, ...LIST_OPTIONS });
}

export function useTriggers(limit = 20) {
  return useQuery({
    queryKey: ['triggers', limit],
    queryFn: () => api.triggers(limit),
    ...LIST_OPTIONS,
  });
}

/**
 * Table filters, mirrored into the URL so a filtered view is shareable and
 * survives a refresh (DASHBOARD_SPEC.md §8.2).
 *
 * Panel params are owned by state/panel.ts; these helpers never touch them.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { ConversationFilters, LogFilters, Status } from '../api/types';

const PAGE_SIZE = 50;
const LOG_PAGE_SIZE = 100;

function readList(params: URLSearchParams, key: string): string[] | undefined {
  const values = params.getAll(key).filter(Boolean);
  return values.length ? values : undefined;
}

function readString(params: URLSearchParams, key: string): string | undefined {
  return params.get(key)?.trim() || undefined;
}

function readInt(params: URLSearchParams, key: string, fallback: number): number {
  const parsed = Number.parseInt(params.get(key) ?? '', 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

export function useConversationFilters(overrides?: Partial<ConversationFilters>) {
  const [searchParams, setSearchParams] = useSearchParams();

  const filters = useMemo<ConversationFilters>(
    () => ({
      status: readList(searchParams, 'status') as Status[] | undefined,
      flow_state: readList(searchParams, 'flow_state'),
      q: readString(searchParams, 'q'),
      from: readString(searchParams, 'from'),
      to: readString(searchParams, 'to'),
      sort: (readString(searchParams, 'sort') ?? 'last_activity') as ConversationFilters['sort'],
      dir: (readString(searchParams, 'dir') ?? 'desc') as ConversationFilters['dir'],
      limit: PAGE_SIZE,
      offset: readInt(searchParams, 'offset', 0),
      ...overrides,
    }),
    [searchParams, overrides],
  );

  const update = useCallback(
    (patch: Partial<ConversationFilters>) => {
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(patch)) {
        next.delete(key);
        if (value === undefined || value === null || value === '') continue;
        if (Array.isArray(value)) value.forEach((v) => next.append(key, String(v)));
        else next.set(key, String(value));
      }
      // Any filter change invalidates the current page — staying on page 4 of a
      // now-shorter result set shows an empty table for no reason.
      if (!('offset' in patch)) next.delete('offset');
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const clear = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    for (const key of ['status', 'flow_state', 'q', 'from', 'to', 'offset']) {
      next.delete(key);
    }
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const hasActiveFilters = useMemo(
    () =>
      Boolean(
        filters.status?.length ||
          filters.flow_state?.length ||
          filters.q ||
          filters.from ||
          filters.to,
      ),
    [filters],
  );

  return { filters, update, clear, hasActiveFilters, pageSize: PAGE_SIZE };
}

export function useLogFilters() {
  const [searchParams, setSearchParams] = useSearchParams();

  const filters = useMemo<LogFilters>(() => {
    const isSuccessRaw = readString(searchParams, 'is_success');
    const conversationRaw = readString(searchParams, 'conversation');
    return {
      conversation: conversationRaw ? Number.parseInt(conversationRaw, 10) : undefined,
      log_level: readList(searchParams, 'log_level'),
      is_success:
        isSuccessRaw === 'true' ? true : isSuccessRaw === 'false' ? false : undefined,
      operation_layer: readString(searchParams, 'operation_layer'),
      which_run: readString(searchParams, 'which_run'),
      q: readString(searchParams, 'q'),
      from: readString(searchParams, 'from'),
      to: readString(searchParams, 'to'),
      limit: LOG_PAGE_SIZE,
      offset: readInt(searchParams, 'offset', 0),
    };
  }, [searchParams]);

  const update = useCallback(
    (patch: Partial<LogFilters>) => {
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(patch)) {
        next.delete(key);
        if (value === undefined || value === null || value === '') continue;
        if (Array.isArray(value)) value.forEach((v) => next.append(key, String(v)));
        else next.set(key, String(value));
      }
      if (!('offset' in patch)) next.delete('offset');
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const clear = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    for (const key of [
      'conversation', 'log_level', 'is_success', 'operation_layer',
      'which_run', 'q', 'from', 'to', 'offset',
    ]) {
      next.delete(key);
    }
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const hasActiveFilters = useMemo(
    () =>
      Boolean(
        filters.conversation ||
          filters.log_level?.length ||
          filters.is_success !== undefined ||
          filters.operation_layer ||
          filters.which_run ||
          filters.q ||
          filters.from ||
          filters.to,
      ),
    [filters],
  );

  return { filters, update, clear, hasActiveFilters, pageSize: LOG_PAGE_SIZE };
}

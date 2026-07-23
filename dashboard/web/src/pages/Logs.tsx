/** Standalone logs browser (DASHBOARD_SPEC.md §8.4). */
import { useEffect, useState } from 'react';
import { useLogs, useMeta } from '../api/client';
import LogTable from '../components/LogTable';
import { StatusLegend } from '../components/StatusChip';
import { ErrorState, PageHeader } from '../components/States';
import { useLogFilters } from '../state/filters';

interface Props {
  onOpenDetail: (logId: string, trigger: HTMLElement) => void;
  onOpenConversation: (cwid: number, trigger: HTMLElement) => void;
  activeLogId: string | null;
}

export default function Logs({ onOpenDetail, onOpenConversation, activeLogId }: Props) {
  const { filters, update, clear, hasActiveFilters, pageSize } = useLogFilters();
  const meta = useMeta();
  const { data, isLoading, error, refetch } = useLogs(filters);
  const [search, setSearch] = useState(filters.q ?? '');

  useEffect(() => setSearch(filters.q ?? ''), [filters.q]);
  useEffect(() => {
    const handle = window.setTimeout(() => {
      if ((filters.q ?? '') !== search) update({ q: search || undefined });
    }, 300);
    return () => window.clearTimeout(handle);
  }, [search, filters.q, update]);

  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <>
      <PageHeader
        title="Logs"
        subtitle={data ? `${data.total} ${data.total === 1 ? 'row' : 'rows'}` : 'Loading…'}
      />

      <div className="mb-3">
        <StatusLegend variant="log" />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          type="search"
          className="input w-56"
          placeholder="Search explanation or class"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label="Search logs"
        />
        <input
          type="number"
          className="input w-40"
          placeholder="Conversation #id"
          value={filters.conversation ?? ''}
          onChange={(event) =>
            update({
              conversation: event.target.value ? Number(event.target.value) : undefined,
            })
          }
          aria-label="Filter by conversation id"
        />
        <select
          className="input"
          value={filters.log_level?.[0] ?? ''}
          onChange={(event) =>
            update({ log_level: event.target.value ? [event.target.value] : undefined })
          }
          aria-label="Filter by log level"
        >
          <option value="">All levels</option>
          {(meta.data?.log_levels ?? []).map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
        <select
          className="input"
          value={filters.is_success === undefined ? '' : String(filters.is_success)}
          onChange={(event) =>
            update({
              is_success: event.target.value === '' ? undefined : event.target.value === 'true',
            })
          }
          aria-label="Filter by success"
        >
          <option value="">Any outcome</option>
          <option value="true">Success</option>
          <option value="false">Not success</option>
        </select>
        <select
          className="input"
          value={filters.operation_layer ?? ''}
          onChange={(event) => update({ operation_layer: event.target.value || undefined })}
          aria-label="Filter by operation layer"
        >
          <option value="">All layers</option>
          {(meta.data?.operation_layers ?? []).map((layer) => (
            <option key={layer} value={layer}>
              {layer}
            </option>
          ))}
        </select>
        <select
          className="input"
          value={filters.which_run ?? ''}
          onChange={(event) => update({ which_run: event.target.value || undefined })}
          aria-label="Filter by run type"
        >
          <option value="">All runs</option>
          {(meta.data?.which_runs ?? []).map((run) => (
            <option key={run} value={run}>
              {run}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-[11px] text-ink3">
          From
          <input
            type="date"
            className="input"
            value={filters.from ?? ''}
            onChange={(event) => update({ from: event.target.value || undefined })}
            aria-label="Logged from"
          />
        </label>
        <label className="flex items-center gap-1 text-[11px] text-ink3">
          To
          <input
            type="date"
            className="input"
            value={filters.to ?? ''}
            onChange={(event) => update({ to: event.target.value || undefined })}
            aria-label="Logged to"
          />
        </label>
        {hasActiveFilters && (
          <button type="button" className="btn" onClick={clear}>
            Clear
          </button>
        )}
      </div>

      <LogTable
        rows={data?.rows ?? []}
        total={data?.total ?? 0}
        limit={pageSize}
        offset={filters.offset ?? 0}
        isLoading={isLoading}
        activeLogId={activeLogId}
        onOpenDetail={onOpenDetail}
        onOpenConversation={onOpenConversation}
        onOffsetChange={(offset) => update({ offset })}
        hasActiveFilters={hasActiveFilters}
        onClearFilters={clear}
      />
    </>
  );
}

/**
 * Filter bar — one row above the table (DASHBOARD_SPEC.md §8.2).
 *
 * Not in the original brief; added because a table with no way to isolate the
 * failures stops being usable past one screenful. Entirely removable.
 */
import { useEffect, useState } from 'react';
import type { ConversationFilters, Status } from '../api/types';
import { STATUS_STYLES, statusTextColor } from '../lib/colors';

interface Props {
  filters: ConversationFilters;
  flowStates: string[];
  onChange: (patch: Partial<ConversationFilters>) => void;
  onClear: () => void;
  hasActiveFilters: boolean;
}

export default function Filters({
  filters,
  flowStates,
  onChange,
  onClear,
  hasActiveFilters,
}: Props) {
  const [search, setSearch] = useState(filters.q ?? '');

  // Debounce so each keystroke does not issue a request; sync back when the URL
  // changes from elsewhere (e.g. Clear).
  useEffect(() => setSearch(filters.q ?? ''), [filters.q]);
  useEffect(() => {
    const handle = window.setTimeout(() => {
      if ((filters.q ?? '') !== search) onChange({ q: search || undefined });
    }, 300);
    return () => window.clearTimeout(handle);
  }, [search, filters.q, onChange]);

  const selectedStatuses = filters.status ?? [];

  function toggleStatus(status: Status) {
    const next = selectedStatuses.includes(status)
      ? selectedStatuses.filter((s) => s !== status)
      : [...selectedStatuses, status];
    onChange({ status: next.length ? next : undefined });
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <input
        type="search"
        className="input w-56"
        placeholder="Search name, phone, or #id"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        aria-label="Search conversations"
      />

      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filter by status">
        {(Object.keys(STATUS_STYLES) as Status[]).map((status) => {
          const active = selectedStatuses.includes(status);
          const color = statusTextColor(status);
          return (
            <button
              key={status}
              type="button"
              className="chip transition-colors"
              aria-pressed={active}
              title={STATUS_STYLES[status].description}
              style={{
                color: active ? '#0A0C10' : color,
                borderColor: color,
                backgroundColor: active ? color : 'transparent',
              }}
              onClick={() => toggleStatus(status)}
            >
              <span aria-hidden>{STATUS_STYLES[status].icon}</span>
              {STATUS_STYLES[status].label}
            </button>
          );
        })}
      </div>

      <select
        className="input"
        value={filters.flow_state?.[0] ?? ''}
        onChange={(event) =>
          onChange({ flow_state: event.target.value ? [event.target.value] : undefined })
        }
        aria-label="Filter by flow state"
      >
        <option value="">All flow states</option>
        {flowStates.map((state) => (
          <option key={state} value={state}>
            {state}
          </option>
        ))}
      </select>

      <label className="flex items-center gap-1 text-[11px] text-ink3">
        From
        <input
          type="date"
          className="input"
          value={filters.from ?? ''}
          onChange={(event) => onChange({ from: event.target.value || undefined })}
          aria-label="Created from"
        />
      </label>
      <label className="flex items-center gap-1 text-[11px] text-ink3">
        To
        <input
          type="date"
          className="input"
          value={filters.to ?? ''}
          onChange={(event) => onChange({ to: event.target.value || undefined })}
          aria-label="Created to"
        />
      </label>

      {hasActiveFilters && (
        <button type="button" className="btn" onClick={onClear}>
          Clear
        </button>
      )}
    </div>
  );
}

/**
 * Log rows (DASHBOARD_SPEC.md §8.2 panel, §8.4 page).
 *
 * Two presentations of the same row: `LogRowList` for the right panel (compact)
 * and `LogTable` for the standalone Logs page (full columns). Both colour-code
 * per §4.9 and both end in a Details button.
 */
import type { LogRow } from '../api/types';
import { STATUS_STYLES } from '../lib/colors';
import { EM_DASH, formatDateTime, formatStateTransition, formatUtcTitle, truncate } from '../lib/format';
import { DerivedChip, StatusChip } from './StatusChip';
import { EmptyState, Pagination, SkeletonRows } from './States';

/** Compact list used inside the conversation-logs panel. */
export function LogRowList({
  rows,
  isLoading,
  onOpenDetail,
}: {
  rows: LogRow[];
  isLoading: boolean;
  onOpenDetail: (logId: string, trigger: HTMLElement) => void;
}) {
  if (isLoading) {
    return (
      <div className="space-y-2 p-3" aria-hidden>
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="skeleton h-14 w-full" />
        ))}
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <EmptyState
        title="No logs for this conversation"
        hint="InfoGatherer writes a log row on escalations, abstains, and divergence turns — a clean run can legitimately have none."
      />
    );
  }

  return (
    <ul className="divide-y divide-border/60">
      {rows.map((row) => {
        const style = STATUS_STYLES[row.log_status];
        return (
          <li
            key={row.id}
            className="px-3 py-2.5"
            style={{ backgroundColor: style.tint, boxShadow: `inset 3px 0 0 ${style.color}` }}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span
                    className="tabular text-[11px] text-ink3"
                    title={formatUtcTitle(row.created_at)}
                  >
                    {formatDateTime(row.created_at)}
                  </span>
                  <StatusChip status={row.log_status} variant="log" compact />
                  {row.derived && <DerivedChip />}
                </div>
                <div className="mt-1 truncate font-mono text-[12px] text-ink2" title={row.operation_label}>
                  {row.operation_label}
                </div>
                {row.explanation && (
                  <p className="mt-1 text-[12px] text-ink2" dir="auto">
                    {truncate(row.explanation, 140)}
                  </p>
                )}
              </div>
              <button
                type="button"
                className="btn shrink-0"
                onClick={(event) => onOpenDetail(row.id, event.currentTarget)}
                aria-label={`Details for log at ${formatDateTime(row.created_at)}`}
              >
                Details
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** Full table used on the standalone Logs page. */
export default function LogTable({
  rows,
  total,
  limit,
  offset,
  isLoading,
  activeLogId,
  onOpenDetail,
  onOpenConversation,
  onOffsetChange,
  hasActiveFilters,
  onClearFilters,
}: {
  rows: LogRow[];
  total: number;
  limit: number;
  offset: number;
  isLoading: boolean;
  activeLogId: string | null;
  onOpenDetail: (logId: string, trigger: HTMLElement) => void;
  onOpenConversation: (cwid: number, trigger: HTMLElement) => void;
  onOffsetChange: (offset: number) => void;
  hasActiveFilters: boolean;
  onClearFilters: () => void;
}) {
  const headers = [
    'Time', 'Conversation', 'Operation', 'Level', 'Success',
    'Code', 'Internal class', 'Transition', 'Explanation', '',
  ];

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <caption className="sr-only">
            InfoGatherer log rows, colour-coded by outcome with a labelled status chip.
          </caption>
          <thead>
            <tr>
              {headers.map((header, index) => (
                <th
                  key={index}
                  scope="col"
                  className={index === headers.length - 1 ? 'th sticky right-0' : 'th'}
                >
                  {header || <span className="sr-only">Actions</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading && <SkeletonRows rows={10} cols={headers.length} />}

            {!isLoading &&
              rows.map((row) => {
                const style = STATUS_STYLES[row.log_status];
                const isActive = activeLogId === row.id;
                return (
                  <tr
                    key={row.id}
                    className={isActive ? 'bg-surface2' : 'hover:bg-surface2/60'}
                    style={{
                      backgroundColor: isActive ? undefined : style.tint,
                      boxShadow: `inset 3px 0 0 ${style.color}`,
                    }}
                  >
                    <td className="td tabular whitespace-nowrap text-[12px] text-ink2">
                      <span title={formatUtcTitle(row.created_at)}>
                        {formatDateTime(row.created_at)}
                      </span>
                    </td>
                    <td className="td whitespace-nowrap">
                      {row.chatwoot_conversation_id ? (
                        <button
                          type="button"
                          className="font-mono text-status-interrupt hover:underline"
                          onClick={(event) =>
                            onOpenConversation(
                              row.chatwoot_conversation_id as number,
                              event.currentTarget,
                            )
                          }
                        >
                          #{row.chatwoot_conversation_id}
                        </button>
                      ) : (
                        <span className="text-ink3">{EM_DASH}</span>
                      )}
                    </td>
                    <td className="td whitespace-nowrap font-mono text-[12px] text-ink2">
                      <div className="flex items-center gap-1.5">
                        {row.operation_label}
                        {row.derived && <DerivedChip />}
                      </div>
                    </td>
                    <td className="td whitespace-nowrap">
                      <StatusChip status={row.log_status} variant="log" />
                    </td>
                    <td className="td whitespace-nowrap text-[12px] text-ink2">
                      {row.is_success === null ? EM_DASH : row.is_success ? 'yes' : 'no'}
                    </td>
                    <td className="td whitespace-nowrap font-mono text-[12px] text-ink2">
                      {row.status_code ?? EM_DASH}
                    </td>
                    <td className="td whitespace-nowrap font-mono text-[12px] text-ink2">
                      {row.internal_class ?? EM_DASH}
                    </td>
                    <td className="td whitespace-nowrap font-mono text-[12px] text-ink3">
                      {formatStateTransition(row.from_state, row.to_state)}
                    </td>
                    <td className="td text-[12px] text-ink2">
                      <span
                        className="block max-w-[260px] truncate"
                        dir="auto"
                        title={row.explanation ?? undefined}
                      >
                        {truncate(row.explanation, 200)}
                      </span>
                    </td>
                    <td
                      className="td sticky right-0 text-right"
                      style={{
                        backgroundColor: isActive ? '#171C24' : '#12161C',
                        boxShadow: 'inset 1px 0 0 #242C38',
                      }}
                    >
                      <button
                        type="button"
                        className="btn"
                        onClick={(event) => onOpenDetail(row.id, event.currentTarget)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>

      {!isLoading && rows.length === 0 && (
        <EmptyState
          title={hasActiveFilters ? 'No logs match these filters' : 'No logs yet'}
          hint={
            hasActiveFilters
              ? undefined
              : 'InfoGatherer writes log rows on escalations, abstains, and divergence turns.'
          }
          action={
            hasActiveFilters ? (
              <button type="button" className="btn mt-1" onClick={onClearFilters}>
                Clear filters
              </button>
            ) : undefined
          }
        />
      )}

      <Pagination total={total} limit={limit} offset={offset} onChange={onOffsetChange} />
    </div>
  );
}

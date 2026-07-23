/**
 * Conversation table (DASHBOARD_SPEC.md §8.2).
 *
 * Columns are exactly as specified: Lead's name, Conversation, Flow state, then
 * the two identically-sized action buttons. Status lives as a chip beside the
 * flow state plus a coloured left rail — never colour alone.
 */
import type { ConversationRow, Status } from '../api/types';
import { NOTE_STYLE, STATUS_STYLES } from '../lib/colors';
import { EM_DASH, formatRelative, truncate } from '../lib/format';
import { StatusChip } from './StatusChip';
import { EmptyState, Pagination, SkeletonRows } from './States';

interface Props {
  rows: ConversationRow[];
  total: number;
  limit: number;
  offset: number;
  isLoading: boolean;
  activeCwid: number | null;
  onOpenLogs: (cwid: number, trigger: HTMLElement) => void;
  onOpenChat: (cwid: number, trigger: HTMLElement) => void;
  onOffsetChange?: (offset: number) => void;
  sort?: string;
  dir?: string;
  onSort?: (column: string) => void;
  hasActiveFilters?: boolean;
  onClearFilters?: () => void;
  emptyTitle?: string;
  emptyHint?: string;
}

const COLUMNS: { key: string; label: string; sortable: boolean }[] = [
  { key: 'name', label: "Lead's name", sortable: true },
  { key: 'cwid', label: 'Conversation', sortable: true },
  { key: 'flow_state', label: 'Flow state', sortable: false },
  { key: 'actions', label: '', sortable: false },
];

export default function ConversationTable({
  rows,
  total,
  limit,
  offset,
  isLoading,
  activeCwid,
  onOpenLogs,
  onOpenChat,
  onOffsetChange,
  sort,
  dir,
  onSort,
  hasActiveFilters,
  onClearFilters,
  emptyTitle = 'No conversations yet',
  emptyHint,
}: Props) {
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <caption className="sr-only">
            InfoGatherer conversations. Each row is colour-coded by status; the
            status is also shown as a labelled chip.
          </caption>
          <thead>
            <tr>
              {COLUMNS.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className="th"
                  aria-sort={
                    sort === column.key
                      ? dir === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : undefined
                  }
                >
                  {column.sortable && onSort ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 uppercase tracking-[0.03em] hover:text-ink"
                      onClick={() => onSort(column.key)}
                    >
                      {column.label}
                      <span aria-hidden className="text-ink3">
                        {sort === column.key ? (dir === 'asc' ? '↑' : '↓') : '↕'}
                      </span>
                    </button>
                  ) : (
                    column.label || <span className="sr-only">Actions</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading && <SkeletonRows rows={8} cols={4} />}

            {!isLoading &&
              rows.map((row) => {
                const style = STATUS_STYLES[row.status as Status];
                const isActive = activeCwid === row.chatwoot_conversation_id;
                return (
                  <tr
                    key={row.id}
                    className={[
                      'group cursor-pointer transition-colors',
                      isActive ? 'bg-surface2' : 'hover:bg-surface2/60',
                    ].join(' ')}
                    style={{
                      backgroundColor: isActive ? undefined : style.tint,
                      boxShadow: `inset 3px 0 0 ${style.color}`,
                    }}
                    onClick={(event) =>
                      onOpenChat(row.chatwoot_conversation_id, event.currentTarget)
                    }
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onOpenChat(row.chatwoot_conversation_id, event.currentTarget);
                      }
                    }}
                    tabIndex={0}
                    aria-label={`Conversation ${row.chatwoot_conversation_id}, ${row.lead_name}, ${style.label}`}
                  >
                    <td className="td">
                      <div className="flex items-center gap-2">
                        <span
                          className={
                            row.lead_name_is_fallback
                              ? 'italic text-ink3'
                              : 'font-medium text-ink'
                          }
                          title={
                            row.lead_name_is_fallback
                              ? 'No contact name on record — showing phone number'
                              : undefined
                          }
                        >
                          {row.lead_name}
                        </span>
                      </div>
                      {row.failure_reason && (
                        <div
                          className="mt-0.5 text-[11px] text-ink3"
                          title={row.failure_reason}
                        >
                          {truncate(row.failure_reason, 64)}
                        </div>
                      )}
                    </td>

                    <td className="td tabular whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5">
                        <span className="font-mono text-ink2">
                          #{row.chatwoot_conversation_id}
                        </span>
                        {row.has_unresolved_note && (
                          <span
                            className="inline-block h-2 w-2 shrink-0 rounded-full"
                            style={{ backgroundColor: NOTE_STYLE.dot }}
                            title="This conversation has an unresolved note"
                            aria-label="Has an unresolved note"
                            role="img"
                          />
                        )}
                      </span>
                      <div className="mt-0.5 text-[11px] text-ink3">
                        {row.message_count} msg · {row.log_count} logs ·{' '}
                        {formatRelative(row.last_activity_at)}
                      </div>
                    </td>

                    <td className="td whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[12px] text-ink2">
                          {row.flow_state}
                        </span>
                        <StatusChip status={row.status} />
                      </div>
                    </td>

                    <td className="td">
                      <div
                        className="flex items-center justify-end gap-2"
                        onClick={(event) => event.stopPropagation()}
                        onKeyDown={(event) => event.stopPropagation()}
                      >
                        <button
                          type="button"
                          className="btn-row"
                          onClick={(event) =>
                            onOpenLogs(row.chatwoot_conversation_id, event.currentTarget)
                          }
                          aria-label={`Logs for conversation ${row.chatwoot_conversation_id}`}
                        >
                          Logs
                        </button>
                        <button
                          type="button"
                          className="btn-row"
                          onClick={(event) =>
                            onOpenChat(row.chatwoot_conversation_id, event.currentTarget)
                          }
                          aria-label={`Conversation ${row.chatwoot_conversation_id} transcript`}
                        >
                          Conversation
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>

      {!isLoading && rows.length === 0 && (
        <EmptyState
          title={hasActiveFilters ? 'No conversations match these filters' : emptyTitle}
          hint={hasActiveFilters ? undefined : emptyHint}
          action={
            hasActiveFilters && onClearFilters ? (
              <button type="button" className="btn mt-1" onClick={onClearFilters}>
                Clear filters
              </button>
            ) : undefined
          }
        />
      )}

      {onOffsetChange && (
        <Pagination
          total={total}
          limit={limit}
          offset={offset}
          onChange={onOffsetChange}
        />
      )}
    </div>
  );
}

export function ConversationSummaryLine({ row }: { row: ConversationRow }) {
  return (
    <span className="text-[11px] text-ink3">
      {row.failure_reason ? truncate(row.failure_reason, 80) : EM_DASH}
    </span>
  );
}

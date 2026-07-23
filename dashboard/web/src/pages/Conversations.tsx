/** Conversations page (DASHBOARD_SPEC.md §8.2). */
import { useConversations, useMeta } from '../api/client';
import ConversationTable from '../components/ConversationTable';
import Filters from '../components/Filters';
import { StatusLegend } from '../components/StatusChip';
import { ErrorState, PageHeader } from '../components/States';
import { useConversationFilters } from '../state/filters';

interface Props {
  onOpenLogs: (cwid: number, trigger: HTMLElement) => void;
  onOpenChat: (cwid: number, trigger: HTMLElement) => void;
  activeCwid: number | null;
}

export default function Conversations({ onOpenLogs, onOpenChat, activeCwid }: Props) {
  const { filters, update, clear, hasActiveFilters, pageSize } = useConversationFilters();
  const meta = useMeta();
  const { data, isLoading, error, refetch } = useConversations(filters);

  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;

  function toggleSort(column: string) {
    if (filters.sort === column) {
      update({ dir: filters.dir === 'asc' ? 'desc' : 'asc' });
    } else {
      update({ sort: column as typeof filters.sort, dir: 'desc' });
    }
  }

  return (
    <>
      <PageHeader
        title="Conversations"
        subtitle={
          data
            ? `${data.total} ${data.total === 1 ? 'conversation' : 'conversations'}`
            : 'Loading…'
        }
      />

      <div className="mb-3">
        <StatusLegend />
      </div>

      <Filters
        filters={filters}
        flowStates={meta.data?.flow_states ?? []}
        onChange={update}
        onClear={clear}
        hasActiveFilters={hasActiveFilters}
      />

      <ConversationTable
        rows={data?.rows ?? []}
        total={data?.total ?? 0}
        limit={pageSize}
        offset={filters.offset ?? 0}
        isLoading={isLoading}
        activeCwid={activeCwid}
        onOpenLogs={onOpenLogs}
        onOpenChat={onOpenChat}
        emptyHint="Conversations appear here once InfoGatherer processes an inbound message."
        onOffsetChange={(offset) => update({ offset })}
        sort={filters.sort}
        dir={filters.dir}
        onSort={toggleSort}
        hasActiveFilters={hasActiveFilters}
        onClearFilters={clear}
      />
    </>
  );
}

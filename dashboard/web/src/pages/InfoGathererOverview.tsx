/**
 * InfoGatherer landing page (DASHBOARD_SPEC.md §8.1).
 *
 * The route was listed explicitly, so it renders something rather than
 * redirecting: the KPI row plus the ten most recent conversations. No new
 * endpoints — it reuses the statistics summary and the conversation list.
 */
import { useConversations, useStatsSummary } from '../api/client';
import ConversationTable from '../components/ConversationTable';
import { StatCards } from '../components/StatCard';
import { StatusLegend } from '../components/StatusChip';
import { ErrorState, PageHeader } from '../components/States';

interface Props {
  onOpenLogs: (cwid: number, trigger: HTMLElement) => void;
  onOpenChat: (cwid: number, trigger: HTMLElement) => void;
  activeCwid: number | null;
  onNavigate: (path: string) => void;
}

const RECENT_LIMIT = 10;

export default function InfoGathererOverview({
  onOpenLogs,
  onOpenChat,
  activeCwid,
  onNavigate,
}: Props) {
  const summary = useStatsSummary();
  const recent = useConversations({ limit: RECENT_LIMIT, sort: 'last_activity', dir: 'desc' });

  if (summary.error) {
    return <ErrorState error={summary.error} onRetry={() => summary.refetch()} />;
  }

  return (
    <>
      <PageHeader
        title="InfoGatherer"
        subtitle={
          summary.data
            ? `${summary.data.total_conversations} conversations · ${summary.data.denominator} runs measured`
            : 'Loading…'
        }
      >
        <button
          type="button"
          className="btn"
          onClick={() => onNavigate('/infogatherer/statistics')}
        >
          Statistics →
        </button>
      </PageHeader>

      <StatCards data={summary.data} isLoading={summary.isLoading} />

      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[13px] font-medium text-ink">Recent conversations</h2>
        <button
          type="button"
          className="btn"
          onClick={() => onNavigate('/infogatherer/conversations')}
        >
          View all →
        </button>
      </div>

      <div className="mb-3">
        <StatusLegend counts={summary.data?.counts} />
      </div>

      <ConversationTable
        rows={recent.data?.rows ?? []}
        total={recent.data?.total ?? 0}
        limit={RECENT_LIMIT}
        offset={0}
        isLoading={recent.isLoading}
        activeCwid={activeCwid}
        onOpenLogs={onOpenLogs}
        onOpenChat={onOpenChat}
        emptyHint="Conversations appear here once InfoGatherer processes an inbound message."
      />
    </>
  );
}

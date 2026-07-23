/** Statistics page (DASHBOARD_SPEC.md §8.3). */
import { useBreakdowns, useConversations, useStatsSummary, useTriggers } from '../api/client';
import ConversationTable from '../components/ConversationTable';
import RankedPie from '../components/RankedPie';
import { StatCards } from '../components/StatCard';
import { StatusLegend } from '../components/StatusChip';
import TriggerTable from '../components/TriggerTable';
import { ErrorState, PageHeader } from '../components/States';

interface Props {
  onOpenLogs: (cwid: number, trigger: HTMLElement) => void;
  onOpenChat: (cwid: number, trigger: HTMLElement) => void;
  activeCwid: number | null;
  onNavigate: (path: string) => void;
}

const LIST_LIMIT = 50;

export default function Statistics({
  onOpenLogs,
  onOpenChat,
  activeCwid,
  onNavigate,
}: Props) {
  const summary = useStatsSummary();
  const breakdowns = useBreakdowns();
  const triggers = useTriggers(20);

  // Both pre-filtered and not user-refilterable, per the spec.
  const humanNeeded = useConversations({ status: ['human_needed'], limit: LIST_LIMIT });
  const failed = useConversations({ status: ['failed'], limit: LIST_LIMIT });

  if (summary.error) {
    return <ErrorState error={summary.error} onRetry={() => summary.refetch()} />;
  }

  return (
    <>
      <PageHeader
        title="Statistics"
        subtitle={
          summary.data
            ? `${summary.data.denominator} runs measured · ${summary.data.total_conversations} conversations total`
            : 'Loading…'
        }
      />

      <StatCards data={summary.data} isLoading={summary.isLoading} />

      <div className="mb-4 grid gap-3 lg:grid-cols-3">
        <RankedPie
          title="Failures by flow state"
          data={breakdowns.data?.failures_by_flow_state}
          isLoading={breakdowns.isLoading}
          emptyTitle="No failures in this period"
          onSliceClick={(slice) => {
            if (slice.key === '__other__') return;
            onNavigate(`/infogatherer/conversations?status=failed&flow_state=${slice.key}`);
          }}
        />
        <RankedPie
          title="Failures by error message"
          data={breakdowns.data?.failures_by_signature}
          isLoading={breakdowns.isLoading}
          emptyTitle="No failures in this period"
          onSliceClick={() => onNavigate('/infogatherer/conversations?status=failed')}
        />
        <RankedPie
          title="Human needed by flow state"
          data={breakdowns.data?.human_needed_by_flow_state}
          isLoading={breakdowns.isLoading}
          emptyTitle="No escalations in this period"
          onSliceClick={(slice) => {
            if (slice.key === '__other__') return;
            onNavigate(`/infogatherer/conversations?status=human_needed`);
          }}
        />
      </div>

      <div className="mb-4">
        <TriggerTable
          data={triggers.data}
          isLoading={triggers.isLoading}
          onOpenConversation={(cwid) =>
            onNavigate(`/infogatherer/conversations?panel=chat&cwid=${cwid}`)
          }
        />
      </div>

      <div className="mb-3">
        <StatusLegend />
      </div>

      <section className="mb-4">
        <h2 className="mb-2 text-[13px] font-medium text-ink">
          Human needed cases
          {humanNeeded.data && (
            <span className="tabular ml-2 text-[11px] text-ink3">{humanNeeded.data.total}</span>
          )}
        </h2>
        <ConversationTable
          rows={humanNeeded.data?.rows ?? []}
          total={humanNeeded.data?.total ?? 0}
          limit={LIST_LIMIT}
          offset={0}
          isLoading={humanNeeded.isLoading}
          activeCwid={activeCwid}
          onOpenLogs={onOpenLogs}
          onOpenChat={onOpenChat}
          emptyTitle="No conversations were escalated to a human"
          emptyHint="InfoGatherer escalates when it cannot resolve a slot or a downstream call fails."
        />
      </section>

      <section>
        <h2 className="mb-2 text-[13px] font-medium text-ink">
          Failed cases
          {failed.data && (
            <span className="tabular ml-2 text-[11px] text-ink3">{failed.data.total}</span>
          )}
        </h2>
        <ConversationTable
          rows={failed.data?.rows ?? []}
          total={failed.data?.total ?? 0}
          limit={LIST_LIMIT}
          offset={0}
          isLoading={failed.isLoading}
          activeCwid={activeCwid}
          onOpenLogs={onOpenLogs}
          onOpenChat={onOpenChat}
          emptyTitle="No failed conversations"
          emptyHint="A conversation fails on an error/fatal log, a backfill failure, or by stalling mid-flow past the staleness window."
        />
      </section>
    </>
  );
}

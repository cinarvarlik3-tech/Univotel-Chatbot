/**
 * KPI row + the class-mix bar (DASHBOARD_SPEC.md §8.3).
 *
 * The four cards do not sum to 100 — in-progress and not_run exist. Rather than
 * leave that as a silent gap, the bar below shows the full mix and captions the
 * excluded count.
 */
import type { Status, StatsSummary } from '../api/types';
import { STATUS_STYLES, statusTextColor } from '../lib/colors';
import { EM_DASH, formatPercent } from '../lib/format';
import { SkeletonBlock } from './States';

export function StatCard({
  label,
  status,
  percent,
  count,
  denominator,
  subline,
}: {
  label: string;
  status: Status;
  percent: number | null;
  count: number;
  denominator: number;
  subline?: string;
}) {
  const color = statusTextColor(status);
  const style = STATUS_STYLES[status];

  return (
    <div className="card relative overflow-hidden p-4">
      <span
        aria-hidden
        className="absolute inset-x-0 top-0 h-0.5"
        style={{ backgroundColor: color }}
      />
      <div className="flex items-center gap-1.5">
        <span aria-hidden style={{ color }}>
          {style.icon}
        </span>
        <h3 className="text-[12px] font-medium text-ink2">{label}</h3>
      </div>
      <p
        className="tabular mt-2 font-semibold leading-none"
        style={{ color, fontSize: 48 }}
        title={percent === null ? 'No runs to divide by' : undefined}
      >
        {formatPercent(percent)}
      </p>
      <p className="tabular mt-2 text-[11px] text-ink3">
        {count} of {denominator} {denominator === 1 ? 'run' : 'runs'}
      </p>
      {subline && <p className="mt-0.5 text-[11px] text-ink3">{subline}</p>}
    </div>
  );
}

export function StatCards({ data, isLoading }: { data?: StatsSummary; isLoading: boolean }) {
  if (isLoading || !data) {
    return (
      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <SkeletonBlock key={index} height={150} />
        ))}
      </div>
    );
  }

  const { counts, percentages, denominator } = data;

  return (
    <>
      <div className="mb-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Failed conversations"
          status="failed"
          percent={percentages.failed}
          count={counts.failed}
          denominator={denominator}
          subline={`stale after ${data.stale_hours}h counts as failed`}
        />
        <StatCard
          label="Human needed"
          status="human_needed"
          percent={percentages.human_needed}
          count={counts.human_needed}
          denominator={denominator}
        />
        <StatCard
          label="Successfully completed"
          status="success"
          percent={percentages.success}
          count={counts.success}
          denominator={denominator}
        />
        <StatCard
          label="Successful until interruption"
          status="human_interruption"
          percent={percentages.clean_interruption}
          count={data.clean_interruption_count}
          denominator={denominator}
          subline={`${data.clean_interruption_count} clean · ${data.dirty_interruption_count} after an error`}
        />
      </div>

      <ClassMixBar data={data} />
    </>
  );
}

function ClassMixBar({ data }: { data: StatsSummary }) {
  const order: Status[] = [
    'success',
    'human_interruption',
    'human_needed',
    'failed',
    'in_progress',
    'not_run',
  ];
  const total = data.total_conversations;
  if (total === 0) return null;

  return (
    <div className="card mb-4 p-3">
      <div
        className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full"
        role="img"
        aria-label={order
          .map((status) => `${STATUS_STYLES[status].label}: ${data.counts[status]}`)
          .join(', ')}
      >
        {order.map((status) => {
          const count = data.counts[status] ?? 0;
          if (count === 0) return null;
          return (
            <span
              key={status}
              style={{
                width: `${(count / total) * 100}%`,
                backgroundColor: statusTextColor(status),
              }}
              title={`${STATUS_STYLES[status].label}: ${count}`}
            />
          );
        })}
      </div>
      <p className="tabular mt-2 text-[11px] text-ink3">
        {data.denominator} {data.denominator === 1 ? 'run' : 'runs'}
        {data.counts.not_run > 0 && (
          <>
            {' · '}
            <span title="Bot declined a pre-existing thread. Excluded from the percentages above.">
              {data.counts.not_run} not run (excluded)
            </span>
          </>
        )}
        {data.counts.in_progress > 0 && ` · ${data.counts.in_progress} in progress`}
        {data.denominator === 0 && ` · ${EM_DASH} no runs to measure`}
      </p>
    </div>
  );
}

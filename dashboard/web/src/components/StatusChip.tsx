/**
 * Status chip and legend (DASHBOARD_SPEC.md §6.2).
 *
 * The chip always pairs icon + text with the colour. Without it the row colours
 * are undocumented, and colour alone fails for CVD readers and greyscale print.
 */
import { STATUS_STYLES, statusTextColor } from '../lib/colors';
import type { Status } from '../api/types';

/**
 * A log row and a conversation share colours but not vocabulary: a divergence
 * log with is_success=true is a "Success", not a "Completed" conversation.
 */
const LOG_LABELS: Record<Status, string> = {
  success: 'Success',
  failed: 'Error',
  in_progress: 'Info',
  human_needed: 'Escalated',
  human_interruption: 'Takeover',
  not_run: 'Not run',
};

export function StatusChip({
  status,
  compact = false,
  variant = 'conversation',
}: {
  status: Status;
  compact?: boolean;
  variant?: 'conversation' | 'log';
}) {
  const style = STATUS_STYLES[status];
  const color = statusTextColor(status);
  const label = variant === 'log' ? LOG_LABELS[status] : style.label;
  return (
    <span
      className="chip"
      style={{ color, borderColor: color, backgroundColor: style.tint }}
      title={style.description}
    >
      <span aria-hidden>{style.icon}</span>
      {!compact && label}
      {compact && <span className="sr-only">{label}</span>}
    </span>
  );
}

export function StatusLegend({
  counts,
  variant = 'conversation',
}: {
  counts?: Record<string, number>;
  variant?: 'conversation' | 'log';
}) {
  return (
    <ul className="flex flex-wrap items-center gap-x-3 gap-y-1.5" aria-label="Status legend">
      {(Object.keys(STATUS_STYLES) as Status[])
        // A log row can never be 'not_run' — that is a conversation-level class.
        .filter((status) => variant !== 'log' || status !== 'not_run')
        .map((status) => {
        const style = STATUS_STYLES[status];
        const color = statusTextColor(status);
        return (
          <li key={status} className="flex items-center gap-1.5" title={style.description}>
            <span
              aria-hidden
              className="h-2.5 w-0.5 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span aria-hidden style={{ color }} className="text-[11px]">
              {style.icon}
            </span>
            <span className="text-[11px] text-ink2">
              {variant === 'log' ? LOG_LABELS[status] : style.label}
            </span>
            {counts && (
              <span className="tabular text-[11px] text-ink3">{counts[status] ?? 0}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Marks a value the dashboard inferred rather than read. An inferred reason must
 * never be presented as though it were logged (§4.4).
 */
export function DerivedChip({ label = 'derived', title }: { label?: string; title?: string }) {
  return (
    <span
      className="chip border-dashed border-ink3 text-ink3"
      title={title ?? 'Reconstructed by the dashboard, not read from a log row.'}
    >
      {label}
    </span>
  );
}

/** Display formatting. Nulls always render as an em-dash, never as a guess. */

export const EM_DASH = '—';

/** The business runs on Istanbul time; UTC is available in the title attribute. */
const TZ = 'Europe/Istanbul';

const dateTimeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: TZ,
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const timeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: TZ,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return EM_DASH;
  return dateTimeFormat.format(date);
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return EM_DASH;
  return timeFormat.format(date);
}

export function formatUtcTitle(iso: string | null | undefined): string {
  return iso ? `${iso} (UTC)` : '';
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return EM_DASH;
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? EM_DASH : `${value.toFixed(1)}%`;
}

export function truncate(text: string | null | undefined, max: number): string {
  if (!text) return EM_DASH;
  const collapsed = text.replace(/\s+/g, ' ').trim();
  return collapsed.length <= max ? collapsed : `${collapsed.slice(0, max - 1)}…`;
}

export function formatStateTransition(
  from: string | null,
  to: string | null,
): string {
  if (!from && !to) return EM_DASH;
  return `${from ?? '?'} → ${to ?? '?'}`;
}

/** Turkish text is common here; dir="auto" keeps punctuation from flipping. */
export const TEXT_DIR = 'auto' as const;

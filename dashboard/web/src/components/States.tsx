/**
 * Loading, empty, and error states (DASHBOARD_SPEC.md §9).
 *
 * Skeletons match the final geometry so tables do not reflow when data lands.
 * Empty states distinguish "nothing here yet" from "nothing matches your
 * filters" — the second is actionable, the first is not.
 */
import type { ReactNode } from 'react';
import { ApiError } from '../api/client';

export function SkeletonRows({ rows = 8, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <tr key={rowIndex} aria-hidden>
          {Array.from({ length: cols }).map((__, colIndex) => (
            <td key={colIndex} className="td">
              <div
                className="skeleton h-4"
                style={{ width: `${45 + ((rowIndex * 7 + colIndex * 13) % 45)}%` }}
              />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

export function SkeletonBlock({ height = 120 }: { height?: number }) {
  return <div className="skeleton w-full" style={{ height }} aria-hidden />;
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <p className="text-ink2">{title}</p>
      {hint && <p className="max-w-md text-[12px] text-ink3">{hint}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof ApiError ? error : null;

  if (apiError?.isNotConfigured) {
    return (
      <div className="card m-4 p-6">
        <h2 className="mb-2 font-medium text-status-failed">Dashboard not configured</h2>
        <p className="mb-3 text-ink2">
          The server is refusing to serve the dashboard because no credentials are set.
        </p>
        <p className="text-[12px] text-ink3">
          Set <code className="rounded bg-surface2 px-1.5 py-0.5">DASHBOARD_USER</code> and{' '}
          <code className="rounded bg-surface2 px-1.5 py-0.5">DASHBOARD_PASSWORD</code> in the
          environment, then restart. This fails closed on purpose — lead phone numbers and
          chat transcripts are behind this login.
        </p>
      </div>
    );
  }

  if (apiError?.isUnauthorized) {
    return (
      <div className="card m-4 p-6">
        <h2 className="mb-2 font-medium text-status-failed">Session expired</h2>
        <p className="mb-3 text-ink2">Reload the page to sign in again.</p>
        <button type="button" className="btn" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }

  return (
    <div className="card m-4 p-6">
      <h2 className="mb-2 font-medium text-status-failed">Could not load this view</h2>
      <p className="mb-3 text-[12px] text-ink2">
        {apiError ? `${apiError.status}: ${apiError.message}` : String(error)}
      </p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <div className="mt-0.5 text-[12px] text-ink3">{subtitle}</div>}
      </div>
      {children && <div className="flex items-center gap-2">{children}</div>}
    </div>
  );
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  const start = offset + 1;
  const end = Math.min(offset + limit, total);

  return (
    <div className="flex items-center justify-between border-t border-border px-3 py-2">
      <span className="tabular text-[11px] text-ink3">
        {start}–{end} of {total}
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="btn"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          ← Prev
        </button>
        <span className="tabular text-[11px] text-ink3">
          {page} / {pages}
        </span>
        <button
          type="button"
          className="btn"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next →
        </button>
      </div>
    </div>
  );
}

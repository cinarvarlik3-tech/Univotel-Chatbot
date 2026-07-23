/**
 * Top human-needed message triggers + the Full Message modal
 * (DASHBOARD_SPEC.md §8.3, §5.10).
 */
import { useEffect, useRef, useState } from 'react';
import type { TriggerList, TriggerRow } from '../api/types';
import { formatDateTime, truncate } from '../lib/format';
import { EmptyState, SkeletonRows } from './States';

function FullMessageModal({
  row,
  onClose,
  onOpenConversation,
}: {
  row: TriggerRow;
  onClose: () => void;
  onOpenConversation: (cwid: number) => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<Element | null>(null);

  useEffect(() => {
    previouslyFocused.current = document.activeElement;
    dialogRef.current?.focus();
    // Restore focus to whatever opened the modal, or keyboard users are dumped
    // at the top of the document on close.
    return () => (previouslyFocused.current as HTMLElement | null)?.focus?.();
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      // Trap focus inside the dialog.
      const focusables = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusables?.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="full-message-title"
        className="card max-h-[80vh] w-full max-w-2xl overflow-y-auto outline-none"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <h2 id="full-message-title" className="font-medium text-ink">
              Full message
            </h2>
            <p className="tabular mt-0.5 text-[11px] text-ink3">
              Triggered {row.count} {row.count === 1 ? 'escalation' : 'escalations'}
            </p>
          </div>
          <button type="button" className="btn-icon" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="px-4 py-3">
          <p
            className="whitespace-pre-wrap break-words rounded bg-page p-3 text-[13px] text-ink"
            dir="auto"
          >
            {row.display_text}
          </p>
        </div>

        <div className="border-t border-border px-4 py-3">
          <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink3">
            Conversations
          </h3>
          <ul className="space-y-1">
            {row.conversations.map((conversation) => (
              <li key={`${conversation.chatwoot_conversation_id}-${conversation.sent_at}`}>
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-3 rounded px-2 py-1.5 text-left hover:bg-surface2"
                  onClick={() => {
                    onOpenConversation(conversation.chatwoot_conversation_id);
                    onClose();
                  }}
                >
                  <span className="font-mono text-[12px] text-status-interrupt">
                    #{conversation.chatwoot_conversation_id}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[12px] text-ink2">
                    {conversation.lead_name}
                  </span>
                  <span className="tabular shrink-0 text-[11px] text-ink3">
                    {formatDateTime(conversation.sent_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export default function TriggerTable({
  data,
  isLoading,
  onOpenConversation,
}: {
  data: TriggerList | undefined;
  isLoading: boolean;
  onOpenConversation: (cwid: number) => void;
}) {
  const [selected, setSelected] = useState<TriggerRow | null>(null);
  const missing = data ? data.total_human_needed - data.with_trigger : 0;

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2.5">
        <h3 className="text-[12px] font-medium text-ink2">
          Top message triggers of human needed
        </h3>
        {data && (
          <span className="tabular text-[11px] text-ink3">
            {data.total_human_needed} escalations
          </span>
        )}
      </div>

      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th scope="col" className="th w-10">#</th>
            <th scope="col" className="th">Message</th>
            <th scope="col" className="th w-20 text-right">Count</th>
            <th scope="col" className="th w-32" />
          </tr>
        </thead>
        <tbody>
          {isLoading && <SkeletonRows rows={5} cols={4} />}
          {!isLoading &&
            data?.rows.map((row, index) => (
              <tr key={row.normalized} className="hover:bg-surface2/60">
                <td className="td tabular text-[12px] text-ink3">{index + 1}</td>
                <td className="td max-w-0">
                  <span className="block truncate text-[12px] text-ink2" dir="auto" title={row.display_text}>
                    {truncate(row.display_text, 110)}
                  </span>
                </td>
                <td className="td tabular text-right text-[12px] text-ink">{row.count}</td>
                <td className="td text-right">
                  <button type="button" className="btn" onClick={() => setSelected(row)}>
                    Full Message
                  </button>
                </td>
              </tr>
            ))}
        </tbody>
      </table>

      {!isLoading && data?.rows.length === 0 && (
        <EmptyState
          title="No human-needed escalations yet"
          hint="Once InfoGatherer escalates, the message that preceded each escalation is grouped here."
        />
      )}

      {missing > 0 && (
        <p className="border-t border-border px-3 py-2 text-[11px] text-ink3">
          {missing} {missing === 1 ? 'escalation had' : 'escalations had'} no preceding inbound
          message and {missing === 1 ? 'is' : 'are'} not represented above.
        </p>
      )}

      {selected && (
        <FullMessageModal
          row={selected}
          onClose={() => setSelected(null)}
          onOpenConversation={onOpenConversation}
        />
      )}
    </div>
  );
}

/**
 * Chatwoot-style transcript with inline flow markers (DASHBOARD_SPEC.md §6.3, §6.4).
 *
 * Black background, white text, bubbles coloured by sender type. Markers are
 * anchored server-side by `after_message_id` — the server owns that placement
 * because it has both clocks (messages.sent_at vs created_at) and only the
 * persist clock is comparable with chatbot_logs.created_at.
 */
import { useEffect, useMemo, useRef } from 'react';
import type { ConversationMessages, FlowMarker, MessageRow } from '../api/types';
import { BUBBLE_STYLES, MARKER_STATUS, STATUS_STYLES } from '../lib/colors';
import { formatTime, formatUtcTitle } from '../lib/format';
import { EmptyState, ErrorState, SkeletonBlock } from './States';

function Bubble({
  message,
  showSender,
  onOpenDetail,
}: {
  message: MessageRow;
  showSender: boolean;
  onOpenDetail: (messageId: string, trigger: HTMLElement) => void;
}) {
  const style = BUBBLE_STYLES[message.bubble];
  const isRight = style.align === 'right';

  return (
    <li className={['flex flex-col', isRight ? 'items-end' : 'items-start'].join(' ')}>
      {showSender && (
        <span className="mb-0.5 px-1 text-[11px] text-ink3">
          {message.sender_name || style.name}
          {message.bubble === 'human' && message.sender_type === 'automation' && (
            <span className="ml-1.5 rounded border border-border px-1 py-px text-[10px]">
              Automation
            </span>
          )}
          {message.bubble === 'private' && (
            <span className="ml-1.5 rounded border border-bubble-privateRail px-1 py-px text-[10px] text-bubble-privateRail">
              Private note
            </span>
          )}
        </span>
      )}
      <button
        type="button"
        onClick={(event) => onOpenDetail(message.id, event.currentTarget)}
        className={[
          'max-w-[78%] px-3 py-2 text-left transition-opacity hover:opacity-90',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-status-interrupt',
          // Corner nearest the sender squared, matching Chatwoot.
          isRight ? 'rounded-xl rounded-br-[4px]' : 'rounded-xl rounded-bl-[4px]',
        ].join(' ')}
        style={{
          backgroundColor: style.bg,
          color: style.text,
          borderLeft:
            message.bubble === 'private' ? `3px solid ${BUBBLE_STYLES.private.bg}` : undefined,
          boxShadow:
            message.bubble === 'private' ? 'inset 3px 0 0 #EAB308' : undefined,
        }}
        aria-label={`Message from ${message.sender_name || style.name} at ${formatTime(message.sent_at)}`}
      >
        <span className="whitespace-pre-wrap break-words text-[13px]" dir="auto">
          {message.content || <span className="italic opacity-60">(no content)</span>}
        </span>
        <span
          className="mt-1 block text-right text-[10px] opacity-70"
          title={formatUtcTitle(message.sent_at)}
        >
          {formatTime(message.sent_at)}
        </span>
      </button>
    </li>
  );
}

function Marker({ marker }: { marker: FlowMarker }) {
  const status = MARKER_STATUS[marker.kind];
  const style = STATUS_STYLES[status];
  return (
    <li className="my-3 flex items-center gap-2" role="separator" aria-label={marker.label}>
      <span className="h-px flex-1" style={{ backgroundColor: style.color }} />
      <span
        className="flex max-w-[86%] shrink-0 items-baseline gap-1.5 rounded-full border px-3 py-1 text-[11px]"
        style={{ borderColor: style.color, color: style.color, backgroundColor: style.tint }}
      >
        <span aria-hidden>{style.icon}</span>
        <span className="whitespace-nowrap font-medium">{marker.label}</span>
        {marker.detail && (
          <span className="text-ink2" dir="auto">
            — {marker.detail}
          </span>
        )}
      </span>
      <span className="h-px flex-1" style={{ backgroundColor: style.color }} />
    </li>
  );
}

/**
 * Nearest scrollable ancestor, or null.
 *
 * scrollIntoView() would be the obvious call here, but it scrolls *every*
 * scrollable ancestor including the document — so a long transcript drags the
 * whole app off-screen. Scrolling the one container that owns the overflow is
 * the only thing we actually want.
 */
function scrollParent(node: HTMLElement | null): HTMLElement | null {
  let current = node?.parentElement ?? null;
  while (current) {
    const { overflowY } = window.getComputedStyle(current);
    if (overflowY === 'auto' || overflowY === 'scroll') return current;
    current = current.parentElement;
  }
  return null;
}

export default function Transcript({
  data,
  isLoading,
  error,
  hidePrivate,
  onOpenMessage,
}: {
  data: ConversationMessages | undefined;
  isLoading: boolean;
  error: unknown;
  hidePrivate: boolean;
  onOpenMessage: (messageId: string, trigger: HTMLElement) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);

  const messages = useMemo(
    () => (data ? data.messages.filter((m) => !hidePrivate || !m.is_private) : []),
    [data, hidePrivate],
  );

  // Markers grouped by the message they render beneath. Anything anchored to a
  // hidden or missing message falls back to the top so it is never dropped.
  const { markersByMessage, leadingMarkers } = useMemo(() => {
    const byMessage = new Map<string, FlowMarker[]>();
    const leading: FlowMarker[] = [];
    const visibleIds = new Set(messages.map((m) => m.id));
    for (const marker of data?.markers ?? []) {
      if (marker.after_message_id && visibleIds.has(marker.after_message_id)) {
        const list = byMessage.get(marker.after_message_id) ?? [];
        list.push(marker);
        byMessage.set(marker.after_message_id, list);
      } else {
        leading.push(marker);
      }
    }
    return { markersByMessage: byMessage, leadingMarkers: leading };
  }, [data, messages]);

  // Open at the newest message, like Chatwoot — but scroll only the panel.
  // Deferred by two frames: on the first render after data arrives the container
  // has not been laid out yet, so scrollHeight is still the pre-paint value and
  // setting scrollTop does nothing.
  useEffect(() => {
    if (!messages.length) return;
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => {
        const container = scrollParent(rootRef.current);
        if (container) container.scrollTop = container.scrollHeight;
      });
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [data?.conversation.chatwoot_conversation_id, messages.length]);

  if (error) return <ErrorState error={error} />;
  if (isLoading || !data) {
    return (
      <div className="space-y-3 bg-transcript p-3">
        <SkeletonBlock height={48} />
        <SkeletonBlock height={64} />
        <SkeletonBlock height={40} />
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="bg-transcript">
        <EmptyState
          title="No messages"
          hint={
            hidePrivate
              ? 'All messages in this conversation are private notes, which are hidden.'
              : 'This conversation has no persisted messages.'
          }
        />
      </div>
    );
  }

  return (
    <div ref={rootRef} className="min-h-full bg-transcript px-3 py-3">
      <ul className="space-y-2">
        {leadingMarkers.map((marker, index) => (
          <Marker key={`leading-${index}`} marker={marker} />
        ))}

        {messages.map((message, index) => {
          const previous = messages[index - 1];
          // Sender name only on the first bubble of a run, as Chatwoot does.
          const showSender =
            !previous ||
            previous.bubble !== message.bubble ||
            previous.sender_name !== message.sender_name;
          return (
            <li key={message.id} className="contents">
              <ul className="contents">
                <Bubble
                  message={message}
                  showSender={showSender}
                  onOpenDetail={onOpenMessage}
                />
                {(markersByMessage.get(message.id) ?? []).map((marker, markerIndex) => (
                  <Marker key={`${message.id}-${markerIndex}`} marker={marker} />
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function MessageDetail({
  message,
  isLoading,
}: {
  message: MessageRow | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <SkeletonBlock height={200} />;
  if (!message) {
    return <EmptyState title="Message not found" hint="It may have been filtered out." />;
  }

  const rows: [string, React.ReactNode][] = [
    ['Bubble', message.bubble],
    ['Direction', message.direction],
    ['Sender type', message.sender_type],
    ['Sender name', message.sender_name],
    ['Sender id', message.sender_id],
    ['Chatwoot id', message.chatwoot_message_id],
    ['Private', message.is_private ? 'true' : 'false'],
    ['Sent at', <span title={formatUtcTitle(message.sent_at)}>{message.sent_at}</span>],
    ['Persisted at', <span title={formatUtcTitle(message.created_at)}>{message.created_at}</span>],
  ];

  return (
    <div>
      <section className="border-b border-border px-3 py-3">
        <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink3">
          Content
        </h3>
        <p className="whitespace-pre-wrap break-words text-[13px] text-ink" dir="auto">
          {message.content || <span className="italic text-ink3">(no content)</span>}
        </p>
      </section>
      <section className="px-3 py-3">
        <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink3">
          Fields
        </h3>
        <dl>
          {rows.map(([label, value]) => (
            <div key={label} className="flex gap-3 py-1">
              <dt className="w-28 shrink-0 text-[11px] uppercase tracking-wide text-ink3">
                {label}
              </dt>
              <dd className="min-w-0 flex-1 break-all font-mono text-[12px] text-ink2">
                {value ?? '—'}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-[11px] text-ink3">
          Sent at is Chatwoot's send clock; persisted at is when this pipeline stored the
          row. Markers are positioned on the persist clock so they line up with log rows.
        </p>
      </section>
    </div>
  );
}

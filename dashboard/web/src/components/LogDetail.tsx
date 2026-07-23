/**
 * Log detail panel (DASHBOARD_SPEC.md §8.2, §5.5).
 *
 * The Payload section is the honest part: chatbot_logs has no payload columns,
 * so instead of rendering an empty JSON block that looks like a bug, the panel
 * states the absence and points at the spec section that would fix it.
 */
import { useState } from 'react';
import type { LogDetail as LogDetailType, MessageRow } from '../api/types';
import { STATUS_STYLES } from '../lib/colors';
import { EM_DASH, formatDateTime, formatUtcTitle } from '../lib/format';
import { DerivedChip, StatusChip } from './StatusChip';
import { ErrorState, SkeletonBlock } from './States';

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex gap-3 py-1">
      <dt className="w-32 shrink-0 text-[11px] uppercase tracking-wide text-ink3">{label}</dt>
      <dd className={['min-w-0 flex-1 text-[12px] text-ink2', mono ? 'font-mono' : ''].join(' ')}>
        {value ?? EM_DASH}
      </dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border px-3 py-3 last:border-b-0">
      <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink3">{title}</h3>
      {children}
    </section>
  );
}

function ContextMessage({ message }: { message: MessageRow }) {
  const style = STATUS_STYLES.in_progress;
  return (
    <li className="rounded border border-border/60 px-2 py-1.5" style={{ borderLeftColor: style.color }}>
      <div className="flex items-center gap-1.5 text-[11px] text-ink3">
        <span className="font-mono">{message.bubble}</span>
        <span>·</span>
        <span>{message.sender_name ?? EM_DASH}</span>
        <span>·</span>
        <span title={formatUtcTitle(message.sent_at)}>{formatDateTime(message.sent_at)}</span>
      </div>
      <p className="mt-0.5 text-[12px] text-ink2" dir="auto">
        {message.content ?? <span className="italic text-ink3">(no content)</span>}
      </p>
    </li>
  );
}

export default function LogDetail({
  data,
  isLoading,
  error,
}: {
  data: LogDetailType | undefined;
  isLoading: boolean;
  error: unknown;
}) {
  const [rawOpen, setRawOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (error) return <ErrorState error={error} />;
  if (isLoading || !data) {
    return (
      <div className="space-y-3 p-3">
        <SkeletonBlock height={140} />
        <SkeletonBlock height={90} />
      </div>
    );
  }

  const { log, conversation, context, payload, raw } = data;

  async function copyRaw() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(raw, null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can be blocked by permissions; the JSON is selectable anyway.
    }
  }

  return (
    <div>
      <Section title="Summary">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <StatusChip status={log.log_status} />
          {log.derived && <DerivedChip />}
          {log.signature_label && (
            <span className="chip border-border text-ink2">{log.signature_label}</span>
          )}
        </div>
        <dl>
          <Field
            label="Time"
            value={
              <span title={formatUtcTitle(log.created_at)}>{formatDateTime(log.created_at)}</span>
            }
          />
          <Field label="Operation" value={log.operation_label} mono />
          <Field label="Level" value={log.log_level} mono />
          <Field
            label="Success"
            value={log.is_success === null ? EM_DASH : log.is_success ? 'true' : 'false'}
            mono
          />
          <Field label="Status code" value={log.status_code} mono />
          <Field label="Internal class" value={log.internal_class} mono />
          <Field
            label="Transition"
            value={
              log.from_state || log.to_state ? (
                `${log.from_state ?? '?'} → ${log.to_state ?? '?'}`
              ) : (
                <span className="text-ink3">
                  {EM_DASH}{' '}
                  <span className="text-[11px]">
                    (from_state/to_state are never populated — spec §12.1)
                  </span>
                </span>
              )
            }
            mono
          />
          <Field label="Network" value={log.network_status} mono />
          <Field label="Database" value={log.database_status} mono />
        </dl>
      </Section>

      {log.explanation && (
        <Section title="Explanation">
          <p className="whitespace-pre-wrap text-[12px] text-ink" dir="auto">
            {log.explanation}
          </p>
        </Section>
      )}

      <Section title="Payload">
        {payload.available ? (
          <div className="space-y-2">
            <dl>
              <Field label="Source" value={payload.source} mono />
              <Field label="Target" value={payload.target} mono />
            </dl>
            <pre className="max-h-64 overflow-auto rounded bg-page p-2 font-mono text-[11px] text-ink2">
              {JSON.stringify({ input: payload.input, output: payload.output }, null, 2)}
            </pre>
          </div>
        ) : (
          <p className="rounded border border-dashed border-border px-2.5 py-2 text-[12px] text-ink3">
            {payload.note}
          </p>
        )}
      </Section>

      {conversation && (
        <Section title="Conversation">
          <dl>
            <Field label="Identifier" value={`#${conversation.chatwoot_conversation_id}`} mono />
            <Field label="Lead" value={conversation.lead_name} />
            <Field label="Status" value={<StatusChip status={conversation.status} />} />
            <Field label="Flow state" value={conversation.flow_state} mono />
          </dl>
        </Section>
      )}

      {(context.preceding_messages.length > 0 || context.following_messages.length > 0) && (
        <Section title="Surrounding messages">
          {context.preceding_messages.length > 0 && (
            <>
              <p className="mb-1 text-[11px] text-ink3">Before</p>
              <ul className="mb-3 space-y-1.5">
                {context.preceding_messages.map((message) => (
                  <ContextMessage key={message.id} message={message} />
                ))}
              </ul>
            </>
          )}
          {context.following_messages.length > 0 && (
            <>
              <p className="mb-1 text-[11px] text-ink3">After</p>
              <ul className="space-y-1.5">
                {context.following_messages.map((message) => (
                  <ContextMessage key={message.id} message={message} />
                ))}
              </ul>
            </>
          )}
        </Section>
      )}

      <Section title="Raw">
        <div className="mb-2 flex items-center gap-2">
          <button
            type="button"
            className="btn"
            onClick={() => setRawOpen((open) => !open)}
            aria-expanded={rawOpen}
          >
            {rawOpen ? 'Hide JSON' : 'Show JSON'}
          </button>
          <button type="button" className="btn" onClick={copyRaw}>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        {rawOpen && (
          <pre className="max-h-80 overflow-auto rounded bg-page p-2 font-mono text-[11px] text-ink2">
            {JSON.stringify(raw, null, 2)}
          </pre>
        )}
      </Section>
    </div>
  );
}

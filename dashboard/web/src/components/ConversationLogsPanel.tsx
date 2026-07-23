/**
 * Conversation Logs panel body (DASHBOARD_SPEC.md §8.2 + notes addition).
 *
 * The log timeline with log-level notes interleaved by time, plus a "+ Note"
 * control in the view header. A log note renders as a yellow log entry; adding
 * one puts a dot on the conversation's table row until it is resolved.
 */
import { useMemo, useState } from 'react';
import { useConversationLogs, useConversationNotes, useNoteMutations } from '../api/client';
import type { LogRow, Note } from '../api/types';
import { ErrorState } from './States';
import { LogEntryItem } from './LogTable';
import { NoteComposer, NoteLogEntry } from './Notes';

type TimelineItem =
  | { kind: 'log'; at: string; row: LogRow }
  | { kind: 'note'; at: string; note: Note };

export default function ConversationLogsPanel({
  cwid,
  onOpenDetail,
}: {
  cwid: number;
  onOpenDetail: (logId: string, trigger: HTMLElement) => void;
}) {
  const logsQuery = useConversationLogs(cwid);
  const notesQuery = useConversationNotes(cwid, 'log');
  const { create, setResolved } = useNoteMutations(cwid);
  const [composing, setComposing] = useState(false);

  const items = useMemo<TimelineItem[]>(() => {
    const merged: TimelineItem[] = [
      ...(logsQuery.data?.rows ?? []).map(
        (row): TimelineItem => ({ kind: 'log', at: row.created_at ?? '', row }),
      ),
      ...(notesQuery.data?.rows ?? []).map(
        (note): TimelineItem => ({ kind: 'note', at: note.created_at ?? '', note }),
      ),
    ];
    // Undated rows sort last rather than jumping to the top.
    merged.sort((a, b) => (a.at === '' ? 1 : b.at === '' ? -1 : a.at.localeCompare(b.at)));
    return merged;
  }, [logsQuery.data, notesQuery.data]);

  if (logsQuery.error) return <ErrorState error={logsQuery.error} />;

  const isLoading = logsQuery.isLoading;
  const isEmpty = !isLoading && items.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="sticky top-0 z-10 shrink-0 border-b border-border bg-surface px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wide text-ink3">
            Logs &amp; notes
          </span>
          {!composing && (
            <button type="button" className="btn" onClick={() => setComposing(true)}>
              + Note
            </button>
          )}
        </div>
        {composing && (
          <div className="mt-2">
            <NoteComposer
              multiline={false}
              autoFocus
              placeholder="Add a note to this conversation's log…"
              pending={create.isPending}
              onCancel={() => setComposing(false)}
              onSubmit={async (body) => {
                await create.mutateAsync({ noteType: 'log', body });
                setComposing(false);
              }}
            />
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading && (
          <div className="space-y-2 p-3" aria-hidden>
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="skeleton h-14 w-full" />
            ))}
          </div>
        )}

        {isEmpty && (
          <p className="px-3 py-8 text-center text-[12px] text-ink3">
            No logs or notes yet. InfoGatherer writes a log row on escalations, abstains,
            and divergence turns — a clean run can have none. Use “+ Note” to annotate.
          </p>
        )}

        {!isLoading && items.length > 0 && (
          <ul className="divide-y divide-border/60">
            {items.map((item) =>
              item.kind === 'log' ? (
                <LogEntryItem key={item.row.id} row={item.row} onOpenDetail={onOpenDetail} />
              ) : (
                <NoteLogEntry
                  key={item.note.id}
                  note={item.note}
                  pending={setResolved.isPending}
                  onToggleResolved={(note) =>
                    setResolved.mutate({ noteId: note.id, resolved: !note.resolved })
                  }
                />
              ),
            )}
          </ul>
        )}
      </div>
    </div>
  );
}

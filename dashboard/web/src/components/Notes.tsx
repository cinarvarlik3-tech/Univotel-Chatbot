/**
 * Per-lead note UI (DASHBOARD_SPEC.md — notes addition).
 *
 * Two presentations of the same record:
 *   NoteLogEntry — a log-style row for the Logs panel.
 *   NoteBubble   — a Chatwoot-private-note-style bubble for the transcript.
 * Both are yellow, headed NOTE, with an italic body and a resolve toggle. A
 * resolved note dims and strikes through so it reads as handled without vanishing.
 *
 * NoteComposer is the shared input: single-line for log notes, multiline
 * (Enter to send, Shift+Enter for a newline) for conversation notes.
 */
import { useState } from 'react';
import type { Note } from '../api/types';
import { NOTE_STYLE } from '../lib/colors';
import { formatDateTime, formatUtcTitle } from '../lib/format';

function ResolveButton({
  resolved,
  pending,
  onToggle,
}: {
  resolved: boolean;
  pending: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className="btn shrink-0"
      onClick={onToggle}
      disabled={pending}
      aria-pressed={resolved}
      title={resolved ? 'Mark this note unresolved' : 'Mark this note resolved'}
    >
      {resolved ? 'Unresolve' : 'Resolve'}
    </button>
  );
}

function NoteMeta({ note }: { note: Note }) {
  return (
    <span className="text-[11px]" style={{ color: NOTE_STYLE.heading }}>
      <span className="font-semibold uppercase tracking-wide">Note</span>
      {note.author && <span className="ml-1.5 opacity-80">· {note.author}</span>}
      {note.created_at && (
        <span
          className="ml-1.5 opacity-70"
          title={formatUtcTitle(note.created_at)}
        >
          · {formatDateTime(note.created_at)}
        </span>
      )}
    </span>
  );
}

/** Log-panel presentation: a yellow log-style row. */
export function NoteLogEntry({
  note,
  pending,
  onToggleResolved,
}: {
  note: Note;
  pending: boolean;
  onToggleResolved: (note: Note) => void;
}) {
  return (
    <li
      className="px-3 py-2.5 transition-opacity"
      style={{
        backgroundColor: NOTE_STYLE.tint,
        boxShadow: `inset 3px 0 0 ${NOTE_STYLE.rail}`,
        opacity: note.resolved ? 0.55 : 1,
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <NoteMeta note={note} />
          <p
            className={[
              'mt-1 whitespace-pre-wrap break-words text-[13px] italic',
              note.resolved ? 'line-through' : '',
            ].join(' ')}
            style={{ color: NOTE_STYLE.text }}
            dir="auto"
          >
            {note.body}
          </p>
        </div>
        <ResolveButton
          resolved={note.resolved}
          pending={pending}
          onToggle={() => onToggleResolved(note)}
        />
      </div>
    </li>
  );
}

/** Transcript presentation: a yellow private-note-style bubble, right-aligned. */
export function NoteBubble({
  note,
  pending,
  onToggleResolved,
}: {
  note: Note;
  pending: boolean;
  onToggleResolved: (note: Note) => void;
}) {
  return (
    <li className="flex flex-col items-end transition-opacity" style={{ opacity: note.resolved ? 0.55 : 1 }}>
      <div className="mb-0.5 flex items-center gap-2 px-1">
        <NoteMeta note={note} />
        <ResolveButton
          resolved={note.resolved}
          pending={pending}
          onToggle={() => onToggleResolved(note)}
        />
      </div>
      <div
        className="max-w-[78%] rounded-xl rounded-br-[4px] px-3 py-2"
        style={{
          backgroundColor: NOTE_STYLE.bg,
          borderLeft: `3px solid ${NOTE_STYLE.rail}`,
        }}
      >
        <span
          className={[
            'whitespace-pre-wrap break-words text-[13px] italic',
            note.resolved ? 'line-through' : '',
          ].join(' ')}
          style={{ color: NOTE_STYLE.text }}
          dir="auto"
        >
          {note.body}
        </span>
      </div>
    </li>
  );
}

/**
 * Shared composer. `multiline` picks a textarea (conversation notes, chat-style)
 * over an input (log notes). Empty/whitespace submissions are blocked; the field
 * clears on a successful send.
 */
export function NoteComposer({
  multiline,
  placeholder,
  pending,
  onSubmit,
  onCancel,
  autoFocus,
}: {
  multiline: boolean;
  placeholder: string;
  pending: boolean;
  onSubmit: (body: string) => Promise<unknown>;
  onCancel?: () => void;
  autoFocus?: boolean;
}) {
  const [value, setValue] = useState('');
  const canSend = value.trim().length > 0 && !pending;

  async function submit() {
    if (!canSend) return;
    try {
      await onSubmit(value.trim());
      setValue('');
    } catch {
      // The mutation surfaces its own error; keep the text so it is not lost.
    }
  }

  return (
    <div className="flex items-end gap-2">
      {multiline ? (
        <textarea
          className="input min-h-[36px] flex-1 resize-none py-1.5"
          rows={1}
          placeholder={placeholder}
          value={value}
          autoFocus={autoFocus}
          dir="auto"
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
        />
      ) : (
        <input
          type="text"
          className="input flex-1"
          placeholder={placeholder}
          value={value}
          autoFocus={autoFocus}
          dir="auto"
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void submit();
            }
            if (event.key === 'Escape' && onCancel) onCancel();
          }}
        />
      )}
      <button type="button" className="btn shrink-0" disabled={!canSend} onClick={() => void submit()}>
        {pending ? 'Saving…' : 'Send'}
      </button>
      {onCancel && (
        <button type="button" className="btn-icon shrink-0" onClick={onCancel} aria-label="Cancel note">
          ✕
        </button>
      )}
    </div>
  );
}

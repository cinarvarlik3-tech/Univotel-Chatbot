/**
 * Conversation transcript panel body (DASHBOARD_SPEC.md §8.2 + notes addition).
 *
 * The transcript with conversation-level notes interleaved as yellow bubbles, and
 * a chat-style composer pinned to the bottom: type a note, hit send, it is
 * recorded. Adding one puts a dot on the conversation's table row until resolved.
 */
import { useConversationMessages, useConversationNotes, useNoteMutations } from '../api/client';
import Transcript from './Transcript';
import { NoteComposer } from './Notes';

export default function ConversationChat({
  cwid,
  hidePrivate,
  onOpenMessage,
}: {
  cwid: number;
  hidePrivate: boolean;
  onOpenMessage: (messageId: string, trigger: HTMLElement) => void;
}) {
  const messagesQuery = useConversationMessages(cwid);
  const notesQuery = useConversationNotes(cwid, 'conversation');
  const { create, setResolved } = useNoteMutations(cwid);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <Transcript
          data={messagesQuery.data}
          isLoading={messagesQuery.isLoading}
          error={messagesQuery.error}
          hidePrivate={hidePrivate}
          onOpenMessage={onOpenMessage}
          notes={notesQuery.data?.rows ?? []}
          notePending={setResolved.isPending}
          onToggleNoteResolved={(note) =>
            setResolved.mutate({ noteId: note.id, resolved: !note.resolved })
          }
        />
      </div>

      <div className="shrink-0 border-t border-border bg-surface p-2.5">
        <NoteComposer
          multiline
          placeholder="Write a note… (Enter to send, Shift+Enter for a newline)"
          pending={create.isPending}
          onSubmit={(body) => create.mutateAsync({ noteType: 'conversation', body })}
        />
      </div>
    </div>
  );
}

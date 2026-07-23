/**
 * App shell (DASHBOARD_SPEC.md §7.1).
 *
 * Owns the three-column grid and renders the right panel centrally so every page
 * shares one panel implementation and one state machine.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useIsFetching, useQueryClient } from '@tanstack/react-query';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import LeftNav from './components/LeftNav';
import RightPanel from './components/RightPanel';
import LogDetail from './components/LogDetail';
import Transcript, { MessageDetail } from './components/Transcript';
import { LogRowList } from './components/LogTable';
import { ErrorState } from './components/States';
import {
  useConversationLogs,
  useConversationMessages,
  useLogDetail,
} from './api/client';
import { panelTitle, usePanel, type PanelState } from './state/panel';
import Conversations from './pages/Conversations';
import InfoGathererOverview from './pages/InfoGathererOverview';
import Logs from './pages/Logs';
import Statistics from './pages/Statistics';

function usePersistentState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return stored === null ? initial : (JSON.parse(stored) as T);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Private browsing can reject writes; the value still works in-session.
    }
  }, [key, value]);
  return [value, setValue] as const;
}

/** Panel bodies, split out so the shell stays readable. */
function PanelBody({
  panel,
  hidePrivate,
  onOpenLogDetail,
  onOpenMessage,
}: {
  panel: PanelState;
  hidePrivate: boolean;
  onOpenLogDetail: (logId: string, trigger: HTMLElement) => void;
  onOpenMessage: (messageId: string, trigger: HTMLElement) => void;
}) {
  const logsQuery = useConversationLogs(
    panel.kind === 'conversationLogs' ? panel.cwid : null,
  );
  const messagesQuery = useConversationMessages(
    panel.kind === 'conversationChat' || panel.kind === 'messageDetail' ? panel.cwid : null,
  );
  const detailQuery = useLogDetail(panel.kind === 'logDetail' ? panel.logId : null);

  switch (panel.kind) {
    case 'conversationLogs':
      if (logsQuery.error) return <ErrorState error={logsQuery.error} />;
      return (
        <LogRowList
          rows={logsQuery.data?.rows ?? []}
          isLoading={logsQuery.isLoading}
          onOpenDetail={onOpenLogDetail}
        />
      );

    case 'conversationChat':
      return (
        <Transcript
          data={messagesQuery.data}
          isLoading={messagesQuery.isLoading}
          error={messagesQuery.error}
          hidePrivate={hidePrivate}
          onOpenMessage={onOpenMessage}
        />
      );

    case 'logDetail':
      return (
        <LogDetail
          data={detailQuery.data}
          isLoading={detailQuery.isLoading}
          error={detailQuery.error}
        />
      );

    case 'messageDetail':
      return (
        <MessageDetail
          message={messagesQuery.data?.messages.find((m) => m.id === panel.messageId)}
          isLoading={messagesQuery.isLoading}
        />
      );
  }
}

export default function App() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isFetching = useIsFetching() > 0;

  const [navCollapsed, setNavCollapsed] = usePersistentState('dash.nav.collapsed', false);
  const [panelWidth, setPanelWidth] = usePersistentState('dash.panel.width', 480);
  const [panelExpanded, setPanelExpanded] = usePersistentState('dash.panel.expanded', false);
  const [hidePrivate, setHidePrivate] = usePersistentState('dash.chat.hidePrivate', false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const { panel, setPanel, parent, goBack, close } = usePanel();

  // Focus returns to whatever opened the panel — otherwise keyboard users are
  // dropped at the top of the document when the panel closes.
  const triggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isFetching) setLastUpdated(new Date().toISOString());
  }, [isFetching]);

  // Collapse the nav on narrow viewports; this is a desk tool, not a phone app.
  useEffect(() => {
    function onResize() {
      if (window.innerWidth < 900) setNavCollapsed(true);
    }
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [setNavCollapsed]);

  const openPanel = useCallback(
    (next: PanelState, trigger?: HTMLElement) => {
      if (trigger) triggerRef.current = trigger;
      setPanel(next);
    },
    [setPanel],
  );

  const closePanel = useCallback(() => {
    close();
    triggerRef.current?.focus?.();
    triggerRef.current = null;
  }, [close]);

  const handlers = useMemo(
    () => ({
      openLogs: (cwid: number, trigger: HTMLElement) =>
        openPanel({ kind: 'conversationLogs', cwid }, trigger),
      openChat: (cwid: number, trigger: HTMLElement) =>
        openPanel({ kind: 'conversationChat', cwid }, trigger),
      openLogDetailFromConversation: (logId: string, trigger: HTMLElement) =>
        openPanel(
          {
            kind: 'logDetail',
            logId,
            // Carrying cwid is what gives this state a parent, and therefore a
            // back arrow, per §7.3.
            cwid: panel && 'cwid' in panel ? (panel.cwid as number) : null,
          },
          trigger,
        ),
      openLogDetailStandalone: (logId: string, trigger: HTMLElement) =>
        openPanel({ kind: 'logDetail', logId, cwid: null }, trigger),
      openMessage: (messageId: string, trigger: HTMLElement) =>
        openPanel(
          {
            kind: 'messageDetail',
            cwid: panel && 'cwid' in panel ? (panel.cwid as number) : 0,
            messageId,
          },
          trigger,
        ),
    }),
    [openPanel, panel],
  );

  const refresh = useCallback(() => {
    queryClient.invalidateQueries();
  }, [queryClient]);

  const pageProps = {
    onOpenLogs: handlers.openLogs,
    onOpenChat: handlers.openChat,
    activeCwid: panel && 'cwid' in panel ? (panel.cwid as number) : null,
  };

  return (
    <div
      className="grid h-full overflow-hidden"
      style={{
        gridTemplateColumns: `${navCollapsed ? 56 : 248}px minmax(0,1fr) ${
          panel ? 'auto' : '0px'
        }`,
        // minmax(0,1fr) on the row, not just the columns: an implicit `auto` row
        // grows to fit its tallest child, so a long transcript would stretch the
        // grid past the viewport and its own overflow-y-auto would never engage.
        gridTemplateRows: 'minmax(0, 1fr)',
      }}
    >
      <LeftNav
        collapsed={navCollapsed}
        onToggle={() => setNavCollapsed((value) => !value)}
        lastUpdated={lastUpdated}
        isFetching={isFetching}
        onRefresh={refresh}
      />

      <main className="min-h-0 min-w-0 overflow-y-auto p-4">
        <Routes>
          <Route path="/" element={<Navigate to="/infogatherer" replace />} />
          <Route
            path="/infogatherer"
            element={
              <InfoGathererOverview
                {...pageProps}
                onNavigate={(path) => navigate(path)}
              />
            }
          />
          <Route path="/infogatherer/conversations" element={<Conversations {...pageProps} />} />
          <Route
            path="/infogatherer/statistics"
            element={<Statistics {...pageProps} onNavigate={(path) => navigate(path)} />}
          />
          <Route
            path="/infogatherer/logs"
            element={
              <Logs
                onOpenDetail={handlers.openLogDetailStandalone}
                onOpenConversation={handlers.openChat}
                activeLogId={panel?.kind === 'logDetail' ? panel.logId : null}
              />
            }
          />
          <Route
            path="*"
            element={
              <div className="card p-6">
                <h1 className="mb-1 font-medium text-ink">Page not found</h1>
                <p className="text-[12px] text-ink3">
                  No such view. Pick something from the navigation.
                </p>
              </div>
            }
          />
        </Routes>
      </main>

      {/* Unmounted, not hidden, when nothing is being displayed (§7.1). */}
      {panel && (
        <RightPanel
          title={panelTitle(panel)}
          onClose={closePanel}
          onBack={parent ? goBack : null}
          width={panelWidth}
          onResize={setPanelWidth}
          expanded={panelExpanded}
          onToggleExpand={() => setPanelExpanded((value) => !value)}
          headerExtra={
            panel.kind === 'conversationChat' ? (
              <button
                type="button"
                className="btn shrink-0"
                onClick={() => setHidePrivate((value) => !value)}
                aria-pressed={hidePrivate}
                title="Chatwoot shows private notes; hide them here if they get in the way"
              >
                {hidePrivate ? 'Show notes' : 'Hide notes'}
              </button>
            ) : undefined
          }
        >
          <PanelBody
            panel={panel}
            hidePrivate={hidePrivate}
            onOpenLogDetail={handlers.openLogDetailFromConversation}
            onOpenMessage={handlers.openMessage}
          />
        </RightPanel>
      )}
    </div>
  );
}

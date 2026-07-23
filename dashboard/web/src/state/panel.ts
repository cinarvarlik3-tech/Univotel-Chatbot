/**
 * Right-panel state machine (DASHBOARD_SPEC.md §7.3).
 *
 * State lives in the URL so a panel survives a refresh and can be shared. The
 * back arrow renders if and only if the current state has a parent — which is
 * why `parent` is modelled explicitly rather than inferred from the page.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

export type PanelState =
  | { kind: 'conversationLogs'; cwid: number }
  | { kind: 'conversationChat'; cwid: number }
  | { kind: 'logDetail'; logId: string; cwid: number | null }
  | { kind: 'messageDetail'; cwid: number; messageId: string };

const PANEL_PARAM = 'panel';
const CWID_PARAM = 'cwid';
const LOG_PARAM = 'logId';
const MESSAGE_PARAM = 'messageId';

function parseCwid(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

export function parsePanel(params: URLSearchParams): PanelState | null {
  const kind = params.get(PANEL_PARAM);
  const cwid = parseCwid(params.get(CWID_PARAM));

  switch (kind) {
    case 'logs':
      return cwid === null ? null : { kind: 'conversationLogs', cwid };
    case 'chat':
      return cwid === null ? null : { kind: 'conversationChat', cwid };
    case 'log': {
      const logId = params.get(LOG_PARAM);
      return logId ? { kind: 'logDetail', logId, cwid } : null;
    }
    case 'message': {
      const messageId = params.get(MESSAGE_PARAM);
      return cwid !== null && messageId
        ? { kind: 'messageDetail', cwid, messageId }
        : null;
    }
    default:
      return null;
  }
}

export function serializePanel(
  params: URLSearchParams,
  panel: PanelState | null,
): URLSearchParams {
  const next = new URLSearchParams(params);
  next.delete(PANEL_PARAM);
  next.delete(CWID_PARAM);
  next.delete(LOG_PARAM);
  next.delete(MESSAGE_PARAM);

  if (!panel) return next;

  switch (panel.kind) {
    case 'conversationLogs':
      next.set(PANEL_PARAM, 'logs');
      next.set(CWID_PARAM, String(panel.cwid));
      break;
    case 'conversationChat':
      next.set(PANEL_PARAM, 'chat');
      next.set(CWID_PARAM, String(panel.cwid));
      break;
    case 'logDetail':
      next.set(PANEL_PARAM, 'log');
      next.set(LOG_PARAM, panel.logId);
      // cwid doubles as the back-arrow signal: present means this detail was
      // opened from a conversation's log list and can navigate back to it.
      if (panel.cwid !== null) next.set(CWID_PARAM, String(panel.cwid));
      break;
    case 'messageDetail':
      next.set(PANEL_PARAM, 'message');
      next.set(CWID_PARAM, String(panel.cwid));
      next.set(MESSAGE_PARAM, panel.messageId);
      break;
  }
  return next;
}

/** The state the back arrow returns to, or null when there is nothing behind. */
export function parentOf(panel: PanelState | null): PanelState | null {
  if (!panel) return null;
  if (panel.kind === 'logDetail' && panel.cwid !== null) {
    return { kind: 'conversationLogs', cwid: panel.cwid };
  }
  if (panel.kind === 'messageDetail') {
    return { kind: 'conversationChat', cwid: panel.cwid };
  }
  return null;
}

export function panelTitle(panel: PanelState): string {
  switch (panel.kind) {
    case 'conversationLogs':
      // Wording fixed by the spec.
      return `Conversation (${panel.cwid})'s Logs`;
    case 'conversationChat':
      return `Conversation (${panel.cwid})`;
    case 'logDetail':
      return 'Log detail';
    case 'messageDetail':
      return 'Message detail';
  }
}

export function usePanel() {
  const [searchParams, setSearchParams] = useSearchParams();

  const panel = useMemo(() => parsePanel(searchParams), [searchParams]);

  const setPanel = useCallback(
    (next: PanelState | null) => {
      // replace: panel moves are view state, not history the back button should
      // have to walk through one entry at a time.
      setSearchParams(serializePanel(searchParams, next), { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const parent = useMemo(() => parentOf(panel), [panel]);
  const goBack = useCallback(() => setPanel(parent), [parent, setPanel]);
  const close = useCallback(() => setPanel(null), [setPanel]);

  return { panel, setPanel, parent, goBack, close };
}

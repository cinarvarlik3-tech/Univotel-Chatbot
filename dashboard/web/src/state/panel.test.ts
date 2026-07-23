/**
 * Panel state machine tests (DASHBOARD_SPEC.md §13.6).
 *
 * The back-arrow rule is the thing worth pinning down: the arrow appears if and
 * only if the state has a parent, which is what distinguishes a log opened from a
 * conversation's log list (has a way back) from one opened on the Logs page.
 */
import { describe, expect, it } from 'vitest';
import { panelTitle, parentOf, parsePanel, serializePanel, type PanelState } from './panel';

function roundTrip(panel: PanelState | null): PanelState | null {
  return parsePanel(serializePanel(new URLSearchParams(), panel));
}

describe('parsePanel / serializePanel', () => {
  it('round-trips a conversation logs panel', () => {
    expect(roundTrip({ kind: 'conversationLogs', cwid: 1704 })).toEqual({
      kind: 'conversationLogs',
      cwid: 1704,
    });
  });

  it('round-trips a chat panel', () => {
    expect(roundTrip({ kind: 'conversationChat', cwid: 231 })).toEqual({
      kind: 'conversationChat',
      cwid: 231,
    });
  });

  it('round-trips a log detail opened from a conversation', () => {
    expect(roundTrip({ kind: 'logDetail', logId: 'abc', cwid: 1704 })).toEqual({
      kind: 'logDetail',
      logId: 'abc',
      cwid: 1704,
    });
  });

  it('round-trips a standalone log detail', () => {
    expect(roundTrip({ kind: 'logDetail', logId: 'abc', cwid: null })).toEqual({
      kind: 'logDetail',
      logId: 'abc',
      cwid: null,
    });
  });

  it('round-trips a message detail', () => {
    expect(roundTrip({ kind: 'messageDetail', cwid: 1704, messageId: 'm1' })).toEqual({
      kind: 'messageDetail',
      cwid: 1704,
      messageId: 'm1',
    });
  });

  it('serializes null as no panel params', () => {
    const params = serializePanel(new URLSearchParams('foo=bar'), null);
    expect(params.get('panel')).toBeNull();
    expect(params.get('cwid')).toBeNull();
    // Unrelated params survive — panel state must not clobber filters.
    expect(params.get('foo')).toBe('bar');
  });

  it('preserves filter params when a panel opens', () => {
    const params = serializePanel(
      new URLSearchParams('status=failed&q=meral'),
      { kind: 'conversationChat', cwid: 1 },
    );
    expect(params.get('status')).toBe('failed');
    expect(params.get('q')).toBe('meral');
    expect(params.get('panel')).toBe('chat');
  });

  it('returns null for an unknown panel kind', () => {
    expect(parsePanel(new URLSearchParams('panel=wat&cwid=1'))).toBeNull();
  });

  it('returns null when a required param is missing', () => {
    expect(parsePanel(new URLSearchParams('panel=logs'))).toBeNull();
    expect(parsePanel(new URLSearchParams('panel=log'))).toBeNull();
    expect(parsePanel(new URLSearchParams('panel=message&cwid=1'))).toBeNull();
  });

  it('returns null for a non-numeric cwid rather than NaN', () => {
    expect(parsePanel(new URLSearchParams('panel=chat&cwid=abc'))).toBeNull();
  });

  it('handles a derived log id containing colons', () => {
    const panel: PanelState = {
      kind: 'logDetail',
      logId: 'derived:human_takeover:f2a1baa2-5bf1-47b6-9378-8d8f51972535',
      cwid: 1704,
    };
    expect(roundTrip(panel)).toEqual(panel);
  });
});

describe('parentOf — drives back-arrow visibility', () => {
  it('gives a log detail opened from a conversation a way back', () => {
    expect(parentOf({ kind: 'logDetail', logId: 'x', cwid: 1704 })).toEqual({
      kind: 'conversationLogs',
      cwid: 1704,
    });
  });

  it('gives a standalone log detail no parent, so no back arrow', () => {
    expect(parentOf({ kind: 'logDetail', logId: 'x', cwid: null })).toBeNull();
  });

  it('returns a message detail to the transcript', () => {
    expect(parentOf({ kind: 'messageDetail', cwid: 9, messageId: 'm' })).toEqual({
      kind: 'conversationChat',
      cwid: 9,
    });
  });

  it('gives top-level panels no parent', () => {
    expect(parentOf({ kind: 'conversationLogs', cwid: 1 })).toBeNull();
    expect(parentOf({ kind: 'conversationChat', cwid: 1 })).toBeNull();
    expect(parentOf(null)).toBeNull();
  });
});

describe('panelTitle', () => {
  it("uses the exact wording the spec fixes for a conversation's logs", () => {
    expect(panelTitle({ kind: 'conversationLogs', cwid: 1704 })).toBe(
      "Conversation (1704)'s Logs",
    );
  });

  it('titles the other panels', () => {
    expect(panelTitle({ kind: 'conversationChat', cwid: 1704 })).toBe('Conversation (1704)');
    expect(panelTitle({ kind: 'logDetail', logId: 'x', cwid: null })).toBe('Log detail');
    expect(panelTitle({ kind: 'messageDetail', cwid: 1, messageId: 'm' })).toBe(
      'Message detail',
    );
  });
});

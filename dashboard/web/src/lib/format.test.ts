/** Formatting tests — the em-dash rule is the important one (§9). */
import { describe, expect, it } from 'vitest';
import {
  EM_DASH,
  formatDateTime,
  formatPercent,
  formatStateTransition,
  truncate,
} from './format';

describe('null handling', () => {
  it('renders an em-dash rather than inventing a value', () => {
    expect(formatDateTime(null)).toBe(EM_DASH);
    expect(formatDateTime(undefined)).toBe(EM_DASH);
    expect(formatPercent(null)).toBe(EM_DASH);
    expect(truncate(null, 10)).toBe(EM_DASH);
    expect(formatStateTransition(null, null)).toBe(EM_DASH);
  });

  it('renders an em-dash for an unparseable timestamp instead of "Invalid Date"', () => {
    expect(formatDateTime('not-a-date')).toBe(EM_DASH);
  });

  it('does not confuse 0% with no data', () => {
    expect(formatPercent(0)).toBe('0.0%');
    expect(formatPercent(null)).toBe(EM_DASH);
  });
});

describe('formatDateTime', () => {
  it('renders in Istanbul time, which is the business timezone', () => {
    // 21:20 UTC is 00:20 the next day in Istanbul (UTC+3).
    expect(formatDateTime('2026-07-22T21:20:03Z')).toContain('00:20');
    expect(formatDateTime('2026-07-22T21:20:03Z')).toContain('23 Jul');
  });
});

describe('truncate', () => {
  it('collapses whitespace so multi-line explanations stay on one row', () => {
    expect(truncate('a\n\n  b   c', 40)).toBe('a b c');
  });

  it('adds an ellipsis only when it actually cuts', () => {
    expect(truncate('exact', 5)).toBe('exact');
    expect(truncate('longer text here', 8)).toBe('longer …');
  });
});

describe('formatStateTransition', () => {
  it('marks a missing half rather than hiding it', () => {
    expect(formatStateTransition('new', null)).toBe('new → ?');
    expect(formatStateTransition(null, 'completed')).toBe('? → completed');
  });
});

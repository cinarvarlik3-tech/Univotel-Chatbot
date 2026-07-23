/**
 * Status presentation (DASHBOARD_SPEC.md §6.2).
 *
 * Every status carries an icon and a text label alongside its colour. A
 * colourblind reader and a greyscale print both still read the table — colour is
 * never the sole carrier of meaning.
 */
import type { MarkerKind, Status } from '../api/types';

export interface StatusStyle {
  label: string;
  icon: string;
  /** Text/border colour. */
  color: string;
  /** Row background tint. */
  tint: string;
  description: string;
}

export const STATUS_STYLES: Record<Status, StatusStyle> = {
  success: {
    label: 'Completed',
    icon: '✓',
    color: '#22C55E',
    tint: 'rgba(34,197,94,0.10)',
    description: 'InfoGatherer finished the flow.',
  },
  failed: {
    label: 'Failed',
    icon: '✕',
    color: '#EF4444',
    tint: 'rgba(239,68,68,0.10)',
    description: 'Errored, or stalled mid-flow past the staleness window.',
  },
  in_progress: {
    label: 'In progress',
    icon: '◔',
    color: '#8B9CB3',
    tint: 'rgba(139,156,179,0.07)',
    description: 'Still mid-flow and recently active.',
  },
  human_needed: {
    label: 'Human needed',
    icon: '⚑',
    color: '#A855F7',
    tint: 'rgba(168,85,247,0.10)',
    description: 'Escalated to a human agent by the bot.',
  },
  human_interruption: {
    label: 'Interrupted',
    icon: '⇄',
    color: '#1F93FF',
    tint: 'rgba(31,147,255,0.10)',
    description: 'A human agent replied, which stops the bot.',
  },
  not_run: {
    label: 'Not run',
    icon: '⊘',
    color: '#4B5563',
    tint: 'transparent',
    description: 'Bot declined a pre-existing thread. Excluded from percentages.',
  },
};

/** not_run's rail colour is deliberately sub-3:1; its chip text needs to be legible. */
export function statusTextColor(status: Status): string {
  return status === 'not_run' ? '#94A3B8' : STATUS_STYLES[status].color;
}

export const MARKER_STATUS: Record<MarkerKind, Status> = {
  failure: 'failed',
  human_needed: 'human_needed',
  human_interruption: 'human_interruption',
};

/**
 * Rank-ordered sequential ramp for the pie charts (§6.5).
 *
 * Not a categorical palette, and deliberately so: no 4+ slot categorical subset
 * clears the colourblind floors for an all-pairs form like a pie (measured — best
 * case was normal-vision ΔE 10.6 against a floor of 15). Colour here encodes
 * rank, which every CVD type preserves because the steps differ in lightness.
 * Identity is carried by the direct labels and the legend, never by hue.
 */
export const RANK_RAMP = [
  '#cde2fb',
  '#9ec5f4',
  '#6da7ec',
  '#3987e5',
  '#256abf',
  '#184f95',
] as const;

/** Neutral, outside the ramp — reads as "not a rank". */
export const OTHER_COLOR = '#4B5563';

export function rankColor(index: number, key?: string): string {
  if (key === '__other__') return OTHER_COLOR;
  return RANK_RAMP[Math.min(index, RANK_RAMP.length - 1)];
}

/** Slices are light-on-dark; the lightest steps need dark label text. */
export function rankLabelColor(index: number, key?: string): string {
  if (key === '__other__') return '#FFFFFF';
  return index <= 2 ? '#0A0C10' : '#FFFFFF';
}

/**
 * Notes are yellow everywhere (DASHBOARD_SPEC.md notes addition). Reuses the
 * Chatwoot private-note palette the transcript already validates — conversation
 * notes are meant to read "like the private notes in chatwoot" — with a brighter
 * amber rail/heading so a NOTE is distinct from a genuine private note.
 */
export const NOTE_STYLE = {
  rail: '#EAB308',
  heading: '#EAB308',
  bg: '#2B2718',
  text: '#F5E9C8',
  tint: 'rgba(234,179,8,0.10)',
  dot: '#EAB308',
} as const;

export const BUBBLE_STYLES = {
  inbound: { bg: '#2B3137', text: '#FFFFFF', align: 'left' as const, name: 'Lead' },
  bot: { bg: '#1B5FA8', text: '#FFFFFF', align: 'right' as const, name: 'ChatBot' },
  human: { bg: '#5B21B6', text: '#FFFFFF', align: 'right' as const, name: 'Agent' },
  private: { bg: '#2B2718', text: '#F5E9C8', align: 'right' as const, name: 'Private note' },
};

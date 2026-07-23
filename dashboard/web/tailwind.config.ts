import type { Config } from 'tailwindcss';

// Tokens mirror DASHBOARD_SPEC.md §6. Contrast ratios in the comments are
// measured against --bg-surface #12161C.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: '#0A0C10',
        surface: '#12161C',
        surface2: '#171C24',
        transcript: '#000000',
        border: '#242C38',
        ink: '#FFFFFF',
        ink2: '#A9B4C4',
        ink3: '#6B7787',
        status: {
          success: '#22C55E',            // 7.96:1
          failed: '#EF4444',             // 4.82:1
          progress: '#8B9CB3',           // 6.48:1
          human: '#A855F7',              // 4.59:1
          interrupt: '#1F93FF',          // 5.77:1
          notrun: '#4B5563',             // rail only — sub-3:1 by design
          notrunText: '#94A3B8',         // 5.6:1 — the legible chip text
        },
        bubble: {
          inbound: '#2B3137',            // white text 13.15:1
          bot: '#1B5FA8',                // white text 6.46:1
          human: '#5B21B6',              // white text 8.98:1
          private: '#2B2718',
          privateRail: '#EAB308',
          privateText: '#F5E9C8',
        },
        // Rank-ordered sequential ramp for the pies (§6.5). Validated as an
        // ordinal ramp on the dark surface: monotone L, adjacent ΔL ≥ 0.06,
        // dark-end contrast 2.24:1, hue spread 4°.
        rank: {
          1: '#cde2fb',
          2: '#9ec5f4',
          3: '#6da7ec',
          4: '#3987e5',
          5: '#256abf',
          6: '#184f95',
          other: '#4B5563',
        },
      },
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto',
               'Helvetica Neue', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config;

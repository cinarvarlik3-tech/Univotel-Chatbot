/**
 * Right panel shell (DASHBOARD_SPEC.md §7.3).
 *
 * Rendered only when a panel state exists — "if it's not displaying information
 * it does not appear", including in the DOM. The parent unmounts this entirely.
 */
import { useEffect, useRef, type ReactNode } from 'react';

interface Props {
  title: string;
  onClose: () => void;
  onBack: (() => void) | null;
  width: number;
  onResize: (width: number) => void;
  expanded: boolean;
  onToggleExpand: () => void;
  headerExtra?: ReactNode;
  children: ReactNode;
}

const MIN_WIDTH = 360;
const MAX_WIDTH = 840;

export default function RightPanel({
  title,
  onClose,
  onBack,
  width,
  onResize,
  expanded,
  onToggleExpand,
  headerExtra,
  children,
}: Props) {
  const panelRef = useRef<HTMLElement>(null);
  const dragging = useRef(false);

  // Esc closes; ← goes back when there is somewhere to go.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key === 'ArrowLeft' && onBack && event.target === panelRef.current) {
        onBack();
      }
    }
    const node = panelRef.current;
    node?.addEventListener('keydown', onKeyDown);
    return () => node?.removeEventListener('keydown', onKeyDown);
  }, [onClose, onBack]);

  // Move focus into the panel on open so keyboard users land where the content
  // changed. The invoking button restores focus on close via the caller.
  useEffect(() => {
    panelRef.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    function onMove(event: MouseEvent) {
      if (!dragging.current) return;
      const next = window.innerWidth - event.clientX;
      onResize(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, next)));
    }
    function onUp() {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [onResize]);

  const effectiveWidth = expanded ? Math.round(window.innerWidth * 0.5) : width;

  return (
    <aside
      ref={panelRef}
      tabIndex={-1}
      role="complementary"
      aria-label={title}
      className="relative flex h-full min-h-0 flex-col border-l border-border bg-surface outline-none"
      style={{ width: effectiveWidth }}
    >
      {/* Drag handle. Keyboard users get the same range via the ± buttons. */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panel"
        className="absolute left-0 top-0 z-20 h-full w-1 cursor-col-resize hover:bg-status-interrupt/40"
        onMouseDown={() => {
          if (expanded) return;
          dragging.current = true;
          document.body.style.cursor = 'col-resize';
          document.body.style.userSelect = 'none';
        }}
      />

      <header className="flex shrink-0 items-center gap-1.5 border-b border-border px-2.5 py-2.5">
        {onBack && (
          <button
            type="button"
            className="btn-icon shrink-0"
            onClick={onBack}
            aria-label="Back"
            title="Back"
          >
            ←
          </button>
        )}
        <h2 className="flex-1 truncate px-1 font-medium text-ink" title={title}>
          {title}
        </h2>
        {headerExtra}
        <button
          type="button"
          className="btn-icon shrink-0"
          onClick={onToggleExpand}
          aria-label={expanded ? 'Shrink panel' : 'Expand panel'}
          aria-pressed={expanded}
          title={expanded ? 'Shrink panel' : 'Expand panel'}
        >
          {expanded ? '⇥' : '⇤'}
        </button>
        <button
          type="button"
          className="btn-icon shrink-0"
          onClick={onClose}
          aria-label="Close panel"
          title="Close panel"
        >
          ✕
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </aside>
  );
}

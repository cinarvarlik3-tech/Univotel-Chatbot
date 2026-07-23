/**
 * Collapsible left navigation (DASHBOARD_SPEC.md §7.2).
 *
 * NAV is data — adding RecEngine or TagAssigner later is one array entry.
 */
import { NavLink, useLocation } from 'react-router-dom';
import { formatRelative } from '../lib/format';

interface NavItem {
  label: string;
  path: string;
  icon: string;
  children?: { label: string; path: string }[];
}

const NAV: NavItem[] = [
  {
    label: 'InfoGatherer',
    path: '/infogatherer',
    icon: '◈',
    children: [
      { label: 'Conversations', path: '/infogatherer/conversations' },
      { label: 'Statistics', path: '/infogatherer/statistics' },
      { label: 'Logs', path: '/infogatherer/logs' },
    ],
  },
];

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  lastUpdated: string | null;
  isFetching: boolean;
  onRefresh: () => void;
}

export default function LeftNav({
  collapsed,
  onToggle,
  lastUpdated,
  isFetching,
  onRefresh,
}: Props) {
  const location = useLocation();

  return (
    <nav
      className="flex h-full min-h-0 flex-col border-r border-border bg-surface"
      aria-label="Primary"
    >
      <div className="flex items-center gap-2 border-b border-border px-3 py-3">
        {!collapsed && (
          <span className="flex-1 truncate font-semibold tracking-tight text-ink">
            Univotel
          </span>
        )}
        <button
          type="button"
          className="btn-icon shrink-0"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
          aria-expanded={!collapsed}
          title={collapsed ? 'Expand navigation' : 'Collapse navigation'}
        >
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {NAV.map((item) => {
          // When collapsed the sub-items are hidden, so the parent icon carries
          // the accent rail — otherwise location is lost entirely.
          const sectionActive = location.pathname.startsWith(item.path);
          return (
            <div key={item.path} className="mb-1">
              <NavLink
                to={item.path}
                end
                title={collapsed ? item.label : undefined}
                className={({ isActive }) =>
                  [
                    'flex items-center gap-2.5 px-3 py-2 transition-colors',
                    'border-l-2',
                    isActive || (collapsed && sectionActive)
                      ? 'border-status-interrupt bg-surface2 text-ink'
                      : 'border-transparent text-ink2 hover:bg-surface2 hover:text-ink',
                  ].join(' ')
                }
              >
                <span aria-hidden className="w-4 text-center text-status-interrupt">
                  {item.icon}
                </span>
                {!collapsed && <span className="truncate font-medium">{item.label}</span>}
              </NavLink>

              {!collapsed && item.children && (
                <ul className="mt-0.5">
                  {item.children.map((child) => (
                    <li key={child.path}>
                      <NavLink
                        to={child.path}
                        className={({ isActive }) =>
                          [
                            'block py-1.5 pl-[38px] pr-3 transition-colors border-l-2',
                            isActive
                              ? 'border-status-interrupt bg-surface2/60 text-ink'
                              : 'border-transparent text-ink2 hover:text-ink',
                          ].join(' ')
                        }
                      >
                        {child.label}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      <div className="border-t border-border px-3 py-2.5">
        {collapsed ? (
          <button
            type="button"
            className="btn-icon"
            onClick={onRefresh}
            aria-label="Refresh data"
            title="Refresh data"
          >
            ⟳
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <span
              aria-hidden
              className={[
                'h-1.5 w-1.5 shrink-0 rounded-full',
                isFetching ? 'bg-status-interrupt' : 'bg-status-success',
              ].join(' ')}
            />
            <span
              className="flex-1 truncate text-[11px] text-ink3"
              aria-live="polite"
            >
              {isFetching ? 'Refreshing…' : `Updated ${formatRelative(lastUpdated)}`}
            </span>
            <button
              type="button"
              className="btn-icon shrink-0"
              onClick={onRefresh}
              aria-label="Refresh data"
              title="Refresh data"
            >
              ⟳
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}

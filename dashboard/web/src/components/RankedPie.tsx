/**
 * Pie chart with a rank-ordered sequential ramp (DASHBOARD_SPEC.md §6.5).
 *
 * Why not categorical colours: a pie is an all-pairs form — a reader compares any
 * two slices, not just neighbours. Running the palette validator, no 4+ slot
 * categorical subset clears the colourblind floors (best case normal-vision
 * ΔE 10.6 against a hard floor of 15). A single-hue ramp assigned by rank encodes
 * magnitude through lightness, which every CVD type preserves.
 *
 * Identity is therefore carried by the legend and the table view, never by hue —
 * which is also why the table toggle is not optional decoration.
 */
import { useState } from 'react';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import type { Breakdown, Slice } from '../api/types';
import { OTHER_COLOR, rankColor } from '../lib/colors';
import { EmptyState, SkeletonBlock } from './States';

interface Props {
  title: string;
  data: Breakdown | undefined;
  isLoading: boolean;
  emptyTitle: string;
  onSliceClick?: (slice: Slice) => void;
}

function SliceTooltip({ active, payload }: { active?: boolean; payload?: { payload: Slice }[] }) {
  if (!active || !payload?.length) return null;
  const slice = payload[0].payload;
  return (
    <div className="card max-w-xs p-2 text-[12px] shadow-lg">
      <p className="font-medium text-ink">{slice.label}</p>
      <p className="tabular text-ink2">
        {slice.count} · {slice.pct.toFixed(1)}%
      </p>
      {slice.members && (
        <ul className="mt-1 border-t border-border pt-1 text-[11px] text-ink3">
          {slice.members.map((member) => (
            <li key={member.key} className="flex justify-between gap-3">
              <span className="truncate">{member.label}</span>
              <span className="tabular">{member.count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function RankedPie({ title, data, isLoading, emptyTitle, onSliceClick }: Props) {
  const [showTable, setShowTable] = useState(false);

  if (isLoading || !data) {
    return (
      <div className="card p-4">
        <h3 className="mb-3 text-[12px] font-medium text-ink2">{title}</h3>
        <SkeletonBlock height={220} />
      </div>
    );
  }

  if (data.total === 0) {
    return (
      <div className="card p-4">
        <h3 className="mb-1 text-[12px] font-medium text-ink2">{title}</h3>
        <EmptyState title={emptyTitle} />
      </div>
    );
  }

  return (
    <div className="card flex flex-col p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-[12px] font-medium text-ink2">{title}</h3>
        <button
          type="button"
          className="btn"
          onClick={() => setShowTable((open) => !open)}
          aria-pressed={showTable}
        >
          {showTable ? 'Chart' : 'Table'}
        </button>
      </div>
      <p className="tabular mb-2 text-[11px] text-ink3">
        {data.total} total · {data.slices.length}{' '}
        {data.slices.length === 1 ? 'category' : 'categories'}
      </p>

      {showTable ? (
        <table className="w-full">
          <thead>
            <tr>
              <th scope="col" className="th">Category</th>
              <th scope="col" className="th text-right">Count</th>
              <th scope="col" className="th text-right">Share</th>
            </tr>
          </thead>
          <tbody>
            {data.slices.map((slice, index) => (
              <tr key={slice.key}>
                <td className="td">
                  <span className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className="h-2.5 w-2.5 shrink-0 rounded-sm"
                      style={{ backgroundColor: rankColor(index, slice.key) }}
                    />
                    <span className="text-[12px] text-ink2">{slice.label}</span>
                  </span>
                </td>
                <td className="td tabular text-right text-[12px] text-ink2">{slice.count}</td>
                <td className="td tabular text-right text-[12px] text-ink2">
                  {slice.pct.toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <>
          <div style={{ height: 200 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data.slices}
                  dataKey="count"
                  nameKey="label"
                  cx="50%"
                  cy="50%"
                  innerRadius={44}
                  outerRadius={80}
                  // 2px surface gap between segments, per the mark spec. A lone
                  // slice gets none — the gap would render as a seam in a full ring.
                  paddingAngle={data.slices.length > 1 ? 1.5 : 0}
                  stroke="#12161C"
                  strokeWidth={2}
                  onClick={(entry: unknown) => onSliceClick?.(entry as Slice)}
                  cursor={onSliceClick ? 'pointer' : 'default'}
                  isAnimationActive={false}
                >
                  {data.slices.map((slice, index) => (
                    <Cell key={slice.key} fill={rankColor(index, slice.key)} />
                  ))}
                </Pie>
                <Tooltip content={<SliceTooltip />} />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Legend in rank order — the identity carrier, so it is never optional. */}
          <ul className="mt-2 space-y-1">
            {data.slices.map((slice, index) => (
              <li key={slice.key} className="flex items-center gap-2 text-[11px]">
                <span
                  aria-hidden
                  className="h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{
                    backgroundColor: rankColor(index, slice.key),
                    outline: slice.key === '__other__' ? `1px dashed ${OTHER_COLOR}` : undefined,
                  }}
                />
                <span className="min-w-0 flex-1 truncate text-ink2" title={slice.label}>
                  {slice.label}
                </span>
                <span className="tabular shrink-0 text-ink3">
                  {slice.count} · {slice.pct.toFixed(1)}%
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

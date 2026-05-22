import React from "react";
import type { DataTableColumn, DataTableQueryState } from "./DataTableShell";

type Props<T> = {
  columns: DataTableColumn<T>[];
  hidden: Set<string>;
  onToggleColumn: (key: string) => void;
  pageSize?: number;
  queryState?: DataTableQueryState;
  onPageSizeChange?: (size: number) => void;
  onQueryChange?: (next: DataTableQueryState) => void;
};

export function DataTableColumnVisibility<T>({
  columns,
  hidden,
  onToggleColumn,
  pageSize,
  queryState,
  onPageSizeChange,
  onQueryChange,
}: Props<T>) {
  return (
    <div className="campaign-actions">
      {onPageSizeChange ? (
        <select
          value={String(pageSize || queryState?.pageSize || 50)}
          onChange={(e) => {
            const next = Number(e.target.value);
            onPageSizeChange(next);
            if (queryState && onQueryChange) onQueryChange({ ...queryState, pageSize: next });
          }}
        >
          {[25, 50, 100, 250].map((s) => <option key={s} value={String(s)}>{s}/page</option>)}
        </select>
      ) : null}
      {columns.map((c) => (
        <label key={c.key}>
          <input
            aria-label={`Toggle column ${c.title}`}
            type="checkbox"
            checked={!hidden.has(c.key)}
            onChange={() => onToggleColumn(c.key)}
          />
          {c.title}
        </label>
      ))}
    </div>
  );
}

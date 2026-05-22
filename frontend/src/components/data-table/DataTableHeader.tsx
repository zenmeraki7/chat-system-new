import React from "react";
import type { DataTableColumn, SortState } from "./DataTableShell";
import type { DataTableSelectionIntent } from "./useDataTableSelection";

type Props<T> = {
  visibleColumns: DataTableColumn<T>[];
  hasSelection: boolean;
  hasRowActions?: boolean;
  rowActionsLabel?: string;
  allVisibleSelected?: boolean;
  someVisibleSelected?: boolean;
  headerCheckboxRef: React.RefObject<HTMLInputElement | null>;
  sort?: SortState;
  allowedSorts?: string[];
  onSortChange?: (next: SortState) => void;
  onSelectionIntent?: (intent: DataTableSelectionIntent) => void;
  getPageToggleIntent: () => DataTableSelectionIntent;
};

export function DataTableHeader<T>({
  visibleColumns,
  hasSelection,
  hasRowActions,
  rowActionsLabel,
  allVisibleSelected,
  someVisibleSelected,
  headerCheckboxRef,
  sort,
  allowedSorts = [],
  onSortChange,
  onSelectionIntent,
  getPageToggleIntent,
}: Props<T>) {
  return (
    <thead>
      <tr role="row">
        {hasSelection ? (
          <th>
            <input
              ref={headerCheckboxRef}
              aria-label="Select all rows on this page"
              aria-checked={someVisibleSelected ? "mixed" : !!allVisibleSelected}
              type="checkbox"
              checked={!!allVisibleSelected}
              onChange={() => onSelectionIntent?.(getPageToggleIntent())}
            />
          </th>
        ) : null}
        {visibleColumns.map((c) => {
          const sortKey = c.sortKey || c.key;
          const canSort = Boolean(c.sortable && onSortChange && allowedSorts.includes(sortKey));
          const active = sort?.key === sortKey;
          return (
            <th
              key={c.key}
              role="columnheader"
              aria-sort={active ? (sort?.dir === "asc" ? "ascending" : "descending") : "none"}
              style={c.width ? { width: c.width } : undefined}
            >
              {canSort ? (
                <button
                  type="button"
                  onClick={() => onSortChange({
                    key: sortKey,
                    dir: active && sort?.dir === "asc" ? "desc" : "asc",
                  })}
                >
                  {c.title}{active ? (sort?.dir === "asc" ? " (asc)" : " (desc)") : ""}
                </button>
              ) : c.title}
            </th>
          );
        })}
        {hasRowActions ? <th role="columnheader">{rowActionsLabel || "Actions"}</th> : null}
      </tr>
    </thead>
  );
}

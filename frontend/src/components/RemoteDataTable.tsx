import React, { ReactNode } from "react";
import { DataTable, type DataTableColumn } from "./DataTable";
import type { SelectionState } from "../lib/queryContract";

type RemoteDataTableProps<T> = {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  selectedIds: Set<string>;
  selection: SelectionState;
  allVisibleSelected: boolean;
  visibleSelectedCount: number;
  totalApprox?: number;
  onToggleRow: (id: string) => void;
  onToggleAllVisible: () => void;
  onSelectAllMatching: () => void | Promise<void>;
  onClearSelection: () => void;
  sortBy?: string;
  sortDir?: "asc" | "desc";
  onSort?: (key: string) => void;
  storageKey?: string;
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
  children?: ReactNode;
};

function formatApprox(value?: number): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "many";
  return value.toLocaleString();
}

export function RemoteDataTable<T>(props: RemoteDataTableProps<T>) {
  const {
    columns,
    rows,
    rowKey,
    loading,
    selectedIds,
    selection,
    allVisibleSelected,
    visibleSelectedCount,
    totalApprox,
    onToggleRow,
    onToggleAllVisible,
    onSelectAllMatching,
    onClearSelection,
    sortBy,
    sortDir,
    onSort,
    storageKey,
    pageSize,
    onPageSizeChange,
    children,
  } = props;

  const showSelectAllPrompt = selection.mode === "explicit" && allVisibleSelected && rows.length > 0;
  const showAllMatchingActive = selection.mode === "all_matching_query";

  return (
    <div>
      {(showSelectAllPrompt || showAllMatchingActive) ? (
        <div className="campaign-actions">
          {showSelectAllPrompt ? (
            <>
              <span>Selected {visibleSelectedCount.toLocaleString()} visible rows.</span>
              <button type="button" onClick={() => void onSelectAllMatching()}>
                Select all {formatApprox(totalApprox)} matching contacts?
              </button>
              <button type="button" onClick={onClearSelection}>Clear</button>
            </>
          ) : null}
          {showAllMatchingActive ? (
            <>
              <span>
                All {formatApprox(totalApprox)} matching rows selected
                {selection.excludedIds.length > 0 ? ` (except ${selection.excludedIds.length.toLocaleString()})` : ""}.
              </span>
              <button type="button" onClick={onClearSelection}>Clear selection</button>
            </>
          ) : null}
        </div>
      ) : null}

      <DataTable
        columns={columns}
        rows={rows}
        rowKey={rowKey}
        loading={loading}
        selectedIds={selectedIds}
        onToggleRow={onToggleRow}
        onToggleAll={onToggleAllVisible}
        allVisibleSelected={allVisibleSelected}
        enableColumnVisibility
        storageKey={storageKey}
        pageSize={pageSize}
        onPageSizeChange={onPageSizeChange}
        virtualizedHeight={380}
        sortBy={sortBy}
        sortDir={sortDir}
        onSort={onSort}
      />
      {children}
    </div>
  );
}


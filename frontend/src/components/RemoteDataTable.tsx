import React, { ReactNode } from "react";
import { DataTable, type DataTableColumn, type DataTablePageInfo, type DataTableQueryState, type DataTableStorageScope, type SortState } from "./DataTable";
import type { SelectionState } from "../lib/queryContract";
import { DataTableSelectionBar } from "./data-table/DataTableSelectionBar";

type RemoteDataTableProps<T> = {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  isFetching?: boolean;
  error?: { title: string; message: string; code?: string } | string;
  onRetry?: () => void;
  emptyState?: ReactNode;
  selectedIds: Set<string>;
  selection: SelectionState;
  allVisibleSelected: boolean;
  visibleSelectedCount: number;
  totalApprox?: number;
  totalCount?: number;
  pageInfo: DataTablePageInfo;
  queryState: DataTableQueryState;
  onQueryChange: (next: DataTableQueryState) => void;
  onNextPage: () => void;
  onPreviousPage: () => void;
  onToggleRow: (id: string) => void;
  onSelectPage: () => void;
  onClearPage: () => void;
  onSelectAllMatching: () => void | Promise<void>;
  onClearSelection: () => void;
  onExport?: (request: {
    mode: "selected_ids" | "current_query";
    selectedIds: string[];
    visibleColumnKeys: string[];
    queryState?: DataTableQueryState;
  }) => void;
  sort?: SortState;
  allowedSorts?: string[];
  onSortChange?: (next: SortState) => void;
  sortBy?: string;
  sortDir?: "asc" | "desc";
  onSort?: (key: string) => void;
  storageScope?: DataTableStorageScope;
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
  children?: ReactNode;
};

export function RemoteDataTable<T>(props: RemoteDataTableProps<T>) {
  const {
    columns,
    rows,
    rowKey,
    loading,
    isFetching,
    error,
    onRetry,
    emptyState,
    selectedIds,
    selection,
    allVisibleSelected,
    visibleSelectedCount,
    totalApprox,
    totalCount,
    pageInfo,
    queryState,
    onQueryChange,
    onNextPage,
    onPreviousPage,
    onToggleRow,
    onSelectPage,
    onClearPage,
    onSelectAllMatching,
    onClearSelection,
    onExport,
    sort,
    allowedSorts,
    onSortChange,
    sortBy,
    sortDir,
    onSort,
    storageScope,
    pageSize,
    onPageSizeChange,
    children,
  } = props;

  return (
    <div>
      <DataTableSelectionBar
        selection={selection}
        allVisibleSelected={allVisibleSelected}
        rowsCount={rows.length}
        visibleSelectedCount={visibleSelectedCount}
        totalApprox={totalApprox}
        onSelectAllMatching={onSelectAllMatching}
        onClearSelection={onClearSelection}
      />

      <DataTable
        columns={columns}
        rows={rows}
        rowKey={rowKey}
        loading={loading}
        isFetching={isFetching}
        error={error}
        onRetry={onRetry}
        emptyState={emptyState}
        totalCount={totalCount}
        pageInfo={pageInfo}
        queryState={queryState}
        onQueryChange={onQueryChange}
        onNextPage={onNextPage}
        onPreviousPage={onPreviousPage}
        selectedIds={selectedIds}
        onToggleRow={onToggleRow}
        onSelectionIntent={(intent) => {
          if (intent.type === "select_page") onSelectPage();
          if (intent.type === "clear_page") onClearPage();
          if (intent.type === "select_all_matching_filter") void onSelectAllMatching();
          if (intent.type === "clear_all") onClearSelection();
        }}
        allVisibleSelected={allVisibleSelected}
        enableColumnVisibility
        storageScope={storageScope}
        pageSize={pageSize}
        onPageSizeChange={onPageSizeChange}
        onExport={onExport}
        sort={sort}
        allowedSorts={allowedSorts}
        onSortChange={onSortChange}
        sortBy={sortBy}
        sortDir={sortDir}
        onSort={onSort}
      />
      {children}
    </div>
  );
}

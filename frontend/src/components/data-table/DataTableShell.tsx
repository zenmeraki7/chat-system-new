import React, { ReactNode, useMemo } from "react";
import { DataTableBody } from "./DataTableBody";
import { DataTableColumnVisibility } from "./DataTableColumnVisibility";
import { DataTableHeader } from "./DataTableHeader";
import { DataTablePagination } from "./DataTablePagination";
import { useDataTablePreferences } from "./useDataTablePreferences";
import { useDataTableSelection, type DataTableSelectionIntent } from "./useDataTableSelection";

export type DataTableColumn<T> = {
  key: string;
  title: string;
  sortable?: boolean;
  sortKey?: string;
  width?: string;
  render: (row: T) => ReactNode;
  exportValue?: (row: T) => string | number | boolean | null | undefined;
};

export type SortState = {
  key: string;
  dir: "asc" | "desc";
};

export type DataTableQueryState = {
  search?: string;
  filters?: Record<string, unknown>;
  sort?: { key: string; direction: "asc" | "desc" };
  pageSize: number;
};

export type DataTablePageInfo = {
  hasNextPage: boolean;
  hasPreviousPage: boolean;
  nextCursor?: string;
  previousCursor?: string;
};

export type DataTableStorageScope = {
  businessId: string;
  userId: string;
  tableId: string;
  version: number;
};

export type DataTableExportRequest = {
  mode: "selected_ids" | "current_query";
  selectedIds: string[];
  visibleColumnKeys: string[];
  queryState?: DataTableQueryState;
};

export type DataTableProps<T> = {
  columns: DataTableColumn<T>[];
  rows: T[];
  mode?: "server_paged" | "bounded";
  loading?: boolean;
  isFetching?: boolean;
  error?: { title: string; message: string; code?: string } | string;
  onRetry?: () => void;
  loadingState?: ReactNode;
  emptyState?: ReactNode;
  rowKey: (row: T) => string;
  getRowAriaLabel?: (row: T) => string;
  isRowSelectable?: (row: T) => boolean;
  rowDisabledReason?: (row: T) => string;
  renderRowActions?: (row: T) => ReactNode;
  rowActionsLabel?: string;
  totalCount?: number;
  pageInfo?: DataTablePageInfo;
  queryState?: DataTableQueryState;
  onQueryChange?: (next: DataTableQueryState) => void;
  onNextPage?: () => void;
  onPreviousPage?: () => void;
  selectedIds?: Set<string>;
  onToggleRow?: (id: string) => void;
  onSelectionIntent?: (intent: DataTableSelectionIntent) => void;
  allVisibleSelected?: boolean;
  sort?: SortState;
  allowedSorts?: string[];
  onSortChange?: (next: SortState) => void;
  sortBy?: string;
  sortDir?: "asc" | "desc";
  onSort?: (key: string) => void;
  enableColumnVisibility?: boolean;
  onExport?: (request: DataTableExportRequest) => void;
  storageScope?: DataTableStorageScope;
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
  tableAriaLabel?: string;
  tableCaption?: string;
};

export function DataTableShell<T>(props: DataTableProps<T>) {
  const {
    columns,
    rows,
    mode,
    loading,
    isFetching,
    error,
    onRetry,
    loadingState,
    emptyState,
    rowKey,
    getRowAriaLabel,
    isRowSelectable,
    rowDisabledReason,
    renderRowActions,
    rowActionsLabel,
    totalCount,
    pageInfo,
    queryState,
    onQueryChange,
    onNextPage,
    onPreviousPage,
    selectedIds,
    onToggleRow,
    onSelectionIntent,
    allVisibleSelected,
    sort,
    allowedSorts,
    onSortChange,
    sortBy,
    sortDir,
    onSort,
    enableColumnVisibility,
    onExport,
    storageScope,
    pageSize,
    onPageSizeChange,
    tableAriaLabel,
    tableCaption,
  } = props;
  void mode;

  const duplicateKeys = useMemo(() => {
    const seen = new Set<string>();
    const duplicates: string[] = [];
    for (const c of columns) {
      if (seen.has(c.key)) duplicates.push(c.key);
      seen.add(c.key);
    }
    return duplicates;
  }, [columns]);

  if (duplicateKeys.length > 0) {
    return <div role="alert">Duplicate column keys: {duplicateKeys.join(", ")}</div>;
  }

  const { hidden, visibleColumns, toggleColumn } = useDataTablePreferences(columns, storageScope);
  const { headerCheckboxRef, someVisibleSelected, getPageToggleIntent } = useDataTableSelection(selectedIds, allVisibleSelected);
  const effectiveSort: SortState | undefined = sort
    || (queryState?.sort ? { key: queryState.sort.key, dir: queryState.sort.direction } : undefined)
    || (sortBy && sortDir ? { key: sortBy, dir: sortDir } : undefined);

  return (
    <div role="region" aria-label={tableAriaLabel || "Data table"}>
      {enableColumnVisibility ? (
        <DataTableColumnVisibility
          columns={columns}
          hidden={hidden}
          onToggleColumn={toggleColumn}
          pageSize={pageSize}
          queryState={queryState}
          onPageSizeChange={onPageSizeChange}
          onQueryChange={onQueryChange}
        />
      ) : null}

      {onExport ? (
        <div className="campaign-actions">
          <button
            type="button"
            onClick={() => {
              const selected = Array.from(selectedIds || []);
              onExport({
                mode: selected.length > 0 ? "selected_ids" : "current_query",
                selectedIds: selected,
                visibleColumnKeys: visibleColumns.map((c) => c.key),
                queryState,
              });
            }}
          >
            Export
          </button>
        </div>
      ) : null}

      <div className="table-scroll-wrap">
        <table role="table" aria-rowcount={totalCount || rows.length}>
          {tableCaption ? <caption>{tableCaption}</caption> : null}
          <DataTableHeader
            visibleColumns={visibleColumns}
            hasSelection={!!onSelectionIntent}
            hasRowActions={!!renderRowActions}
            rowActionsLabel={rowActionsLabel}
            allVisibleSelected={allVisibleSelected}
            someVisibleSelected={someVisibleSelected}
            headerCheckboxRef={headerCheckboxRef}
            sort={effectiveSort}
            allowedSorts={allowedSorts}
            onSortChange={(next) => {
              if (onSortChange) {
                onSortChange(next);
                return;
              }
              if (queryState && onQueryChange) {
                onQueryChange({ ...queryState, sort: { key: next.key, direction: next.dir } });
                return;
              }
              onSort?.(next.key);
            }}
            onSelectionIntent={onSelectionIntent}
            getPageToggleIntent={getPageToggleIntent}
          />
          <DataTableBody
            rows={rows}
            rowKey={rowKey}
            visibleColumns={visibleColumns}
            selectedIds={selectedIds}
            onToggleRow={onToggleRow}
            loading={loading}
            isFetching={isFetching}
            error={error}
            onRetry={onRetry}
            hasSelection={!!onSelectionIntent}
            loadingState={loadingState}
            emptyState={emptyState}
            getRowAriaLabel={getRowAriaLabel}
            isRowSelectable={isRowSelectable}
            rowDisabledReason={rowDisabledReason}
            renderRowActions={renderRowActions}
          />
        </table>
      </div>

      <DataTablePagination
        hasPreviousPage={pageInfo?.hasPreviousPage}
        hasNextPage={pageInfo?.hasNextPage}
        onPreviousPage={onPreviousPage}
        onNextPage={onNextPage}
        isFetching={isFetching}
        rowsCount={rows.length}
        totalCount={totalCount}
      />
    </div>
  );
}

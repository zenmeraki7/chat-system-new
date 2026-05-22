import React, { ReactNode, useMemo } from "react";
import type { DataTableColumn } from "./DataTableShell";

type DataTableError = { title: string; message: string; code?: string };

type Props<T> = {
  rows: T[];
  rowKey: (row: T) => string;
  visibleColumns: DataTableColumn<T>[];
  selectedIds?: Set<string>;
  onToggleRow?: (id: string) => void;
  loading?: boolean;
  isFetching?: boolean;
  error?: DataTableError | string;
  onRetry?: () => void;
  hasSelection: boolean;
  loadingState?: ReactNode;
  emptyState?: ReactNode;
  getRowAriaLabel?: (row: T) => string;
  isRowSelectable?: (row: T) => boolean;
  rowDisabledReason?: (row: T) => string;
  renderRowActions?: (row: T) => ReactNode;
};

function CellErrorFallback({ message }: { message: string }) {
  return <span title={message}>[render error]</span>;
}

class RenderErrorBoundary extends React.Component<{ children: ReactNode }, { hasError: boolean; message: string }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, message: "" };
  }
  static getDerivedStateFromError(error: unknown) {
    return { hasError: true, message: error instanceof Error ? error.message : "unknown error" };
  }
  render() {
    if (this.state.hasError) return <CellErrorFallback message={this.state.message} />;
    return this.props.children;
  }
}

export function DataTableBody<T>({
  rows,
  rowKey,
  visibleColumns,
  selectedIds,
  onToggleRow,
  loading,
  isFetching,
  error,
  onRetry,
  hasSelection,
  loadingState,
  emptyState,
  getRowAriaLabel,
  isRowSelectable,
  rowDisabledReason,
  renderRowActions,
}: Props<T>) {
  const columnCount = visibleColumns.length + (hasSelection ? 1 : 0) + (renderRowActions ? 1 : 0);

  const renderedRows = useMemo(
    () => rows.map((row) => {
      const id = rowKey(row);
      const selectable = isRowSelectable ? isRowSelectable(row) : true;
      const disabledReason = rowDisabledReason ? rowDisabledReason(row) : undefined;
      const rowLabel = getRowAriaLabel ? getRowAriaLabel(row) : `Select row ${id}`;
      return (
        <tr key={id} role="row" aria-label={getRowAriaLabel ? rowLabel : undefined}>
          {onToggleRow ? (
            <td>
              <input
                aria-label={rowLabel}
                type="checkbox"
                checked={!!selectedIds?.has(id)}
                disabled={!selectable}
                title={!selectable ? (disabledReason || "Row not selectable") : undefined}
                onChange={() => {
                  if (!selectable) return;
                  onToggleRow(id);
                }}
              />
            </td>
          ) : null}
          {visibleColumns.map((c) => (
            <td key={`${id}:${c.key}`} role="cell">
              <RenderErrorBoundary>{c.render(row)}</RenderErrorBoundary>
            </td>
          ))}
          {renderRowActions ? <td role="cell">{renderRowActions(row)}</td> : null}
        </tr>
      );
    }),
    [rows, rowKey, onToggleRow, selectedIds, visibleColumns, getRowAriaLabel, isRowSelectable, rowDisabledReason, renderRowActions]
  );

  const errorObj = typeof error === "string" ? { title: "Request failed", message: error } : error;

  return (
    <tbody>
      {(loading || isFetching) && rows.length === 0 ? (
        loadingState ? (
          <tr><td colSpan={columnCount}>{loadingState}</td></tr>
        ) : (
          Array.from({ length: 6 }).map((_, idx) => (
            <tr key={`skeleton-${idx}`} aria-hidden="true">
              <td colSpan={columnCount}>
                <div className="skeleton-line" />
              </td>
            </tr>
          ))
        )
      ) : errorObj ? (
        <tr>
          <td colSpan={columnCount}>
            <strong>{errorObj.title}</strong>
            <div>{errorObj.message}</div>
            {onRetry ? <button type="button" onClick={onRetry}>Retry</button> : null}
          </td>
        </tr>
      ) : rows.length === 0 ? (
        <tr><td colSpan={columnCount}>{emptyState || "No records"}</td></tr>
      ) : renderedRows}
    </tbody>
  );
}

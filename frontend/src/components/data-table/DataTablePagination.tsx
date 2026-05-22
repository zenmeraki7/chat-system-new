import React from "react";

type Props = {
  hasPreviousPage?: boolean;
  hasNextPage?: boolean;
  onPreviousPage?: () => void;
  onNextPage?: () => void;
  isFetching?: boolean;
  rowsCount: number;
  totalCount?: number;
};

export function DataTablePagination({
  hasPreviousPage,
  hasNextPage,
  onPreviousPage,
  onNextPage,
  isFetching,
  rowsCount,
  totalCount,
}: Props) {
  return (
    <>
      <div className="campaign-actions">
        <button type="button" disabled={!hasPreviousPage} onClick={onPreviousPage}>Previous Page</button>
        <button type="button" disabled={!hasNextPage} onClick={onNextPage}>Next Page</button>
      </div>
      {isFetching && rowsCount > 0 ? <div>Refreshing...</div> : null}
      {typeof totalCount === "number" ? <div>Total: {totalCount.toLocaleString()}</div> : null}
    </>
  );
}

import React from "react";
import type { SelectionState } from "../../lib/queryContract";

type Props = {
  selection: SelectionState;
  allVisibleSelected: boolean;
  rowsCount: number;
  visibleSelectedCount: number;
  totalApprox?: number;
  onSelectAllMatching: () => void | Promise<void>;
  onClearSelection: () => void;
};

function formatApprox(value?: number): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "many";
  return value.toLocaleString();
}

export function DataTableSelectionBar({
  selection,
  allVisibleSelected,
  rowsCount,
  visibleSelectedCount,
  totalApprox,
  onSelectAllMatching,
  onClearSelection,
}: Props) {
  const showSelectAllPrompt = selection.mode === "explicit" && allVisibleSelected && rowsCount > 0;
  const showAllMatchingActive = selection.mode === "all_matching_query";

  if (!showSelectAllPrompt && !showAllMatchingActive) return null;

  return (
    <div className="campaign-actions">
      {showSelectAllPrompt ? (
        <>
          <span>{visibleSelectedCount.toLocaleString()} selected on this page.</span>
          <button type="button" onClick={() => void onSelectAllMatching()}>
            Select all {formatApprox(totalApprox)} matching contacts?
          </button>
          <button type="button" onClick={onClearSelection}>Clear</button>
        </>
      ) : null}
      {showAllMatchingActive ? (
        <>
          <span>
            All {formatApprox(selection.estimatedCount ?? totalApprox)} matching rows selected
            {selection.excludedIds.size > 0 ? ` (except ${selection.excludedIds.size.toLocaleString()})` : ""}.
          </span>
          <button type="button" onClick={onClearSelection}>Clear selection</button>
        </>
      ) : null}
    </div>
  );
}

import { useEffect, useRef } from "react";

export type DataTableSelectionIntent =
  | { type: "select_page" }
  | { type: "clear_page" }
  | { type: "select_all_matching_filter" }
  | { type: "clear_all" };

export function useDataTableSelection(selectedIds?: Set<string>, allVisibleSelected?: boolean) {
  const headerCheckboxRef = useRef<HTMLInputElement | null>(null);
  const someVisibleSelected = !!selectedIds && selectedIds.size > 0 && !allVisibleSelected;

  useEffect(() => {
    if (headerCheckboxRef.current) {
      headerCheckboxRef.current.indeterminate = someVisibleSelected;
    }
  }, [someVisibleSelected]);

  const getPageToggleIntent = (): DataTableSelectionIntent => (
    allVisibleSelected ? { type: "clear_page" } : { type: "select_page" }
  );

  return { headerCheckboxRef, someVisibleSelected, getPageToggleIntent };
}

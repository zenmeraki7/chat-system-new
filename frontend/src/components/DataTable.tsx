import { ReactNode, useMemo, useState } from "react";

export type DataTableColumn<T> = {
  key: string;
  title: string;
  sortable?: boolean;
  width?: string;
  render: (row: T) => ReactNode;
};

type DataTableProps<T extends { id?: string }> = {
  columns: DataTableColumn<T>[];
  rows: T[];
  loading?: boolean;
  rowKey: (row: T) => string;
  selectedIds?: Set<string>;
  onToggleRow?: (id: string) => void;
  onToggleAll?: () => void;
  allVisibleSelected?: boolean;
  sortBy?: string;
  sortDir?: "asc" | "desc";
  onSort?: (key: string) => void;
  enableColumnVisibility?: boolean;
  enableExportSelected?: boolean;
  virtualizedHeight?: number;
  virtualizedRowHeight?: number;
  storageKey?: string;
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
};

export function DataTable<T extends { id?: string }>(props: DataTableProps<T>) {
  const {
    columns,
    rows,
    loading,
    rowKey,
    selectedIds,
    onToggleRow,
    onToggleAll,
    allVisibleSelected,
    sortBy,
    sortDir,
    onSort,
    enableColumnVisibility,
    enableExportSelected,
    virtualizedHeight = 420,
    virtualizedRowHeight = 44,
    storageKey,
    pageSize,
    onPageSizeChange,
  } = props;
  const [hidden, setHidden] = useState<Set<string>>(() => {
    if (!storageKey) return new Set();
    try {
      const raw = localStorage.getItem(`${storageKey}:hidden_columns`);
      const parsed = raw ? (JSON.parse(raw) as string[]) : [];
      return new Set(parsed);
    } catch {
      return new Set();
    }
  });
  const [scrollTop, setScrollTop] = useState(0);
  const visibleColumns = useMemo(() => columns.filter((c) => !hidden.has(c.key)), [columns, hidden]);
  const canVirtualize = rows.length > 100;
  const startIndex = canVirtualize ? Math.max(0, Math.floor(scrollTop / virtualizedRowHeight) - 5) : 0;
  const endIndex = canVirtualize ? Math.min(rows.length, startIndex + Math.ceil(virtualizedHeight / virtualizedRowHeight) + 10) : rows.length;
  const displayRows = canVirtualize ? rows.slice(startIndex, endIndex) : rows;
  const topSpacer = canVirtualize ? startIndex * virtualizedRowHeight : 0;
  const bottomSpacer = canVirtualize ? Math.max(0, (rows.length - endIndex) * virtualizedRowHeight) : 0;

  const exportSelected = () => {
    if (!selectedIds || selectedIds.size === 0) return;
    const selectedRows = rows.filter((r) => selectedIds.has(rowKey(r)));
    if (!selectedRows.length) return;
    const header = visibleColumns.map((c) => c.title);
    const lines = selectedRows.map((row) =>
      visibleColumns.map((c) => {
        const value = c.render(row);
        const text = typeof value === "string" || typeof value === "number" ? String(value) : "";
        return `"${text.replaceAll("\"", "\"\"")}"`;
      }).join(",")
    );
    const csv = [header.join(","), ...lines].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "table_export_selected.csv";
    a.click();
    URL.revokeObjectURL(url);
  };
  const toggleColumn = (key: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      if (storageKey) localStorage.setItem(`${storageKey}:hidden_columns`, JSON.stringify(Array.from(next)));
      return next;
    });
  };

  return (
    <div>
      {enableColumnVisibility ? (
        <div className="campaign-actions">
          {onPageSizeChange ? (
            <select value={String(pageSize || 50)} onChange={(e) => onPageSizeChange(Number(e.target.value))}>
              {[25, 50, 100, 250].map((s) => <option key={s} value={String(s)}>{s}/page</option>)}
            </select>
          ) : null}
          {columns.map((c) => (
            <label key={c.key}>
              <input
                type="checkbox"
                checked={!hidden.has(c.key)}
                onChange={() => toggleColumn(c.key)}
              />
              {c.title}
            </label>
          ))}
        </div>
      ) : null}
      {enableExportSelected ? (
        <div className="campaign-actions">
          <button type="button" onClick={exportSelected}>Export Selected</button>
        </div>
      ) : null}
      <div style={{ maxHeight: virtualizedHeight, overflow: "auto" }} onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}>
    <table>
      <thead>
        <tr>
          {onToggleAll ? <th><input type="checkbox" checked={!!allVisibleSelected} onChange={onToggleAll} /></th> : null}
          {visibleColumns.map((c) => (
            <th key={c.key} style={c.width ? { width: c.width } : undefined}>
              {c.sortable && onSort ? (
                <button type="button" onClick={() => onSort(c.key)}>
                  {c.title}{sortBy === c.key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                </button>
              ) : c.title}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {topSpacer > 0 ? <tr><td colSpan={visibleColumns.length + (onToggleAll ? 1 : 0)} style={{ height: `${topSpacer}px`, padding: 0, border: "none" }} /></tr> : null}
        {loading ? (
          <tr><td colSpan={visibleColumns.length + (onToggleAll ? 1 : 0)}>Loading...</td></tr>
        ) : rows.length === 0 ? (
          <tr><td colSpan={visibleColumns.length + (onToggleAll ? 1 : 0)}>No records</td></tr>
        ) : displayRows.map((row) => {
          const id = rowKey(row);
          return (
            <tr key={id}>
              {onToggleRow ? (
                <td><input type="checkbox" checked={!!selectedIds?.has(id)} onChange={() => onToggleRow(id)} /></td>
              ) : null}
              {visibleColumns.map((c) => <td key={`${id}:${c.key}`}>{c.render(row)}</td>)}
            </tr>
          );
        })}
        {bottomSpacer > 0 ? <tr><td colSpan={visibleColumns.length + (onToggleAll ? 1 : 0)} style={{ height: `${bottomSpacer}px`, padding: 0, border: "none" }} /></tr> : null}
      </tbody>
    </table>
      </div>
    </div>
  );
}

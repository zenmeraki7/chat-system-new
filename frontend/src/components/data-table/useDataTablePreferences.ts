import { useEffect, useMemo, useState } from "react";
import type { DataTableColumn, DataTableStorageScope } from "./DataTableShell";

function getHiddenColumnsStorageKey(scope?: DataTableStorageScope): string {
  if (!scope) return "";
  const businessId = String(scope.businessId || "").trim();
  const userId = String(scope.userId || "").trim();
  const tableId = String(scope.tableId || "").trim();
  const version = Number(scope.version || 1);
  if (!businessId || !userId || !tableId) return "";
  return `dt:${businessId}:${userId}:${tableId}:v${version}:hidden_columns`;
}

export function useDataTablePreferences<T>(columns: DataTableColumn<T>[], storageScope?: DataTableStorageScope) {
  const hiddenColumnsStorageKey = useMemo(() => getHiddenColumnsStorageKey(storageScope), [storageScope]);

  const [hidden, setHidden] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set();
    if (!hiddenColumnsStorageKey) return new Set();
    try {
      const raw = localStorage.getItem(hiddenColumnsStorageKey);
      const parsedPayload = raw ? (JSON.parse(raw) as string[]) : [];
      const parsed = Array.isArray(parsedPayload) ? parsedPayload : [];
      return new Set(parsed);
    } catch {
      return new Set();
    }
  });

  useEffect(() => {
    if (!hiddenColumnsStorageKey) {
      setHidden(new Set());
      return;
    }
    try {
      const raw = localStorage.getItem(hiddenColumnsStorageKey);
      const parsedPayload = raw ? (JSON.parse(raw) as string[]) : [];
      setHidden(new Set(Array.isArray(parsedPayload) ? parsedPayload : []));
    } catch {
      setHidden(new Set());
    }
  }, [hiddenColumnsStorageKey]);

  const toggleColumn = (key: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      if (hiddenColumnsStorageKey) {
        localStorage.setItem(hiddenColumnsStorageKey, JSON.stringify(Array.from(next)));
      }
      return next;
    });
  };

  const visibleColumns = useMemo(() => columns.filter((c) => !hidden.has(c.key)), [columns, hidden]);

  return { hidden, visibleColumns, toggleColumn };
}

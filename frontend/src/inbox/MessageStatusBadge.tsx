export function MessageStatusBadge({ status }: { status?: string | null }) {
  return <span className="status-pill">{String(status || "QUEUED").toUpperCase()}</span>;
}

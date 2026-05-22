export function RecipientSnapshotPreview({ total, eligible, skipped }: { total: number; eligible: number; skipped: number }) {
  return (
    <section className="health-grid">
      <div className="health-card"><strong>Total</strong><span>{total}</span></div>
      <div className="health-card"><strong>Eligible</strong><span>{eligible}</span></div>
      <div className="health-card"><strong>Skipped</strong><span>{skipped}</span></div>
    </section>
  );
}

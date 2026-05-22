export function WhatsAppReadinessPanel({
  score,
  state,
  reasons,
}: {
  score?: number;
  state: string;
  reasons?: string[];
}) {
  return (
    <section className="signature-safety-card">
      <div className="signature-safety-head"><h3>WhatsApp Readiness</h3><span>{state}</span></div>
      <div className="signature-safety-score">{Number(score || 0)}<small>/100</small></div>
      {(reasons || []).length ? <ul className="compact-list">{(reasons || []).map((r) => <li key={r}>{r}</li>)}</ul> : null}
    </section>
  );
}

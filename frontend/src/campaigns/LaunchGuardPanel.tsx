export function LaunchGuardPanel({ canLaunch, reasons }: { canLaunch: boolean; reasons: string[] }) {
  return (
    <section className="panel">
      <h3>Launch Guard</h3>
      <p>{canLaunch ? "Ready to launch" : "Launch blocked"}</p>
      {reasons.length ? <ul className="compact-list">{reasons.map((r) => <li key={r}>{r}</li>)}</ul> : null}
    </section>
  );
}

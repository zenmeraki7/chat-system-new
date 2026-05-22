export function DiagnosticsPanel({ title, payload }: { title: string; payload: unknown }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(payload, null, 2)}</pre>
    </section>
  );
}

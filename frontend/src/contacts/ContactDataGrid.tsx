type ContactCRMRecord = {
  id: string;
  phone_e164?: string | null;
  wa_id?: string | null;
  name?: string | null;
  tags: string[];
  opt_in_status: string;
};

export function ContactDataGrid({ rows }: { rows: ContactCRMRecord[] }) {
  return (
    <table>
      <thead><tr><th>Name</th><th>Phone</th><th>Opt-in</th><th>Tags</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td>{r.name || "Unknown"}</td>
            <td>{r.phone_e164 || r.wa_id || "-"}</td>
            <td>{r.opt_in_status}</td>
            <td>{(r.tags || []).join(", ") || "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function WalletStatusCard({ balance, currency = "USD" }: { balance: number; currency?: string }) {
  return (
    <article className="kpi-card">
      <h4>Wallet Balance</h4>
      <p>{currency} {balance.toFixed(2)}</p>
    </article>
  );
}

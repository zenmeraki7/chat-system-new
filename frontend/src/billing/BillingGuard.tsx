export function BillingGuard({ walletOk, children }: { walletOk: boolean; children: React.ReactNode }) {
  if (!walletOk) return <div className="panel"><h3>Billing Guard</h3><p>Wallet is not ready for sending.</p></div>;
  return <>{children}</>;
}

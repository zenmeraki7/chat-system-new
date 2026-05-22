export function PhoneNumberRecoveryActions({
  phoneNumberId,
  onRegister,
  onTest,
}: {
  phoneNumberId: string;
  onRegister: (id: string) => void;
  onTest: (id: string) => void;
}) {
  return (
    <div className="campaign-actions">
      <button onClick={() => onRegister(phoneNumberId)}>Register number</button>
      <button onClick={() => onTest(phoneNumberId)}>Send test message</button>
    </div>
  );
}

export function ConversationLockBanner({ locked, onReopen }: { locked: boolean; onReopen?: () => void }) {
  if (!locked) return null;
  return (
    <div className="closed-chat-row">
      <span>Lock</span>
      <span>This conversation is closed. Reopen to send a message.</span>
      {onReopen ? <button onClick={onReopen}>Reopen</button> : null}
    </div>
  );
}

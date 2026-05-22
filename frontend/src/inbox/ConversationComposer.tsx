import { useState } from "react";

export function ConversationComposer({ onSend }: { onSend: (text: string) => Promise<void> }) {
  const [value, setValue] = useState("");
  return (
    <div className="meta-chat-input">
      <input className="chat-input" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Type reply..." />
      <button onClick={() => onSend(value).then(() => setValue(""))}>Send</button>
    </div>
  );
}

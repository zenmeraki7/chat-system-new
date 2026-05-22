import { createContext, useContext, useMemo, useState } from "react";

type WizardContextValue = {
  campaignId: string | null;
  recipientSnapshotFrozen: boolean;
  setCampaignId: (id: string) => void;
  setRecipientSnapshotFrozen: (v: boolean) => void;
};

const Ctx = createContext<WizardContextValue | null>(null);

export function CampaignWizardProvider({ children }: { children: React.ReactNode }) {
  const [campaignId, setCampaignIdState] = useState<string | null>(null);
  const [recipientSnapshotFrozen, setRecipientSnapshotFrozen] = useState(false);
  const value = useMemo(
    () => ({
      campaignId,
      recipientSnapshotFrozen,
      setCampaignId: (id: string) => setCampaignIdState(id),
      setRecipientSnapshotFrozen,
    }),
    [campaignId, recipientSnapshotFrozen]
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCampaignWizard() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCampaignWizard must be used within CampaignWizardProvider");
  return ctx;
}

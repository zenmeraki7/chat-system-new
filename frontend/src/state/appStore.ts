import { useSyncExternalStore } from "react";

type Id = string;
type EntityName = "campaigns" | "contacts" | "conversations" | "messages" | "templates" | "users";
type EntityMap<T = any> = Record<Id, T>;

type EntityState = Record<EntityName, EntityMap>;
type UiState = {
  inbox: {
    selectedConversationId: string;
    filters: Record<string, unknown>;
    search: string;
    tab: string;
    draftByConversationId: Record<string, string>;
  };
  network: {
    realtimeConnected: boolean;
    lastEventAt: string | null;
    lagMs: number;
    backpressureWarning: string | null;
  };
};

type QueryState = {
  cursors: Record<string, string | undefined>;
  stale: Record<string, boolean>;
  loading: Record<string, boolean>;
  errors: Record<string, string | undefined>;
};

type AppStoreState = {
  entities: EntityState;
  ui: UiState;
  query: QueryState;
};

type Listener = () => void;

type Updater<T> = T | ((prev: T) => T);

const emptyEntities = (): EntityState => ({
  campaigns: {},
  contacts: {},
  conversations: {},
  messages: {},
  templates: {},
  users: {},
});

let state: AppStoreState = {
  entities: emptyEntities(),
  ui: {
    inbox: { selectedConversationId: "", filters: {}, search: "", tab: "today", draftByConversationId: {} },
    network: { realtimeConnected: false, lastEventAt: null, lagMs: 0, backpressureWarning: null },
  },
  query: { cursors: {}, stale: {}, loading: {}, errors: {} },
};

const listeners = new Set<Listener>();
const emit = () => listeners.forEach((listener) => listener());
const setState = (updater: Updater<AppStoreState>) => {
  state = typeof updater === "function" ? (updater as (prev: AppStoreState) => AppStoreState)(state) : updater;
  emit();
};

export const appStore = {
  getSnapshot: () => state,
  subscribe(listener: Listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  upsertMany<T extends { id?: string; public_id?: string; campaign_id?: string }>(entity: EntityName, rows: T[]) {
    if (!rows.length) return;
    setState((prev) => {
      const nextBucket = { ...prev.entities[entity] };
      for (const row of rows) {
        const id = String(row.id || row.public_id || row.campaign_id || "");
        if (!id) continue;
        nextBucket[id] = { ...(nextBucket[id] || {}), ...row };
      }
      return { ...prev, entities: { ...prev.entities, [entity]: nextBucket } };
    });
  },
  upsertOne<T extends { id?: string; public_id?: string; campaign_id?: string }>(entity: EntityName, row: T) {
    this.upsertMany(entity, [row]);
  },
  patchEntity(entity: EntityName, id: string, patch: Record<string, unknown>) {
    if (!id) return;
    setState((prev) => ({
      ...prev,
      entities: {
        ...prev.entities,
        [entity]: {
          ...prev.entities[entity],
          [id]: { ...(prev.entities[entity][id] || {}), ...patch },
        },
      },
    }));
  },
  setInboxUi(patch: Partial<UiState["inbox"]>) {
    setState((prev) => ({ ...prev, ui: { ...prev.ui, inbox: { ...prev.ui.inbox, ...patch } } }));
  },
  setNetwork(patch: Partial<UiState["network"]>) {
    setState((prev) => ({ ...prev, ui: { ...prev.ui, network: { ...prev.ui.network, ...patch } } }));
  },
  setQuery(key: string, patch: { loading?: boolean; stale?: boolean; error?: string; cursor?: string }) {
    setState((prev) => ({
      ...prev,
      query: {
        cursors: patch.cursor === undefined ? prev.query.cursors : { ...prev.query.cursors, [key]: patch.cursor },
        stale: patch.stale === undefined ? prev.query.stale : { ...prev.query.stale, [key]: patch.stale },
        loading: patch.loading === undefined ? prev.query.loading : { ...prev.query.loading, [key]: patch.loading },
        errors: patch.error === undefined ? prev.query.errors : { ...prev.query.errors, [key]: patch.error },
      },
    }));
  },
};

export function useStoreSelector<T>(selector: (snapshot: AppStoreState) => T): T {
  return useSyncExternalStore(appStore.subscribe, () => selector(appStore.getSnapshot()), () => selector(appStore.getSnapshot()));
}

export const selectors = {
  conversations: () => Object.values(appStore.getSnapshot().entities.conversations),
  messagesForConversation: (conversationId: string) => Object.values(appStore.getSnapshot().entities.messages).filter((m: any) => String(m.conversation_id || m.conversation_public_id || "") === conversationId),
};

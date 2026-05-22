import { create } from "zustand";

type SessionState = {
  accessToken: string | null;
  userId: string | null;
  setSession: (input: { accessToken: string }) => void;
  clearSession: () => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  accessToken: sessionStorage.getItem("access_token"),
  userId: null,
  setSession: ({ accessToken }) => {
    sessionStorage.setItem("access_token", accessToken);
    set({ accessToken, userId: null });
  },
  clearSession: () => {
    ["access_token", "token", "auth_token", "jwt", "bearer_token", "current_user_id", "auth_user_id"].forEach((k) => {
      localStorage.removeItem(k);
      sessionStorage.removeItem(k);
    });
    set({ accessToken: null, userId: null });
  },
}));


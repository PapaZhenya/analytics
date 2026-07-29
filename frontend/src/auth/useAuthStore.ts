import { create } from "zustand";

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string;
  role_code: string;
  org_id: string;
  is_active: boolean;
}

interface AuthState {
  accessToken: string | null;
  user: CurrentUser | null;
  setSession: (accessToken: string, user: CurrentUser | null) => void;
  setAccessToken: (accessToken: string | null) => void;
  clear: () => void;
}

// Access token lives in memory only (not localStorage) — the refresh token is the only
// long-lived credential, and it's an httpOnly cookie the JS layer never touches
// directly. Losing the access token on a hard page reload is expected; the app calls
// /auth/refresh on startup to obtain a fresh one from the refresh cookie.
export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  setSession: (accessToken, user) => set({ accessToken, user }),
  setAccessToken: (accessToken) => set({ accessToken }),
  clear: () => set({ accessToken: null, user: null }),
}));

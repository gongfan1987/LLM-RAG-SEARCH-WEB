import { create } from "zustand";
import type { User } from "@/types/auth";
import { fetchCurrentUser, login, register } from "@/lib/api/auth";
import { clearAuthToken, getAuthToken, setAuthToken } from "@/lib/api/tokenStorage";

interface AuthState {
  user: User | null;
  /** 是否已完成首次登录态恢复检测，避免页面闪烁 */
  initialized: boolean;
  loading: boolean;
  error: string | null;

  loginWithPassword: (username: string, password: string) => Promise<boolean>;
  registerWithPassword: (username: string, password: string) => Promise<boolean>;
  restoreSession: () => Promise<void>;
  logout: () => void;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  initialized: false,
  loading: false,
  error: null,

  loginWithPassword: async (username, password) => {
    set({ loading: true, error: null });
    try {
      const { access_token, user } = await login({ username, password });
      setAuthToken(access_token);
      set({ user, loading: false });
      return true;
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : "登录失败",
      });
      return false;
    }
  },

  registerWithPassword: async (username, password) => {
    set({ loading: true, error: null });
    try {
      const { access_token, user } = await register({ username, password });
      setAuthToken(access_token);
      set({ user, loading: false });
      return true;
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : "注册失败",
      });
      return false;
    }
  },

  restoreSession: async () => {
    const token = getAuthToken();
    if (!token) {
      set({ initialized: true });
      return;
    }
    try {
      const user = await fetchCurrentUser();
      set({ user, initialized: true });
    } catch {
      clearAuthToken();
      set({ user: null, initialized: true });
    }
  },

  logout: () => {
    clearAuthToken();
    set({ user: null });
  },

  clearError: () => set({ error: null }),
}));

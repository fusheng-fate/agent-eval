import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { auth } from "../lib/api";
import { setToken, setRefreshToken, clearAuth, getToken } from "../lib/http";
import type { UserOut } from "../lib/types";

interface AuthCtx {
  user: UserOut | null;
  loading: boolean;
  isAdmin: boolean;
  login: (username: string, password: string) => Promise<UserOut>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await auth.me();
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await auth.login(username, password);
    setToken(res.access_token);
    setRefreshToken(res.refresh_token);
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(() => {
    // 先通知后端吊销当前 access_token（jti 黑名单），失败也不阻塞前端登出
    void auth.logout().catch(() => {});
    clearAuth();
    setUser(null);
    window.location.href = "/login";
  }, []);

  const value: AuthCtx = {
    user,
    loading,
    isAdmin: user?.role === "admin",
    login,
    logout,
    refresh,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}

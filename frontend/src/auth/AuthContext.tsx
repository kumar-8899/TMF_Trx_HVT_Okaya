import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, setToken, setUnauthorizedHandler } from "../api/client";
import { hasPermission } from "./permissions";

export interface Principal {
  username: string;
  role: string;
  permissions: string[];
  must_change_password?: boolean;
}

interface AuthValue {
  principal: Principal | null;
  loading: boolean;
  mustChangePassword: boolean;
  login: (username: string, password: string) => Promise<Principal>;
  logout: () => void;
  changePassword: (oldPw: string, newPw: string) => Promise<void>;
  can: (perm: string) => boolean;
}

const TOKEN_KEY = "tmf.token";
const AuthCtx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [loading, setLoading] = useState(true);
  const [mustChange, setMustChange] = useState(false);

  const logout = useCallback(() => {
    api.post("/auth/logout").catch(() => {});
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setPrincipal(null);
    setMustChange(false);
  }, []);

  // 401 from any call drops the session.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      localStorage.removeItem(TOKEN_KEY);
      setToken(null);
      setPrincipal(null);
    });
  }, []);

  // Revalidate a stored token on boot.
  useEffect(() => {
    const tok = localStorage.getItem(TOKEN_KEY);
    if (!tok) {
      setLoading(false);
      return;
    }
    setToken(tok);
    api
      .get("/auth/me")
      .then((me) => setPrincipal(me))
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.post(
      "/auth/login",
      { username, credential: { password } },
      { auth: false },
    );
    localStorage.setItem(TOKEN_KEY, res.token);
    setToken(res.token);
    const p: Principal = res.principal;
    setPrincipal(p);
    setMustChange(Boolean(p.must_change_password));
    return p;
  }, []);

  const changePassword = useCallback(async (oldPw: string, newPw: string) => {
    await api.post("/auth/change-password", { old: oldPw, new: newPw });
    setMustChange(false);
  }, []);

  const can = useCallback((perm: string) => hasPermission(principal?.permissions, perm), [principal]);

  const value = useMemo<AuthValue>(
    () => ({ principal, loading, mustChangePassword: mustChange, login, logout, changePassword, can }),
    [principal, loading, mustChange, login, logout, changePassword, can],
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

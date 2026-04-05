import { useState, useEffect, useCallback } from "react";
import { getAuthStatus, loginWithInvite, logout as apiLogout } from "../api/client";
import type { User, AuthStatus } from "../types";

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [githubEnabled, setGithubEnabled] = useState(false);

  const checkAuth = useCallback(async () => {
    try {
      const data: AuthStatus = await getAuthStatus();
      setUser(data.authenticated ? data.user : null);
      setGithubEnabled(data.github_enabled);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const loginInvite = useCallback(async (code: string) => {
    await loginWithInvite(code);
    await checkAuth();
  }, [checkAuth]);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  return { user, loading, githubEnabled, loginInvite, logout, checkAuth };
}

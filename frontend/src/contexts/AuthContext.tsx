import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import api from "../api/client";

interface AuthContextType {
  isAuthenticated: boolean;
  login: (username: string, password: string, totpCode: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

const TOKEN_KEY = "ts_auth_token";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return !!localStorage.getItem(TOKEN_KEY);
  });

  const login = useCallback(async (username: string, password: string, totpCode: string) => {
    const res = await api.post("/auth/login", {
      username,
      password,
      totp_code: totpCode,
    });
    localStorage.setItem(TOKEN_KEY, res.data.access_token);
    setIsAuthenticated(true);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setIsAuthenticated(false);
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

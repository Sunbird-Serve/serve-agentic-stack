/**
 * AdminContext — Simple token-based auth for admin routes.
 * No Keycloak, no OIDC. Just a static token from .env.
 */
import { createContext, useContext, useState, useCallback } from 'react';

const AdminContext = createContext(null);

const ADMIN_TOKEN_KEY = 'serve_admin_token';

export function AdminProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(ADMIN_TOKEN_KEY) || null);

  const login = useCallback((inputToken) => {
    localStorage.setItem(ADMIN_TOKEN_KEY, inputToken);
    setToken(inputToken);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(ADMIN_TOKEN_KEY);
    setToken(null);
  }, []);

  const value = {
    token,
    isAuthenticated: !!token,
    login,
    logout,
  };

  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>;
}

export function useAdmin() {
  const context = useContext(AdminContext);
  if (!context) {
    throw new Error('useAdmin must be used within AdminProvider');
  }
  return context;
}

export default AdminContext;

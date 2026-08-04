/**
 * AdminContext — Simple token-based auth for admin routes.
 * No Keycloak, no OIDC. Just a static token from .env.
 */
import { createContext, useContext, useState, useCallback } from 'react';

const AdminContext = createContext(null);

const ADMIN_TOKEN_KEY = 'serve_admin_token';
const ADMIN_ROLE_KEY = 'serve_admin_role';

export function AdminProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(ADMIN_TOKEN_KEY) || null);
  const [role, setRole] = useState(() => localStorage.getItem(ADMIN_ROLE_KEY) || null);

  const login = useCallback((inputToken, adminRole = 'vm') => {
    localStorage.setItem(ADMIN_TOKEN_KEY, inputToken);
    localStorage.setItem(ADMIN_ROLE_KEY, adminRole);
    setToken(inputToken);
    setRole(adminRole);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(ADMIN_TOKEN_KEY);
    localStorage.removeItem(ADMIN_ROLE_KEY);
    setToken(null);
    setRole(null);
  }, []);

  const value = {
    token,
    role,
    isAuthenticated: !!token,
    isTech: role === 'tech',
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

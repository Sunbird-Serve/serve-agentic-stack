/**
 * AuthContext — Keycloak Authentication Context
 * Provides user identity, roles, and token to the entire app.
 */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import keycloak from '../lib/keycloak';

const AuthContext = createContext(null);

// Minimum token validity in seconds before refresh
const MIN_TOKEN_VALIDITY = 30;
// Refresh interval (check every 10 seconds)
const TOKEN_REFRESH_INTERVAL = 10000;

/**
 * Map Keycloak realm roles to the app's internal persona/view.
 * Priority order matters — first match wins.
 */
function resolvePersona(roles = []) {
  if (roles.includes('sAdmin')) return 'admin';
  if (roles.includes('nAdmin') || roles.includes('vAdmin')) return 'admin';
  if (roles.includes('vCoordinator')) return 'ops';
  if (roles.includes('nCoordinator')) return 'need_coordinator';
  if (roles.includes('Volunteer')) return 'volunteer';
  // Default fallback
  return 'volunteer';
}

export function AuthProvider({ children }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [user, setUser] = useState(null);
  const [persona, setPersona] = useState(null);
  const refreshIntervalRef = useRef(null);

  const updateUserFromToken = useCallback(() => {
    if (!keycloak.authenticated || !keycloak.tokenParsed) return;

    const tokenParsed = keycloak.tokenParsed;
    const realmRoles = tokenParsed.realm_access?.roles || [];

    const userData = {
      sub: tokenParsed.sub,
      email: tokenParsed.email || '',
      preferredUsername: tokenParsed.preferred_username || '',
      name: tokenParsed.name || tokenParsed.preferred_username || '',
      roles: realmRoles,
      agencyId: tokenParsed.agencyId || null,
      agencyType: tokenParsed.agencyType || null,
      rcOsid: tokenParsed.rcOsid || null,
    };

    setUser(userData);
    setPersona(resolvePersona(realmRoles));
    setAuthenticated(true);
  }, []);

  // Initialize Keycloak
  useEffect(() => {
    keycloak
      .init({
        onLoad: 'login-required',
        pkceMethod: 'S256',
        checkLoginIframe: false,
      })
      .then((auth) => {
        if (auth) {
          updateUserFromToken();
        }
        setInitializing(false);
      })
      .catch((err) => {
        console.error('Keycloak init failed:', err);
        setInitializing(false);
      });

    // Listen for token refresh events
    keycloak.onTokenExpired = () => {
      keycloak.updateToken(MIN_TOKEN_VALIDITY).catch(() => {
        console.warn('Token refresh failed, logging out');
        keycloak.logout();
      });
    };

    keycloak.onAuthRefreshSuccess = () => {
      updateUserFromToken();
    };

    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
      }
    };
  }, [updateUserFromToken]);

  // Periodic token refresh
  useEffect(() => {
    if (!authenticated) return;

    refreshIntervalRef.current = setInterval(() => {
      keycloak.updateToken(MIN_TOKEN_VALIDITY).catch(() => {
        console.warn('Periodic token refresh failed');
        keycloak.logout();
      });
    }, TOKEN_REFRESH_INTERVAL);

    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
      }
    };
  }, [authenticated]);

  const getToken = useCallback(async () => {
    try {
      await keycloak.updateToken(MIN_TOKEN_VALIDITY);
      return keycloak.token;
    } catch {
      keycloak.logout();
      return null;
    }
  }, []);

  const logout = useCallback(() => {
    keycloak.logout({ redirectUri: window.location.origin });
  }, []);

  const value = {
    authenticated,
    initializing,
    user,
    persona,
    getToken,
    logout,
    keycloak,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

export default AuthContext;

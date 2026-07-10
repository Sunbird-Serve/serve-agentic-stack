/**
 * AuthContext — Authentication Context
 *
 * Two modes controlled by REACT_APP_AUTH_ENABLED:
 *   "true"  → Keycloak OIDC login (production / staging)
 *   "false" → Dev bypass with role picker (local dev, no Keycloak needed)
 */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';

const AuthContext = createContext(null);

const AUTH_ENABLED = process.env.REACT_APP_AUTH_ENABLED !== 'false';

// Minimum token validity in seconds before refresh
const MIN_TOKEN_VALIDITY = 30;
const TOKEN_REFRESH_INTERVAL = 10000;

/**
 * Map Keycloak realm roles to the app's internal persona/view.
 */
function resolvePersona(roles = []) {
  if (roles.includes('sAdmin')) return 'admin';
  if (roles.includes('nAdmin') || roles.includes('vAdmin')) return 'admin';
  if (roles.includes('vCoordinator')) return 'ops';
  if (roles.includes('nCoordinator')) return 'need_coordinator';
  if (roles.includes('Volunteer')) return 'volunteer';
  return 'volunteer';
}

// ─── Dev Bypass User ──────────────────────────────────────────────────────────
const DEV_USER = {
  sub: 'dev-user-00000000-0000-0000-0000-000000000000',
  email: 'dev@localhost',
  preferredUsername: 'dev-contributor',
  name: 'Dev Contributor',
  roles: ['Volunteer', 'nCoordinator', 'vCoordinator', 'sAdmin'],
  agencyId: null,
  agencyType: null,
  rcOsid: null,
};

// ─── Dev Mode Provider (no Keycloak) ──────────────────────────────────────────

function DevAuthProvider({ children }) {
  const [persona, setPersona] = useState(null);
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    // Check for previously selected role
    const savedRole = localStorage.getItem('serve-dev-role');
    if (savedRole) {
      setPersona(savedRole);
      setAuthenticated(true);
    }
  }, []);

  const selectRole = useCallback((role) => {
    setPersona(role);
    setAuthenticated(true);
    localStorage.setItem('serve-dev-role', role);
  }, []);

  const logout = useCallback(() => {
    setPersona(null);
    setAuthenticated(false);
    localStorage.removeItem('serve-dev-role');
  }, []);

  const getToken = useCallback(async () => null, []); // No token in dev mode

  const value = {
    authenticated,
    initializing: false,
    user: authenticated ? DEV_USER : null,
    persona,
    getToken,
    logout,
    keycloak: null,
    // Dev-only helpers
    isDevMode: true,
    selectRole,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ─── Keycloak Provider (production) ───────────────────────────────────────────

function KeycloakAuthProvider({ children }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [user, setUser] = useState(null);
  const [persona, setPersona] = useState(null);
  const refreshIntervalRef = useRef(null);
  const initCalledRef = useRef(false);

  // Lazy-load keycloak only when auth is enabled
  const keycloakRef = useRef(null);
  if (!keycloakRef.current) {
    // Dynamic require so dev mode never loads keycloak-js
    const kc = require('../lib/keycloak').default;
    keycloakRef.current = kc;
  }
  const keycloak = keycloakRef.current;

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
  }, [keycloak]);

  useEffect(() => {
    if (initCalledRef.current) return;
    initCalledRef.current = true;

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

    keycloak.onTokenExpired = () => {
      keycloak.updateToken(MIN_TOKEN_VALIDITY).catch(() => {
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
  }, [keycloak, updateUserFromToken]);

  useEffect(() => {
    if (!authenticated) return;
    refreshIntervalRef.current = setInterval(() => {
      keycloak.updateToken(MIN_TOKEN_VALIDITY).catch(() => {
        keycloak.logout();
      });
    }, TOKEN_REFRESH_INTERVAL);
    return () => clearInterval(refreshIntervalRef.current);
  }, [authenticated, keycloak]);

  const getToken = useCallback(async () => {
    try {
      await keycloak.updateToken(MIN_TOKEN_VALIDITY);
      return keycloak.token;
    } catch {
      keycloak.logout();
      return null;
    }
  }, [keycloak]);

  const logout = useCallback(() => {
    keycloak.logout({ redirectUri: window.location.origin });
  }, [keycloak]);

  const value = {
    authenticated,
    initializing,
    user,
    persona,
    getToken,
    logout,
    keycloak,
    isDevMode: false,
    selectRole: null,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ─── Exported Provider (picks mode automatically) ─────────────────────────────

export function AuthProvider({ children }) {
  if (!AUTH_ENABLED) {
    return <DevAuthProvider>{children}</DevAuthProvider>;
  }
  return <KeycloakAuthProvider>{children}</KeycloakAuthProvider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

export default AuthContext;

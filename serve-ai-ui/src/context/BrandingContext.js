/**
 * BrandingContext — Dynamic tenant branding.
 *
 * Three layers (each overrides the previous):
 *   1. Build-time defaults from env vars
 *   2. Persisted branding from localStorage (from last Context Token)
 *   3. Runtime override from Context Token resolution
 *
 * Components consume branding via useBranding() hook.
 * CSS custom properties are applied to :root for Tailwind/CSS integration.
 */
import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';

// ── Default branding from environment variables ──────────────────────────────

const DEFAULT_BRANDING = {
  appName: process.env.REACT_APP_TENANT_NAME || 'SERVE',
  logoUrl: process.env.REACT_APP_TENANT_LOGO || null,
  primaryColor: process.env.REACT_APP_TENANT_PRIMARY_COLOR || '#2563eb',
  accentColor: process.env.REACT_APP_TENANT_ACCENT_COLOR || '#0891b2',
  tagline: process.env.REACT_APP_TENANT_TAGLINE || 'Volunteer Platform',
  tenant: process.env.REACT_APP_TENANT_ID || 'serve',
};

const BRANDING_STORAGE_KEY = 'serve_branding';

// ── Helpers ──────────────────────────────────────────────────────────────────

function loadPersistedBranding() {
  try {
    const stored = localStorage.getItem(BRANDING_STORAGE_KEY);
    if (stored) {
      return JSON.parse(stored);
    }
  } catch {
    // ignore parse errors
  }
  return null;
}

function persistBranding(branding) {
  try {
    localStorage.setItem(BRANDING_STORAGE_KEY, JSON.stringify(branding));
  } catch {
    // storage full — ignore
  }
}

/**
 * Convert a hex color to HSL values for CSS custom properties.
 * Returns "H S% L%" format compatible with Tailwind's hsl() usage.
 */
function hexToHsl(hex) {
  if (!hex || !hex.startsWith('#')) return null;
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }

  return `${Math.round(h * 360)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
}

/**
 * Apply branding colors to CSS custom properties on :root.
 */
function applyBrandingToCSS(branding) {
  const root = document.documentElement;
  const primaryHsl = hexToHsl(branding.primaryColor);
  const accentHsl = hexToHsl(branding.accentColor);

  if (primaryHsl) {
    root.style.setProperty('--primary', primaryHsl);
    root.style.setProperty('--ring', primaryHsl);
  }
  if (accentHsl) {
    root.style.setProperty('--accent', accentHsl);
  }
}

// ── Context ──────────────────────────────────────────────────────────────────

const BrandingContext = createContext(null);

export function BrandingProvider({ children }) {
  const [branding, setBranding] = useState(() => {
    // Layer 2: persisted overrides layer 1 (defaults)
    const persisted = loadPersistedBranding();
    return { ...DEFAULT_BRANDING, ...(persisted || {}) };
  });

  // Apply CSS custom properties whenever branding changes
  useEffect(() => {
    applyBrandingToCSS(branding);
  }, [branding]);

  /**
   * Update branding from a Context Token resolution.
   * This is Layer 3 — runtime override from the Portal.
   * @param {Object} tokenBranding - { appName, logoUrl, primaryColor, accentColor, tagline, tenant }
   */
  const applyTokenBranding = useCallback((tokenBranding) => {
    if (!tokenBranding || typeof tokenBranding !== 'object') return;

    const merged = {
      ...DEFAULT_BRANDING,
      ...tokenBranding,
    };
    setBranding(merged);
    persistBranding(merged);
  }, []);

  /**
   * Reset to default branding (useful on logout or tenant switch).
   */
  const resetBranding = useCallback(() => {
    localStorage.removeItem(BRANDING_STORAGE_KEY);
    setBranding(DEFAULT_BRANDING);
    applyBrandingToCSS(DEFAULT_BRANDING);
  }, []);

  const value = useMemo(() => ({
    ...branding,
    applyTokenBranding,
    resetBranding,
  }), [branding, applyTokenBranding, resetBranding]);

  return (
    <BrandingContext.Provider value={value}>
      {children}
    </BrandingContext.Provider>
  );
}

/**
 * Hook to consume branding in any component.
 * Returns: { appName, logoUrl, primaryColor, accentColor, tagline, tenant, applyTokenBranding, resetBranding }
 */
export function useBranding() {
  const context = useContext(BrandingContext);
  if (!context) {
    throw new Error('useBranding must be used within a BrandingProvider');
  }
  return context;
}

export default BrandingContext;

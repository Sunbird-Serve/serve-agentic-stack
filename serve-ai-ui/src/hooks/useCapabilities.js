/**
 * useCapabilities — Derives navigation capabilities from user roles.
 * Returns the resolved persona, capabilities array, and filtered nav items.
 */
import { useMemo } from 'react';
import { useAuth } from '../context/AuthContext';
import { resolveCapabilities, hasCapability, NAV_ITEMS } from '../services/capabilities';

export function useCapabilities() {
  const { user } = useAuth();

  return useMemo(() => {
    const roles = user?.roles || [];
    const { persona, capabilities } = resolveCapabilities(roles);

    // Filter nav items to only those the user can access
    const navItems = NAV_ITEMS
      .filter((item) => hasCapability(capabilities, item.requiredCapability))
      .map((item) => {
        if (!item.children) return item;
        return {
          ...item,
          children: item.children.filter((child) =>
            hasCapability(capabilities, child.requiredCapability)
          ),
        };
      });

    return {
      persona,
      capabilities,
      navItems,
      hasCapability: (cap) => hasCapability(capabilities, cap),
    };
  }, [user]);
}

export default useCapabilities;

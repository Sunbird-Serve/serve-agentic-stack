/**
 * SERVE UI — Capability Mapping
 * Maps Keycloak realm roles to application capabilities.
 * Capabilities drive navigation visibility — no hardcoded persona checks in UI.
 */

/**
 * Role → Persona + Capabilities mapping.
 * Priority order matters: first matching role wins for persona assignment.
 * Capabilities are the full set for that role.
 */
export const ROLE_CAPABILITY_MAP = {
  sAdmin: {
    persona: 'Super_Admin',
    capabilities: [
      'conversation:access',
      'operations:access',
      'operations:conversations',
      'operations:pipeline',
      'operations:agents',
      'operations:evaluation',
    ],
  },
  nAdmin: {
    persona: 'Need_Admin',
    capabilities: [
      'conversation:access',
      'operations:access',
      'operations:conversations',
      'operations:pipeline',
    ],
  },
  vAdmin: {
    persona: 'Volunteer_Admin',
    capabilities: [
      'conversation:access',
      'operations:access',
      'operations:conversations',
      'operations:pipeline',
      'operations:agents',
    ],
  },
  vCoordinator: {
    persona: 'Volunteer_Coordinator',
    capabilities: [
      'conversation:access',
      'operations:access',
      'operations:conversations',
      'operations:pipeline',
    ],
  },
  nCoordinator: {
    persona: 'Need_Coordinator',
    capabilities: [
      'conversation:access',
      'operations:access',
      'operations:conversations',
    ],
  },
  Volunteer: {
    persona: 'Volunteer',
    capabilities: ['conversation:access'],
  },
};

/** Priority order for persona resolution when user has multiple roles */
export const ROLE_PRIORITY = [
  'sAdmin',
  'nAdmin',
  'vAdmin',
  'vCoordinator',
  'nCoordinator',
  'Volunteer',
];

/** Default when no recognized role is found */
export const DEFAULT_CAPABILITIES = {
  persona: 'Volunteer',
  capabilities: ['conversation:access'],
};

/**
 * Navigation items — rendered if user has the requiredCapability.
 */
export const NAV_ITEMS = [
  {
    id: 'conversations',
    label: 'Conversations',
    icon: 'MessageSquare',
    path: '/conversations',
    requiredCapability: 'conversation:access',
  },
  {
    id: 'operations',
    label: 'Operations',
    icon: 'Activity',
    path: '/operations',
    requiredCapability: 'operations:access',
    children: [
      {
        id: 'ops-overview',
        label: 'Overview',
        icon: 'Activity',
        path: '/operations/overview',
        requiredCapability: 'operations:access',
      },
      {
        id: 'ops-conversations',
        label: 'Conversations',
        icon: 'MessagesSquare',
        path: '/operations/conversations',
        requiredCapability: 'operations:conversations',
      },
      {
        id: 'ops-pipeline',
        label: 'Pipeline',
        icon: 'TrendingUp',
        path: '/operations/pipeline',
        requiredCapability: 'operations:pipeline',
      },
      {
        id: 'ops-agents',
        label: 'Agents & Tools',
        icon: 'Bot',
        path: '/operations/agents',
        requiredCapability: 'operations:agents',
      },
      {
        id: 'ops-evaluation',
        label: 'Evaluation',
        icon: 'BarChart3',
        path: '/operations/evaluation',
        requiredCapability: 'operations:evaluation',
      },
    ],
  },
];

/**
 * Resolve capabilities from a set of Keycloak realm roles.
 * Returns { persona, capabilities } for the highest-priority matching role.
 */
export function resolveCapabilities(roles = []) {
  for (const role of ROLE_PRIORITY) {
    if (roles.includes(role)) {
      return ROLE_CAPABILITY_MAP[role];
    }
  }
  return DEFAULT_CAPABILITIES;
}

/**
 * Check if a set of capabilities includes a specific capability.
 */
export function hasCapability(capabilities = [], capability) {
  return capabilities.includes(capability);
}

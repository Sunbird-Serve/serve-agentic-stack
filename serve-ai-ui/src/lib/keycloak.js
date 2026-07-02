/**
 * Keycloak Configuration & Initialization
 * Uses keycloak-js with PKCE public client (serve-ui)
 */
import Keycloak from 'keycloak-js';

const keycloakConfig = {
  url: process.env.REACT_APP_KEYCLOAK_URL || 'http://localhost:8080',
  realm: process.env.REACT_APP_KEYCLOAK_REALM || 'sunbird-serve',
  clientId: 'serve-ui',
};

const keycloak = new Keycloak(keycloakConfig);

export default keycloak;

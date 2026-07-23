/**
 * SERVE AI — API Service (Simplified)
 * No Keycloak. Volunteer chat uses guest-interact (no auth).
 * Admin routes use X-Admin-Token header.
 */
import axios from "axios";

const BACKEND_URL =
  process.env.REACT_APP_BACKEND_URL || "http://localhost:8001";
const API = `${BACKEND_URL}/api`;

// Create axios instance
const apiClient = axios.create({
  baseURL: API,
  headers: { "Content-Type": "application/json" },
  timeout: 60000,
});

// Admin token interceptor — attaches token from localStorage if available
apiClient.interceptors.request.use((config) => {
  // Check both admin token keys (volunteer ops + needs ops)
  const token = localStorage.getItem("serve_admin_token") || localStorage.getItem("serve_needs_admin_token");
  if (token) {
    // Send as both X-Admin-Token (new) and Bearer (legacy compatibility)
    config.headers["X-Admin-Token"] = token;
    config.headers["Authorization"] = `Bearer ${token}`;
  }
  return config;
});

// Error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error("API Error:", error.response?.data || error.message);
    return Promise.reject(error);
  }
);

/**
 * Orchestrator API
 */
export const orchestratorApi = {
  // Guest interaction (no auth needed — for volunteer chat)
  guestInteract: async (
    sessionId,
    message,
    guestId = null,
    channel = "web_ui",
    persona = "new_volunteer"
  ) => {
    const payload = {
      message,
      channel,
      persona,
      channel_metadata: { guest_id: guestId },
    };
    if (sessionId) {
      payload.session_id = sessionId;
    }
    const response = await apiClient.post("/orchestrator/guest-interact", payload);
    return response.data;
  },

  // Health check
  health: async () => {
    const response = await apiClient.get("/orchestrator/health");
    return response.data;
  },
};

/**
 * Dashboard API (admin)
 */
export const dashboardApi = {
  getStats: async (page = 1, pageSize = 25) => {
    const params = {};
    if (page !== 1) params.page = page;
    if (pageSize !== 25) params.page_size = pageSize;
    const response = await apiClient.get("/mcp/dashboard/stats", { params });
    return response.data;
  },
  getAnalytics: async () => {
    const response = await apiClient.get("/mcp/dashboard/analytics");
    return response.data;
  },
  getConversation: async (sessionId, limit = 50) => {
    const response = await apiClient.get(
      `/mcp/dashboard/conversation/${sessionId}`,
      { params: { limit } }
    );
    return response.data;
  },
  getSessionDetail: async (sessionId) => {
    const response = await apiClient.get(
      `/mcp/dashboard/session/${sessionId}`
    );
    return response.data;
  },
};

export default { orchestrator: orchestratorApi, dashboard: dashboardApi };

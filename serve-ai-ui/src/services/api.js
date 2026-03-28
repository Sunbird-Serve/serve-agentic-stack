/**
 * SERVE AI - API Service
 * Handles all communication with the backend services
 */
import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Create axios instance with defaults
const apiClient = axios.create({
  baseURL: API,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 60000,
});

// Add response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error.response?.data || error.message);
    return Promise.reject(error);
  }
);

/**
 * Orchestrator API
 */
export const orchestratorApi = {
  // Process a chat interaction
  interact: async (sessionId, message, channel = 'web_ui', persona = 'new_volunteer', channelMetadata = null) => {
    const payload = {
      message,
      channel,
      persona,
    };
    if (sessionId) {
      payload.session_id = sessionId;
    }
    if (channelMetadata) {
      payload.channel_metadata = channelMetadata;
    }
    const response = await apiClient.post('/orchestrator/interact', payload);
    return response.data;
  },

  // Get session state
  getSession: async (sessionId) => {
    const response = await apiClient.get(`/orchestrator/session/${sessionId}`);
    return response.data;
  },

  // List all sessions (for ops view)
  listSessions: async (status = null, limit = 50) => {
    const params = { limit };
    if (status) params.status = status;
    const response = await apiClient.get('/orchestrator/sessions', { params });
    return response.data;
  },

  // Health check
  health: async () => {
    const response = await apiClient.get('/orchestrator/health');
    return response.data;
  },
};

/**
 * MCP Service API
 */
export const mcpApi = {
  // Get full session with profile
  getSession: async (sessionId) => {
    const response = await apiClient.get(`/mcp/capabilities/onboarding/session/${sessionId}`);
    return response.data;
  },

  // Get conversation history
  getConversation: async (sessionId, limit = 50) => {
    const response = await apiClient.post('/mcp/capabilities/onboarding/get-conversation', {
      session_id: sessionId,
      limit,
    });
    return response.data;
  },

  // Get telemetry events
  getTelemetry: async (sessionId, limit = 100) => {
    const response = await apiClient.get(`/mcp/capabilities/onboarding/telemetry/${sessionId}`, {
      params: { limit },
    });
    return response.data;
  },

  // List all sessions
  listSessions: async (status = null, limit = 50) => {
    const params = { limit };
    if (status) params.status = status;
    const response = await apiClient.get('/mcp/capabilities/onboarding/sessions', { params });
    return response.data;
  },

  // Health check
  health: async () => {
    const response = await apiClient.get('/mcp/health');
    return response.data;
  },
};

/**
 * Platform Health API
 */
export const healthApi = {
  // Check all services
  checkAll: async () => {
    const response = await apiClient.get('/health');
    return response.data;
  },
};

/**
 * Tech Dashboard API
 */
export const dashboardApi = {
  getStats: async () => {
    const response = await apiClient.get('/mcp/dashboard/stats');
    return response.data;
  },
  getConversation: async (sessionId, limit = 50) => {
    const response = await apiClient.get(`/mcp/dashboard/conversation/${sessionId}`, {
      params: { limit },
    });
    return response.data;
  },
  getSessionDetail: async (sessionId) => {
    const response = await apiClient.get(`/mcp/dashboard/session/${sessionId}`);
    return response.data;
  },
};

export default {
  orchestrator: orchestratorApi,
  mcp: mcpApi,
  health: healthApi,
};

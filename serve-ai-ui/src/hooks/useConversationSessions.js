/**
 * useConversationSessions — Manages the list of user's conversation sessions.
 * Supports creating new sessions, switching between sessions, and persisting to localStorage.
 */
import { useState, useCallback, useEffect } from 'react';

const SESSIONS_KEY = 'serve_conversation_sessions';
const ACTIVE_SESSION_KEY = 'serve_active_session';

/**
 * Load sessions from localStorage.
 */
function loadSessions() {
  try {
    const stored = localStorage.getItem(SESSIONS_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

/**
 * Save sessions to localStorage.
 */
function saveSessions(sessions) {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
  } catch {
    // storage full — ignore
  }
}

export function useConversationSessions() {
  const [sessions, setSessions] = useState(loadSessions);
  const [activeSessionId, setActiveSessionId] = useState(
    () => localStorage.getItem(ACTIVE_SESSION_KEY) || null
  );

  // Persist sessions to localStorage when they change
  useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

  // Persist active session ID
  useEffect(() => {
    if (activeSessionId) {
      localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionId);
    } else {
      localStorage.removeItem(ACTIVE_SESSION_KEY);
    }
  }, [activeSessionId]);

  /**
   * Get the currently active session object.
   */
  const activeSession = sessions.find((s) => s.id === activeSessionId) || null;

  /**
   * Create a new session (before orchestrator assigns an ID).
   * Returns a temporary local ID. Call updateSessionId() once the orchestrator responds.
   */
  const createSession = useCallback((title = 'New Conversation') => {
    const tempId = `temp-${Date.now()}`;
    const newSession = {
      id: tempId,
      title,
      status: 'active',
      createdAt: new Date().toISOString(),
      lastMessageAt: null,
      lastMessage: null,
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(tempId);
    return tempId;
  }, []);

  /**
   * Update the session ID once the orchestrator creates a real session.
   */
  const updateSessionId = useCallback((tempId, realId) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === tempId ? { ...s, id: realId } : s))
    );
    setActiveSessionId((current) => (current === tempId ? realId : current));
  }, []);

  /**
   * Switch to an existing session.
   */
  const switchSession = useCallback((sessionId) => {
    setActiveSessionId(sessionId);
  }, []);

  /**
   * Update a session's metadata (title, last message, etc.)
   */
  const updateSession = useCallback((sessionId, updates) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === sessionId ? { ...s, ...updates } : s))
    );
  }, []);

  return {
    sessions,
    activeSessionId,
    activeSession,
    createSession,
    updateSessionId,
    switchSession,
    updateSession,
  };
}

export default useConversationSessions;

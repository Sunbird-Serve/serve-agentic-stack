/**
 * useConversation — Manages messages for a single conversation session.
 * Handles sending messages to the orchestrator and receiving responses.
 * Uses a ref for sessionId to avoid stale closure issues.
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { orchestratorApi } from '../services/api';
import { useCapabilities } from './useCapabilities';

export function useConversation(sessionId, onSessionCreated) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const { persona } = useCapabilities();

  // Use a ref to always have the latest sessionId in the sendMessage closure
  const sessionIdRef = useRef(sessionId);
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  // Also keep onSessionCreated in a ref to avoid re-creating sendMessage
  const onSessionCreatedRef = useRef(onSessionCreated);
  useEffect(() => {
    onSessionCreatedRef.current = onSessionCreated;
  }, [onSessionCreated]);

  /**
   * Map the capability persona to the orchestrator persona string.
   */
  const getOrchestratorPersona = useCallback(() => {
    const map = {
      Super_Admin: 'new_volunteer',
      Need_Admin: 'new_volunteer',
      Volunteer_Admin: 'new_volunteer',
      Volunteer_Coordinator: 'new_volunteer',
      Need_Coordinator: 'need_coordinator',
      Volunteer: 'new_volunteer',
    };
    return map[persona] || 'new_volunteer';
  }, [persona]);

  /**
   * Send a user message and receive the assistant response.
   */
  const sendMessage = useCallback(
    async (content) => {
      if (!content.trim() || loading) return;

      // Add user message immediately
      const userMsg = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: content.trim(),
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setLoading(true);

      try {
        // Use the ref value so we always have the latest session ID
        const currentSessionId = sessionIdRef.current;

        const response = await orchestratorApi.interact(
          currentSessionId,
          content.trim(),
          'web_ui',
          getOrchestratorPersona()
        );

        // If we didn't have a session yet, store the new one
        if (!currentSessionId && response.session_id) {
          sessionIdRef.current = response.session_id;
          if (onSessionCreatedRef.current) {
            onSessionCreatedRef.current(response.session_id);
          }
        }

        // Add assistant response
        const assistantMsg = {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: response.assistant_message,
          timestamp: new Date().toISOString(),
          metadata: {
            agent: response.active_agent,
            state: response.state,
          },
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } catch (error) {
        console.error('Failed to send message:', error);
        const errorMsg = {
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: 'I encountered an issue processing your message. Please try again.',
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errorMsg]);
      }

      setLoading(false);
    },
    [loading, getOrchestratorPersona]
  );

  /**
   * Reset messages (for new session)
   */
  const resetMessages = useCallback(() => {
    setMessages([]);
    sessionIdRef.current = null;
  }, []);

  return {
    messages,
    loading,
    sendMessage,
    resetMessages,
    setMessages,
  };
}

export default useConversation;

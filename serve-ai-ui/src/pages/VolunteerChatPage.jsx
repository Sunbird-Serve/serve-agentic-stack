/**
 * VolunteerChatPage — Public volunteer onboarding chat.
 * No login required. Uses guest-interact endpoint.
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { ChatThread } from '../components/conversation/ChatThread';
import { ChatInput } from '../components/conversation/ChatInput';
import { orchestratorApi } from '../services/api';

export function VolunteerChatPage() {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const sessionIdRef = useRef(null);
  const guestIdRef = useRef(
    localStorage.getItem('serve_guest_id') || `guest_${Date.now().toString(36)}`
  );

  // Persist guest ID
  useEffect(() => {
    localStorage.setItem('serve_guest_id', guestIdRef.current);
  }, []);

  const sendMessage = useCallback(async (content) => {
    if (!content.trim() || loading) return;

    const userMsg = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: content.trim(),
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const response = await orchestratorApi.guestInteract(
        sessionIdRef.current,
        content.trim(),
        guestIdRef.current,
        'web_ui',
        'new_volunteer'
      );

      if (response.session_id) {
        sessionIdRef.current = response.session_id;
      }
      if (response.debug_info?.guest_id) {
        guestIdRef.current = response.debug_info.guest_id;
        localStorage.setItem('serve_guest_id', response.debug_info.guest_id);
      }

      // Progress message
      if (response.preliminary_message) {
        setMessages((prev) => [...prev, {
          id: `progress-${Date.now()}`,
          role: 'assistant',
          content: response.preliminary_message,
          timestamp: new Date().toISOString(),
          metadata: { type: 'progress' },
        }]);
      }

      // Assistant message
      setMessages((prev) => [...prev, {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.assistant_message,
        timestamp: new Date().toISOString(),
        metadata: { agent: response.active_agent, state: response.state },
      }]);

      // Auto-continue
      if (response.auto_continue) {
        const followup = await orchestratorApi.guestInteract(
          sessionIdRef.current,
          '__auto_continue__',
          guestIdRef.current
        );
        if (followup.preliminary_message) {
          setMessages((prev) => [...prev, {
            id: `progress-f-${Date.now()}`,
            role: 'assistant',
            content: followup.preliminary_message,
            timestamp: new Date().toISOString(),
          }]);
        }
        if (followup.assistant_message) {
          setMessages((prev) => [...prev, {
            id: `assistant-f-${Date.now()}`,
            role: 'assistant',
            content: followup.assistant_message,
            timestamp: new Date().toISOString(),
          }]);
        }
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      setMessages((prev) => [...prev, {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: 'Something went wrong. Please try again.',
        timestamp: new Date().toISOString(),
      }]);
    }

    setLoading(false);
  }, [loading]);

  return (
    <div className="min-h-screen bg-white flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-100 px-4 py-3 flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-amber-500 flex items-center justify-center">
          <span className="text-white font-bold text-sm">eV</span>
        </div>
        <div>
          <h1 className="text-sm font-semibold text-slate-900">eVidyaloka — Project Serve</h1>
          <p className="text-xs text-slate-500">Volunteer with us to teach children in rural India</p>
        </div>
      </header>

      {/* Chat area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <ChatThread messages={messages} loading={loading} />
        <ChatInput onSend={sendMessage} loading={loading} />
      </div>
    </div>
  );
}

export default VolunteerChatPage;

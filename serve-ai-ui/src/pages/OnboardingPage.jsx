/**
 * OnboardingPage — Public volunteer onboarding (no Keycloak required).
 * Uses guest-interact API endpoint. No auth, no sidebar, clean chat experience.
 * After onboarding completes, prompts the user to sign up.
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { ChatThread } from '../components/conversation/ChatThread';
import { ChatInput } from '../components/conversation/ChatInput';
import { orchestratorApi } from '../services/api';
import { useBranding } from '../context/BrandingContext';
import { MessageSquare } from 'lucide-react';

const GUEST_ID_KEY = 'serve_guest_id';
const GUEST_SESSION_KEY = 'serve_guest_session';

function getOrCreateGuestId() {
  let guestId = localStorage.getItem(GUEST_ID_KEY);
  if (!guestId) {
    guestId = `guest_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    localStorage.setItem(GUEST_ID_KEY, guestId);
  }
  return guestId;
}

export function OnboardingPage() {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(
    () => localStorage.getItem(GUEST_SESSION_KEY) || null
  );
  const [isComplete, setIsComplete] = useState(false);
  const guestIdRef = useRef(getOrCreateGuestId());
  const sessionIdRef = useRef(sessionId);

  // Keep ref in sync
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  // Persist session_id
  useEffect(() => {
    if (sessionId) {
      localStorage.setItem(GUEST_SESSION_KEY, sessionId);
    }
  }, [sessionId]);

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

      // Store session_id from response
      if (response.session_id && !sessionIdRef.current) {
        const newId = response.session_id;
        sessionIdRef.current = newId;
        setSessionId(newId);
      }

      // Update guest_id if server assigned a different one
      if (response.debug_info?.guest_id) {
        guestIdRef.current = response.debug_info.guest_id;
        localStorage.setItem(GUEST_ID_KEY, response.debug_info.guest_id);
      }

      // Add assistant message
      const assistantMsg = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.assistant_message,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Check if onboarding is complete
      if (response.is_complete) {
        setIsComplete(true);
      }
    } catch (error) {
      console.error('Guest interact failed:', error);
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: 'I encountered an issue. Please try again.',
          timestamp: new Date().toISOString(),
        },
      ]);
    }

    setLoading(false);
  }, [loading]);

  const handleSignUp = () => {
    // Redirect to Keycloak login (account was created by the onboarding agent)
    const keycloakUrl = process.env.REACT_APP_KEYCLOAK_URL || 'http://localhost:8080';
    const realm = process.env.REACT_APP_KEYCLOAK_REALM || 'sunbird-serve';
    const redirectUri = `${window.location.origin}/conversations`;
    window.location.href = `${keycloakUrl}/realms/${realm}/protocol/openid-connect/auth?client_id=serve-ui&response_type=code&redirect_uri=${encodeURIComponent(redirectUri)}&scope=openid`;
  };

  const handleStartNew = () => {
    localStorage.removeItem(GUEST_SESSION_KEY);
    setSessionId(null);
    sessionIdRef.current = null;
    setMessages([]);
    setIsComplete(false);
  };

  const { appName, logoUrl, primaryColor } = useBranding();

  return (
    <div className="min-h-screen flex flex-col bg-white">
      {/* Header */}
      <header className="border-b border-slate-200 bg-white sticky top-0 z-50">
        <div className="flex items-center justify-between h-14 px-4 sm:px-6">
          <div className="flex items-center gap-3">
            {logoUrl ? (
              <img src={logoUrl} alt={appName} className="w-8 h-8 rounded-lg object-contain" />
            ) : (
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center"
                style={{ backgroundColor: primaryColor }}
              >
                <span className="text-white font-bold text-sm">
                  {appName?.charAt(0) || 'S'}
                </span>
              </div>
            )}
            <h1 className="text-base font-semibold text-slate-900 tracking-tight">
              {appName}
            </h1>
            <span className="text-sm text-slate-400 hidden sm:inline">
              Volunteer Onboarding
            </span>
          </div>
          {sessionId && (
            <button
              onClick={handleStartNew}
              className="text-xs text-slate-500 hover:text-slate-700 px-3 py-1.5 rounded-md border border-slate-200 hover:bg-slate-50 transition-colors"
            >
              Start Over
            </button>
          )}
        </div>
      </header>

      {/* Chat */}
      <div className="flex-1 flex flex-col max-w-3xl mx-auto w-full">
        {messages.length === 0 && !loading ? (
          <WelcomeState onStart={sendMessage} />
        ) : (
          <>
            <ChatThread messages={messages} loading={loading} />
            {isComplete ? (
              <CompleteState onSignUp={handleSignUp} />
            ) : (
              <ChatInput onSend={sendMessage} loading={loading} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

function WelcomeState({ onStart }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-4">
      <div className="text-center max-w-sm">
        <div className="w-16 h-16 rounded-2xl bg-blue-50 flex items-center justify-center mx-auto mb-4">
          <MessageSquare className="w-8 h-8 text-blue-600" />
        </div>
        <h2 className="text-xl font-semibold text-slate-900 mb-2">
          Become a Volunteer
        </h2>
        <p className="text-sm text-slate-500 mb-6 leading-relaxed">
          Chat with our AI assistant to get started. No account needed — you can sign up later.
        </p>
        <button
          onClick={() => onStart('I want to volunteer')}
          className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          Start Onboarding
        </button>
      </div>
    </div>
  );
}

function CompleteState({ onSignUp }) {
  return (
    <div className="p-4 border-t border-slate-200 bg-slate-50">
      <div className="text-center max-w-sm mx-auto py-4">
        <p className="text-sm text-slate-700 mb-3 font-medium">
          🎉 Registration complete! Sign in to continue your volunteer journey — selection, scheduling, and teaching assignment are next.
        </p>
        <button
          onClick={onSignUp}
          className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          Sign In to Continue
        </button>
      </div>
    </div>
  );
}

export default OnboardingPage;

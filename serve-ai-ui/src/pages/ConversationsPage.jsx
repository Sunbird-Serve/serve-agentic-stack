/**
 * ConversationsPage — The Conversation Workspace.
 * Multi-session chat interface with session list on left and active chat on right.
 * Wired to the existing orchestratorApi.interact endpoint.
 */
import { useCallback, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { SessionList } from '../components/conversation/SessionList';
import { ChatThread } from '../components/conversation/ChatThread';
import { ChatInput } from '../components/conversation/ChatInput';
import { useConversation } from '../hooks/useConversation';
import { useConversationSessions } from '../hooks/useConversationSessions';
import { MessageSquare } from 'lucide-react';

export function ConversationsPage() {
  const { sessionId: urlSessionId } = useParams();
  const {
    sessions,
    activeSessionId,
    activeSession,
    createSession,
    updateSessionId,
    switchSession,
    updateSession,
  } = useConversationSessions();

  // If URL has a sessionId, switch to it
  useEffect(() => {
    if (urlSessionId && urlSessionId !== activeSessionId) {
      switchSession(urlSessionId);
    }
  }, [urlSessionId, activeSessionId, switchSession]);

  // Callback when orchestrator creates a real session
  const handleSessionCreated = useCallback(
    (realSessionId) => {
      if (activeSessionId && activeSessionId.startsWith('temp-')) {
        updateSessionId(activeSessionId, realSessionId);
      }
    },
    [activeSessionId, updateSessionId]
  );

  const { messages, loading, sendMessage, resetMessages } = useConversation(
    activeSessionId?.startsWith('temp-') ? null : activeSessionId,
    handleSessionCreated
  );

  // Handle sending — update session metadata on send
  const handleSend = useCallback(
    (content) => {
      // Update last message preview
      if (activeSessionId) {
        updateSession(activeSessionId, {
          lastMessageAt: new Date().toISOString(),
          lastMessage: content,
        });

        // Set title from first message if still default
        if (activeSession?.title === 'New Conversation') {
          const title = content.length > 40 ? content.slice(0, 40) + '…' : content;
          updateSession(activeSessionId, { title });
        }
      }
      sendMessage(content);
    },
    [activeSessionId, activeSession, sendMessage, updateSession]
  );

  // Handle new session
  const handleNewSession = useCallback(() => {
    createSession('New Conversation');
    resetMessages();
  }, [createSession, resetMessages]);

  // Handle session switch
  const handleSelectSession = useCallback(
    (id) => {
      switchSession(id);
      resetMessages();
    },
    [switchSession, resetMessages]
  );

  return (
    <div className="flex h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Session list — hidden on mobile, shown on desktop */}
      <div className="hidden md:block w-64 flex-shrink-0">
        <SessionList
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
        />
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeSessionId ? (
          <>
            <ChatThread messages={messages} loading={loading} />
            <ChatInput onSend={handleSend} loading={loading} />
          </>
        ) : (
          <EmptyState onNewSession={handleNewSession} />
        )}
      </div>
    </div>
  );
}

function EmptyState({ onNewSession }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-4">
      <div className="text-center max-w-sm">
        <div className="w-16 h-16 rounded-2xl bg-blue-50 flex items-center justify-center mx-auto mb-4">
          <MessageSquare className="w-8 h-8 text-blue-600" />
        </div>
        <h2 className="text-lg font-semibold text-slate-900 mb-2">
          Start a Conversation
        </h2>
        <p className="text-sm text-slate-500 mb-6">
          Chat with SERVE AI agents for volunteer onboarding, need registration, and more.
        </p>
        <button
          onClick={onNewSession}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          New Conversation
        </button>
      </div>
    </div>
  );
}

export default ConversationsPage;

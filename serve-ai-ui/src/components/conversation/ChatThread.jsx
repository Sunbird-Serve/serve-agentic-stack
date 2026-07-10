/**
 * ChatThread — Scrollable message list with auto-scroll to bottom.
 */
import { useRef, useEffect } from 'react';
import { MessageBubble } from './MessageBubble';
import { TypingIndicator } from './TypingIndicator';

export function ChatThread({ messages = [], loading = false }) {
  const bottomRef = useRef(null);

  // Auto-scroll when new messages arrive or loading state changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, loading]);

  if (messages.length === 0 && !loading) {
    return (
      <div className="flex-1 flex items-center justify-center px-4">
        <p className="text-sm text-slate-400 text-center">
          Start a conversation by typing a message below.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4">
      <div className="space-y-4 max-w-3xl mx-auto">
        {messages.map((msg, idx) => (
          <MessageBubble key={msg.id || idx} message={msg} />
        ))}

        {loading && (
          <div className="flex gap-3 mr-auto max-w-[85%]">
            <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center bg-slate-200 text-slate-600">
              <span className="text-xs font-semibold">AI</span>
            </div>
            <div className="px-4 py-2.5 bg-slate-100 rounded-2xl rounded-bl-sm">
              <TypingIndicator />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}

export default ChatThread;

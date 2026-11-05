/**
 * ChatThread — Scrollable message list with auto-scroll to bottom.
 */
import { useRef, useEffect, useMemo } from 'react';
import { MessageBubble } from './MessageBubble';
import { TypingIndicator } from './TypingIndicator';

export function ChatThread({
  messages = [],
  loading = false,
  onStructuredSubmit,
}) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, loading]);

  const latestOpenFormId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const m = messages[i];
      const req = m.metadata?.ui_request;
      // Interactive only: collect fields or present actions. Info-only blocks
      // (e.g. terminal stop with no Got it) are not "open forms".
      if (
        m.role === 'assistant' &&
        req &&
        !m.metadata?.ui_request_submitted &&
        ((req.fields && req.fields.length > 0) ||
          (req.actions && req.actions.length > 0))
      ) {
        return m.id;
      }
    }
    return null;
  }, [messages]);

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
          <MessageBubble
            key={msg.id || idx}
            message={msg}
            onStructuredSubmit={onStructuredSubmit}
            formDisabled={
              loading ||
              (msg.metadata?.ui_request && msg.id !== latestOpenFormId)
            }
          />
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

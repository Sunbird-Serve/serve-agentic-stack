/**
 * MessageBubble — Renders a single message with role-based styling.
 * Supports user and assistant messages with distinct visual treatment.
 */
import { User, Bot } from 'lucide-react';

export function MessageBubble({ message }) {
  const isUser = message.role === 'user';

  return (
    <div
      className={`flex gap-3 max-w-[85%] animate-fade-in ${
        isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'
      }`}
    >
      {/* Avatar */}
      <div
        className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-slate-200 text-slate-600'
        }`}
      >
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      {/* Bubble */}
      <div
        className={`px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? 'bg-blue-600 text-white rounded-2xl rounded-br-sm'
            : 'bg-slate-100 text-slate-800 rounded-2xl rounded-bl-sm'
        }`}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        {message.timestamp && (
          <p
            className={`text-[10px] mt-1.5 ${
              isUser ? 'text-blue-200' : 'text-slate-400'
            }`}
          >
            {new Date(message.timestamp).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </p>
        )}
      </div>
    </div>
  );
}

export default MessageBubble;

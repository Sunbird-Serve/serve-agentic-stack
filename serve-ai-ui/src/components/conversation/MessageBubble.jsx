/**
 * MessageBubble — Renders a single message with role-based styling.
 * Supports user and assistant messages with distinct visual treatment.
 * Parses [VIDEO:url|caption] tags into video players.
 */
import { User, Bot } from 'lucide-react';

const VIDEO_TAG_RE = /\[VIDEO:(.*?)\|(.*?)\]/g;

function renderContent(content) {
  const parts = [];
  let lastIndex = 0;
  let match;

  const regex = new RegExp(VIDEO_TAG_RE);
  while ((match = regex.exec(content)) !== null) {
    // Text before the video tag
    if (match.index > lastIndex) {
      const text = content.slice(lastIndex, match.index).trim();
      if (text) parts.push({ type: 'text', value: text });
    }
    // Video
    parts.push({ type: 'video', url: match[1], caption: match[2] });
    lastIndex = regex.lastIndex;
  }
  // Remaining text after last video tag
  if (lastIndex < content.length) {
    const text = content.slice(lastIndex).trim();
    if (text) parts.push({ type: 'text', value: text });
  }

  if (parts.length === 0) {
    return <p className="whitespace-pre-wrap">{content}</p>;
  }

  return (
    <div className="space-y-2">
      {parts.map((part, i) =>
        part.type === 'text' ? (
          <p key={i} className="whitespace-pre-wrap">{part.value}</p>
        ) : (
          <div key={i} className="rounded-lg overflow-hidden">
            <video
              src={part.url}
              controls
              className="w-full max-w-[300px] rounded-lg"
              preload="metadata"
            />
            {part.caption && (
              <p className="text-xs text-slate-500 mt-1">{part.caption}</p>
            )}
          </div>
        )
      )}
    </div>
  );
}

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
        {renderContent(message.content)}
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

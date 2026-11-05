/**
 * MessageBubble — Renders a single message with role-based styling.
 * Supports user and assistant messages with distinct visual treatment.
 * Parses [VIDEO:url|caption] tags into video players.
 * Renders structured ui_request forms when present on assistant messages.
 */
import { User, Bot } from 'lucide-react';
import { StructuredUiRequest } from './StructuredUiRequest';

const VIDEO_TAG_RE = /\[VIDEO:(.*?)\|(.*?)\]/g;

function renderContent(content) {
  const parts = [];
  let lastIndex = 0;
  let match;

  const regex = new RegExp(VIDEO_TAG_RE);
  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      const text = content.slice(lastIndex, match.index).trim();
      if (text) parts.push({ type: 'text', value: text });
    }
    parts.push({ type: 'video', url: match[1], caption: match[2] });
    lastIndex = regex.lastIndex;
  }
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

export function MessageBubble({ message, onStructuredSubmit, formDisabled = false }) {
  const isUser = message.role === 'user';
  const uiRequest = !isUser ? message.metadata?.ui_request : null;
  const formSubmitted = Boolean(message.metadata?.ui_request_submitted);
  const submittedValues = message.metadata?.form_values || null;

  return (
    <div
      className={`flex gap-3 max-w-[85%] animate-fade-in ${
        isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'
      }`}
    >
      <div
        className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-slate-200 text-slate-600'
        }`}
      >
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      <div
        className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? 'bg-blue-600 text-white rounded-br-sm'
            : 'bg-slate-100 text-slate-800 rounded-bl-sm'
        }`}
      >
        {renderContent(message.content)}

        {uiRequest && (
          <StructuredUiRequest
            uiRequest={uiRequest}
            disabled={formDisabled || formSubmitted}
            submittedValues={submittedValues}
            onSubmit={(values) => onStructuredSubmit?.(uiRequest, values, message.id)}
          />
        )}
      </div>
    </div>
  );
}

export default MessageBubble;

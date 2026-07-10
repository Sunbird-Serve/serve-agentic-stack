/**
 * SessionList — Left panel showing user's conversation sessions.
 * Allows switching between sessions and creating new ones.
 */
import { Plus, MessageSquare } from 'lucide-react';
import { Button } from '../ui/button';
import { cn } from '../../lib/utils';

function formatTime(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'now';
  if (diffMins < 60) return `${diffMins}m`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d`;
}

const STATUS_COLORS = {
  active: 'bg-emerald-500',
  paused: 'bg-amber-400',
  completed: 'bg-slate-400',
  error: 'bg-red-500',
};

export function SessionList({ sessions = [], activeSessionId, onSelectSession, onNewSession }) {
  return (
    <div className="flex flex-col h-full border-r border-slate-200 bg-slate-50">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
        <h3 className="text-sm font-semibold text-slate-700">Sessions</h3>
        <Button
          variant="ghost"
          size="icon"
          onClick={onNewSession}
          className="h-7 w-7 text-slate-500 hover:text-blue-600"
          title="New conversation"
          aria-label="Start new conversation"
        >
          <Plus className="w-4 h-4" />
        </Button>
      </div>

      {/* Session items */}
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <MessageSquare className="w-8 h-8 text-slate-300 mx-auto mb-2" />
            <p className="text-xs text-slate-400">No conversations yet</p>
          </div>
        ) : (
          <div className="py-1">
            {sessions.map((session) => (
              <button
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className={cn(
                  'w-full text-left px-4 py-3 border-b border-slate-100 hover:bg-white transition-colors',
                  activeSessionId === session.id && 'bg-white border-l-2 border-l-blue-600'
                )}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={cn(
                      'w-2 h-2 rounded-full flex-shrink-0',
                      STATUS_COLORS[session.status] || 'bg-slate-400'
                    )}
                  />
                  <span className="text-sm font-medium text-slate-800 truncate flex-1">
                    {session.title || 'Conversation'}
                  </span>
                  <span className="text-[10px] text-slate-400 flex-shrink-0">
                    {formatTime(session.lastMessageAt || session.createdAt)}
                  </span>
                </div>
                {session.lastMessage && (
                  <p className="text-xs text-slate-500 truncate pl-4">
                    {session.lastMessage}
                  </p>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default SessionList;

/**
 * ConversationList — Session list with chat viewer.
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, MessageSquare } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Card, CardContent } from '../../components/ui/card';
import { dashboardApi } from '../../services/api';

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

export function ConversationList() {
  const [sessions, setSessions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [conversation, setConversation] = useState([]);
  const [loading, setLoading] = useState(true);
  const [chatLoading, setChatLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await dashboardApi.getStats(1, 200);
      if (res.status === 'success') {
        setSessions(res.recent_sessions || []);
      }
    } catch (e) {
      console.error('Load failed:', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const viewConversation = async (sessionId) => {
    setSelectedId(sessionId);
    setChatLoading(true);
    try {
      const res = await dashboardApi.getConversation(sessionId, 100);
      setConversation(res.messages || res.conversation || []);
    } catch (e) {
      console.error('Failed to load conversation:', e);
      setConversation([]);
    }
    setChatLoading(false);
  };

  return (
    <div className="p-6 h-screen flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
          <MessageSquare className="w-5 h-5" /> Conversations
        </h1>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      <div className="flex-1 flex flex-col md:flex-row gap-4 overflow-hidden">
        {/* Session list */}
        <Card className="w-full md:w-80 flex-shrink-0 border-none shadow-sm overflow-y-auto max-h-[40vh] md:max-h-none">
          <CardContent className="p-0">
            {sessions.map((s) => (
              <button
                key={s.id}
                onClick={() => viewConversation(s.id)}
                className={`w-full text-left px-4 py-3 border-b border-slate-50 hover:bg-slate-50 transition-colors ${
                  selectedId === s.id ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''
                }`}
              >
                <div className="flex justify-between items-start">
                  <span className="text-sm font-medium text-slate-900 truncate">
                    {s.volunteer_name || s.actor_id?.slice(0, 12) || 'Anonymous'}
                  </span>
                  <span className="text-xs text-slate-400 whitespace-nowrap ml-2">
                    {timeAgo(s.last_message_at)}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs text-slate-500 capitalize">{s.active_agent}</span>
                  <span className="text-xs text-slate-400">·</span>
                  <span className="text-xs text-slate-400">{s.stage}</span>
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        {/* Chat viewer */}
        <Card className="flex-1 border-none shadow-sm overflow-y-auto">
          <CardContent className="p-4">
            {!selectedId ? (
              <div className="flex items-center justify-center h-full text-slate-400 text-sm">
                Select a conversation to view
              </div>
            ) : chatLoading ? (
              <div className="flex items-center justify-center h-full text-slate-400 text-sm">
                Loading...
              </div>
            ) : (
              <div className="space-y-3">
                {conversation.map((msg, i) => (
                  <div
                    key={i}
                    className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${
                        msg.role === 'user'
                          ? 'bg-blue-600 text-white'
                          : 'bg-slate-100 text-slate-800'
                      }`}
                    >
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                      <p className={`text-xs mt-1 ${msg.role === 'user' ? 'text-blue-200' : 'text-slate-400'}`}>
                        {msg.agent && <span className="capitalize">{msg.agent} · </span>}
                        {timeAgo(msg.created_at || msg.timestamp)}
                      </p>
                    </div>
                  </div>
                ))}
                {conversation.length === 0 && (
                  <p className="text-center text-slate-400 text-sm py-8">No messages</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default ConversationList;

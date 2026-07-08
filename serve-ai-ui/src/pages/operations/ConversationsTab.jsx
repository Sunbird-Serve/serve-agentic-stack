/**
 * ConversationsTab — Operations > Conversations monitoring.
 * Session list with filters + session detail panel.
 * Migrated from AdminView with light theme.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw, Search, MessageSquare, ChevronDown,
} from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Input } from '../../components/ui/input';
import { ScrollArea } from '../../components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import { dashboardApi } from '../../services/api';

// ── Helpers ──────────────────────────────────────────────────────────────────

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const fmtTime = (iso) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

const stageBadge = (stage) => (
  <span className="text-[10px] px-2 py-0.5 rounded-full font-medium bg-slate-100 text-slate-700 border border-slate-200">
    {stage || '—'}
  </span>
);

const channelBadge = (ch) => (
  <span className="text-[10px] px-2 py-0.5 rounded-full font-medium bg-blue-50 text-blue-700 border border-blue-200">
    {ch || '—'}
  </span>
);

// ── Session List ─────────────────────────────────────────────────────────────

const SessionsList = ({ sessions, selectedId, onSelect }) => {
  const [search, setSearch] = useState('');
  const [filterStage, setFilterStage] = useState('');
  const [filterChannel, setFilterChannel] = useState('');

  const stages = [...new Set(sessions.map(s => s.stage).filter(Boolean))];
  const channels = [...new Set(sessions.map(s => s.channel).filter(Boolean))];

  const filtered = sessions.filter(s => {
    if (filterStage && s.stage !== filterStage) return false;
    if (filterChannel && s.channel !== filterChannel) return false;
    if (search) {
      const q = search.toLowerCase();
      return (s.actor_id || '').toLowerCase().includes(q) ||
             (s.id || '').toLowerCase().includes(q) ||
             (s.volunteer_name || '').toLowerCase().includes(q);
    }
    return true;
  });

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="p-3 border-b border-slate-200 space-y-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-2 w-3.5 h-3.5 text-slate-400" />
          <Input
            className="pl-7 h-8 text-xs"
            placeholder="Search actor / session ID / name…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-2">
          <select
            className="flex-1 text-xs border border-slate-200 text-slate-600 rounded px-2 py-1.5 bg-white"
            value={filterStage}
            onChange={e => setFilterStage(e.target.value)}
          >
            <option value="">All stages</option>
            {stages.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            className="flex-1 text-xs border border-slate-200 text-slate-600 rounded px-2 py-1.5 bg-white"
            value={filterChannel}
            onChange={e => setFilterChannel(e.target.value)}
          >
            <option value="">All channels</option>
            {channels.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>

      {/* List */}
      <ScrollArea className="flex-1">
        {filtered.length === 0 ? (
          <p className="text-xs text-slate-400 px-4 py-6 text-center">No sessions match</p>
        ) : filtered.map(s => (
          <div
            key={s.id}
            className={`px-3 py-2.5 cursor-pointer border-b border-slate-100 hover:bg-slate-50 transition-colors ${
              selectedId === s.id ? 'bg-blue-50 border-l-2 border-l-blue-600' : ''
            }`}
            onClick={() => onSelect(s.id)}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-mono text-slate-600 truncate flex-1">
                {s.volunteer_name || s.actor_id?.slice(0, 18) || '—'}
              </span>
              {channelBadge(s.channel)}
            </div>
            <div className="flex items-center gap-2">
              {stageBadge(s.stage)}
              <span className="text-[10px] text-slate-400 ml-auto">{timeAgo(s.last_message_at || s.created_at)}</span>
            </div>
          </div>
        ))}
      </ScrollArea>
    </div>
  );
};

// ── Session Detail ───────────────────────────────────────────────────────────

const FieldRow = ({ label, value }) => (
  <div className="flex gap-3 py-1.5 border-b border-slate-100 last:border-0">
    <span className="text-xs text-slate-500 w-36 shrink-0">{label}</span>
    {value != null && value !== '' ? (
      <span className="text-xs text-slate-800 break-all">{String(value)}</span>
    ) : (
      <span className="text-xs text-slate-400 italic">—</span>
    )}
  </div>
);

const CollapsibleJson = ({ label, value }) => {
  const [open, setOpen] = useState(false);
  if (!value) return <FieldRow label={label} value={null} />;
  let display = value;
  try { display = JSON.stringify(typeof value === 'string' ? JSON.parse(value) : value, null, 2); }
  catch { display = String(value); }
  return (
    <div className="py-1.5 border-b border-slate-100 last:border-0">
      <button
        className="flex items-center gap-2 text-xs text-slate-500 hover:text-slate-700 w-full text-left"
        onClick={() => setOpen(o => !o)}
      >
        <span className="w-36 shrink-0">{label}</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
        <span className="text-slate-400">{open ? 'collapse' : 'expand'}</span>
      </button>
      {open && (
        <pre className="mt-2 text-[10px] text-slate-700 bg-slate-50 rounded p-3 overflow-x-auto max-h-48 leading-relaxed border border-slate-200">
          {display}
        </pre>
      )}
    </div>
  );
};

const SessionDetail = ({ sessionId }) => {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    dashboardApi.getSessionDetail(sessionId)
      .then(r => {
        if (r.status === 'success') setDetail(r);
        else setError(r.error || 'Failed to load');
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (!sessionId) return (
    <div className="flex items-center justify-center h-full text-slate-400 text-sm">
      Select a session to inspect
    </div>
  );
  if (loading) return (
    <div className="flex items-center justify-center h-full">
      <RefreshCw className="w-6 h-6 animate-spin text-slate-400" />
    </div>
  );
  if (error) return (
    <div className="flex items-center justify-center h-full text-red-500 text-sm">{error}</div>
  );

  const { session, messages, telemetry } = detail;

  return (
    <div className="flex flex-col h-full">
      {/* Session header */}
      <div className="px-4 py-3 border-b border-slate-200 flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-mono text-slate-600 truncate">{session.id}</p>
          <div className="flex items-center gap-2 mt-1">
            {channelBadge(session.channel)}
            {stageBadge(session.stage)}
            <span className="text-[10px] text-slate-500">{session.persona}</span>
          </div>
        </div>
        <span className="text-[10px] text-slate-400">{timeAgo(session.last_message_at)}</span>
      </div>

      <Tabs defaultValue="conversation" className="flex-1 flex flex-col min-h-0">
        <TabsList className="mx-4 mt-2 shrink-0">
          <TabsTrigger value="conversation" className="text-xs">
            Chat ({messages?.length || 0})
          </TabsTrigger>
          <TabsTrigger value="info" className="text-xs">
            Info
          </TabsTrigger>
          <TabsTrigger value="telemetry" className="text-xs">
            Telemetry ({telemetry?.length || 0})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="conversation" className="flex-1 min-h-0 mt-0">
          <ScrollArea className="h-full px-4 py-3">
            {(!messages || messages.length === 0) ? (
              <p className="text-center text-slate-400 text-sm py-8">No messages yet</p>
            ) : (
              <div className="space-y-3">
                {messages.map((msg, i) => (
                  <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[78%] px-3 py-2 rounded-xl text-sm ${
                      msg.role === 'user'
                        ? 'bg-blue-600 text-white rounded-br-sm'
                        : 'bg-slate-100 text-slate-800 rounded-bl-sm'
                    }`}>
                      {msg.role !== 'user' && msg.agent && (
                        <p className="text-[10px] text-slate-500 mb-1 font-medium">{msg.agent}</p>
                      )}
                      <p className="leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                      <p className={`text-[10px] mt-1 ${msg.role === 'user' ? 'text-blue-200' : 'text-slate-400'}`}>
                        {fmtTime(msg.timestamp)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </TabsContent>

        <TabsContent value="info" className="flex-1 min-h-0 mt-0">
          <ScrollArea className="h-full px-4 py-3">
            <FieldRow label="Session ID" value={session.id} />
            <FieldRow label="Actor ID" value={session.actor_id} />
            <FieldRow label="Channel" value={session.channel} />
            <FieldRow label="Persona" value={session.persona} />
            <FieldRow label="Workflow" value={session.workflow} />
            <FieldRow label="Stage" value={session.stage} />
            <FieldRow label="Status" value={session.status} />
            <FieldRow label="Active Agent" value={session.active_agent} />
            <FieldRow label="Volunteer ID" value={session.volunteer_id} />
            <FieldRow label="Volunteer Name" value={session.volunteer_name} />
            <CollapsibleJson label="Sub State" value={session.sub_state} />
            <CollapsibleJson label="Channel Metadata" value={session.channel_metadata} />
            <FieldRow label="Created" value={session.created_at ? new Date(session.created_at).toLocaleString() : null} />
            <FieldRow label="Updated" value={session.updated_at ? new Date(session.updated_at).toLocaleString() : null} />
          </ScrollArea>
        </TabsContent>

        <TabsContent value="telemetry" className="flex-1 min-h-0 mt-0">
          <ScrollArea className="h-full">
            {(!telemetry || telemetry.length === 0) ? (
              <p className="text-center text-slate-400 text-sm py-8">No telemetry events</p>
            ) : (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="px-3 py-2 text-[10px] text-slate-500 font-medium uppercase">Time</th>
                    <th className="px-3 py-2 text-[10px] text-slate-500 font-medium uppercase">Event</th>
                    <th className="px-3 py-2 text-[10px] text-slate-500 font-medium uppercase">Agent</th>
                    <th className="px-3 py-2 text-[10px] text-slate-500 font-medium uppercase text-right">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {telemetry.map((ev, i) => (
                    <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="px-3 py-2 text-[10px] text-slate-500 font-mono">{fmtTime(ev.timestamp)}</td>
                      <td className="px-3 py-2">
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-700 font-medium">{ev.event_type}</span>
                      </td>
                      <td className="px-3 py-2 text-xs text-slate-600">{ev.agent || ev.source_service || '—'}</td>
                      <td className="px-3 py-2 text-xs text-slate-500 text-right">{ev.duration_ms != null ? `${ev.duration_ms}ms` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  );
};

// ── Main ─────────────────────────────────────────────────────────────────────

export function ConversationsTab() {
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await dashboardApi.getStats(1, 500);
      if (res?.status === 'success') {
        setSessions(res.recent_sessions || []);
      }
    } catch (e) {
      console.error('Conversations load failed:', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [load]);

  return (
    <div className="flex h-[calc(100vh-8rem)]">
      {/* Sessions list */}
      <div className="w-[35%] border-r border-slate-200 flex flex-col">
        <div className="px-3 py-2 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-slate-500" />
            <span className="text-sm font-medium text-slate-700">Sessions</span>
            <span className="text-xs text-slate-400">({sessions.length})</span>
          </div>
          <Button variant="ghost" size="icon" onClick={load} disabled={loading} className="h-7 w-7">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
        <div className="flex-1 min-h-0">
          <SessionsList
            sessions={sessions}
            selectedId={selectedSession}
            onSelect={setSelectedSession}
          />
        </div>
      </div>

      {/* Detail */}
      <div className="flex-1">
        <SessionDetail sessionId={selectedSession} />
      </div>
    </div>
  );
}

export default ConversationsTab;

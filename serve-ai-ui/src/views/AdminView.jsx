/**
 * SERVE AI - Tech Team Dashboard
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  RefreshCw, Activity, Users, MessageSquare, BookOpen,
  CheckCircle, Wifi, WifiOff, Search, ChevronDown, Handshake, UserPlus,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { ScrollArea } from '../components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Input } from '../components/ui/input';
import { dashboardApi, healthApi, orchestratorApi, dashboardAuth } from '../services/api';

// ── DashboardLogin ────────────────────────────────────────────────────────────

const DashboardLogin = ({ onAuthenticated }) => {
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    dashboardAuth.setToken(token.trim());
    try {
      const result = await dashboardApi.getStats();
      if (result?.error === 'Unauthorized') {
        dashboardAuth.clearToken();
        setError('Invalid API key. Please try again.');
      } else {
        onAuthenticated();
      }
    } catch (err) {
      if (err.response?.status === 401) {
        dashboardAuth.clearToken();
        setError('Invalid API key. Please try again.');
      } else {
        // Network error but token saved — let them through
        onAuthenticated();
      }
    }
    setLoading(false);
  };

  return (
    <div className="bg-slate-900 min-h-[calc(100vh-64px)] flex items-center justify-center">
      <div className="bg-slate-800 rounded-xl p-8 w-full max-w-sm shadow-xl">
        <h2 className="text-lg font-semibold text-slate-100 mb-1">Tech Dashboard</h2>
        <p className="text-xs text-slate-500 mb-6">Enter your API key to continue</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            type="password"
            placeholder="API key"
            value={token}
            onChange={e => setToken(e.target.value)}
            className="bg-slate-700 border-slate-600 text-slate-200 placeholder:text-slate-500"
            autoFocus
          />
          {error && <p className="text-xs text-red-400">{error}</p>}
          <Button
            type="submit"
            disabled={!token.trim() || loading}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white"
          >
            {loading ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : null}
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
};

// ── helpers ──────────────────────────────────────────────────────────────────

const fmt = (n) => (n ?? 0).toLocaleString();

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60)   return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const fmtTime = (iso) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

const STAGE_COLOR = {
  initiated:             'bg-slate-700 text-slate-200',
  capturing_phone:       'bg-yellow-900 text-yellow-300',
  resolving_coordinator: 'bg-blue-900 text-blue-300',
  confirming_identity:   'bg-indigo-900 text-indigo-300',
  resolving_school:      'bg-purple-900 text-purple-300',
  drafting_need:         'bg-orange-900 text-orange-300',
  pending_approval:      'bg-amber-900 text-amber-300',
  submitted:             'bg-green-900 text-green-300',
  paused:                'bg-slate-800 text-slate-400',
  init:                  'bg-slate-700 text-slate-300',
};

const NEED_STATUS_COLOR = {
  draft:               'bg-slate-700 text-slate-300',
  pending_approval:    'bg-amber-900 text-amber-300',
  submitted:           'bg-green-900 text-green-300',
  approved:            'bg-emerald-900 text-emerald-300',
  rejected:            'bg-red-900 text-red-300',
  refinement_required: 'bg-orange-900 text-orange-300',
};

const TELEMETRY_COLOR = {
  state_transition: 'bg-blue-900 text-blue-300',
  agent_response:   'bg-green-900 text-green-300',
  error:            'bg-red-900 text-red-300',
  agent_handoff:    'bg-purple-900 text-purple-300',
  llm_call:         'bg-cyan-900 text-cyan-300',
  tool_call:        'bg-teal-900 text-teal-300',
  session_start:    'bg-slate-700 text-slate-300',
  session_end:      'bg-slate-700 text-slate-300',
};

const stageBadge = (stage) => (
  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${STAGE_COLOR[stage] || 'bg-slate-700 text-slate-300'}`}>
    {stage || '—'}
  </span>
);

const channelBadge = (ch) => (
  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 font-medium">{ch || '—'}</span>
);


// ── StatCard ──────────────────────────────────────────────────────────────────

const StatCard = ({ icon: Icon, label, value, sub, color = 'text-slate-100' }) => (
  <Card className="border-none shadow-sm bg-slate-800">
    <CardContent className="pt-5 pb-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-slate-400 mb-1">{label}</p>
          <p className={`text-2xl font-bold ${color}`}>{fmt(value)}</p>
          {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
        </div>
        <div className="p-2 rounded-lg bg-slate-700">
          <Icon className="w-5 h-5 text-slate-400" />
        </div>
      </div>
    </CardContent>
  </Card>
);

// ── AgentHealthStrip ──────────────────────────────────────────────────────────

const AGENTS = [
  { key: 'need',        label: 'Need Agent' },
  { key: 'onboarding',  label: 'Onboarding Agent' },
  { key: 'engagement',  label: 'Engagement Agent' },
];

const AgentHealthStrip = ({ orchestratorHealth }) => {
  // orchestratorHealth comes from /api/health which includes agent registry info
  const agentStatuses = orchestratorHealth?.agents || {};

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <span className="text-xs text-slate-500 font-medium uppercase tracking-wide">Agents</span>
      {AGENTS.map(({ key, label }) => {
        const info = agentStatuses[key];
        const healthy = info?.status === 'healthy' || info?.healthy === true;
        const unknown = !info;
        return (
          <div key={key} className="flex items-center gap-1.5 bg-slate-800 rounded-full px-3 py-1">
            <span className={`w-2 h-2 rounded-full ${unknown ? 'bg-slate-500' : healthy ? 'bg-green-400' : 'bg-red-400'}`} />
            <span className="text-xs text-slate-300">{label}</span>
          </div>
        );
      })}
      <div className="flex items-center gap-1.5 bg-slate-800 rounded-full px-3 py-1">
        <span className={`w-2 h-2 rounded-full ${orchestratorHealth ? 'bg-green-400' : 'bg-red-400'}`} />
        <span className="text-xs text-slate-300">Orchestrator</span>
      </div>
    </div>
  );
};

// ── SessionsList ──────────────────────────────────────────────────────────────

const SessionsList = ({ sessions, selectedId, onSelect, onJumpToSession }) => {
  const [search, setSearch] = useState('');
  const [filterStage, setFilterStage] = useState('');
  const [filterChannel, setFilterChannel] = useState('');

  const stages   = [...new Set(sessions.map(s => s.stage).filter(Boolean))];
  const channels = [...new Set(sessions.map(s => s.channel).filter(Boolean))];

  const filtered = sessions.filter(s => {
    if (filterStage   && s.stage   !== filterStage)   return false;
    if (filterChannel && s.channel !== filterChannel) return false;
    if (search) {
      const q = search.toLowerCase();
      return (s.actor_id || '').toLowerCase().includes(q) ||
             (s.id || '').toLowerCase().includes(q);
    }
    return true;
  });

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="p-3 border-b border-slate-700 space-y-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-2 w-3.5 h-3.5 text-slate-500" />
          <Input
            className="pl-7 h-7 text-xs bg-slate-800 border-slate-700 text-slate-200 placeholder:text-slate-500"
            placeholder="Search actor / session ID…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-2">
          <select
            className="flex-1 text-xs bg-slate-800 border border-slate-700 text-slate-300 rounded px-2 py-1"
            value={filterStage}
            onChange={e => setFilterStage(e.target.value)}
          >
            <option value="">All stages</option>
            {stages.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            className="flex-1 text-xs bg-slate-800 border border-slate-700 text-slate-300 rounded px-2 py-1"
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
          <p className="text-xs text-slate-500 px-4 py-6 text-center">No sessions match</p>
        ) : filtered.map(s => (
          <div
            key={s.id}
            className={`px-3 py-2.5 cursor-pointer border-b border-slate-800 hover:bg-slate-750 transition-colors ${
              selectedId === s.id ? 'bg-slate-700 border-l-2 border-l-blue-500' : ''
            }`}
            onClick={() => onSelect(s.id)}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-mono text-slate-300 truncate flex-1">
                {s.actor_id?.slice(0, 18) || '—'}
              </span>
              {channelBadge(s.channel)}
            </div>
            <div className="flex items-center gap-2">
              {stageBadge(s.stage)}
              <span className="text-[10px] text-slate-500 ml-auto">{timeAgo(s.last_message_at || s.created_at)}</span>
            </div>
          </div>
        ))}
      </ScrollArea>
    </div>
  );
};


// ── SessionDetail ─────────────────────────────────────────────────────────────

const FieldRow = ({ label, value }) => (
  <div className="flex gap-3 py-1.5 border-b border-slate-800 last:border-0">
    <span className="text-xs text-slate-500 w-40 shrink-0">{label}</span>
    {value != null && value !== '' && value !== undefined ? (
      <span className="text-xs text-slate-200 break-all">{String(value)}</span>
    ) : (
      <span className="text-xs text-slate-600 italic">Not captured</span>
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
    <div className="py-1.5 border-b border-slate-800 last:border-0">
      <button
        className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-200 w-full text-left"
        onClick={() => setOpen(o => !o)}
      >
        <span className="w-40 shrink-0 text-slate-500">{label}</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
        <span className="text-slate-600">{open ? 'collapse' : 'expand'}</span>
      </button>
      {open && (
        <pre className="mt-2 text-[10px] text-slate-300 bg-slate-900 rounded p-3 overflow-x-auto max-h-48 leading-relaxed">
          {display}
        </pre>
      )}
    </div>
  );
};

const TelemetryRow = ({ event }) => {
  const [open, setOpen] = useState(false);
  const colorClass = TELEMETRY_COLOR[event.event_type] || 'bg-slate-700 text-slate-300';
  return (
    <>
      <tr
        className="border-b border-slate-800 hover:bg-slate-800 cursor-pointer"
        onClick={() => setOpen(o => !o)}
      >
        <td className="px-3 py-2 text-[10px] text-slate-500 font-mono whitespace-nowrap">{fmtTime(event.timestamp)}</td>
        <td className="px-3 py-2">
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${colorClass}`}>{event.event_type}</span>
        </td>
        <td className="px-3 py-2 text-xs text-slate-400">{event.agent || event.source_service || '—'}</td>
        <td className="px-3 py-2 text-xs text-slate-500 text-right">{event.duration_ms != null ? `${event.duration_ms}ms` : '—'}</td>
      </tr>
      {open && event.data && Object.keys(event.data).length > 0 && (
        <tr className="bg-slate-900">
          <td colSpan={4} className="px-4 py-2">
            <pre className="text-[10px] text-slate-400 overflow-x-auto max-h-32 leading-relaxed">
              {JSON.stringify(event.data, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
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
    <div className="flex items-center justify-center h-full text-slate-600 text-sm">
      Select a session to inspect
    </div>
  );

  if (loading) return (
    <div className="flex items-center justify-center h-full">
      <RefreshCw className="w-6 h-6 animate-spin text-slate-600" />
    </div>
  );

  if (error) return (
    <div className="flex items-center justify-center h-full text-red-400 text-sm">{error}</div>
  );

  const { session, need_draft, messages, telemetry } = detail;

  return (
    <div className="flex flex-col h-full">
      {/* Session header */}
      <div className="px-4 py-3 border-b border-slate-700 flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-mono text-slate-300 truncate">{session.id}</p>
          <div className="flex items-center gap-2 mt-1">
            {channelBadge(session.channel)}
            {stageBadge(session.stage)}
            <span className="text-[10px] text-slate-500">{session.persona}</span>
          </div>
        </div>
        <span className="text-[10px] text-slate-500">{timeAgo(session.last_message_at)}</span>
      </div>

      <Tabs defaultValue="conversation" className="flex-1 flex flex-col min-h-0">
        <TabsList className="mx-4 mt-2 bg-slate-800 shrink-0">
          <TabsTrigger value="conversation" className="text-xs data-[state=active]:bg-slate-700">
            Conversation <span className="ml-1 text-slate-500">({messages.length})</span>
          </TabsTrigger>
          <TabsTrigger value="need" className="text-xs data-[state=active]:bg-slate-700">
            Need Draft
          </TabsTrigger>
          <TabsTrigger value="info" className="text-xs data-[state=active]:bg-slate-700">
            Session Info
          </TabsTrigger>
          <TabsTrigger value="telemetry" className="text-xs data-[state=active]:bg-slate-700">
            Telemetry <span className="ml-1 text-slate-500">({telemetry.length})</span>
          </TabsTrigger>
        </TabsList>

        {/* Tab: Conversation */}
        <TabsContent value="conversation" className="flex-1 min-h-0 mt-0">
          <ScrollArea className="h-full px-4 py-3">
            {messages.length === 0 ? (
              <p className="text-center text-slate-600 text-sm py-8">No messages yet</p>
            ) : (
              <div className="space-y-3">
                {messages.map((msg, i) => (
                  <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[78%] px-3 py-2 rounded-xl text-sm ${
                      msg.role === 'user'
                        ? 'bg-blue-600 text-white rounded-br-sm'
                        : 'bg-slate-700 text-slate-200 rounded-bl-sm'
                    }`}>
                      {msg.role !== 'user' && msg.agent && (
                        <p className="text-[10px] text-slate-400 mb-1 font-medium">{msg.agent}</p>
                      )}
                      <p className="leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                      <p className={`text-[10px] mt-1 ${msg.role === 'user' ? 'text-blue-300' : 'text-slate-500'}`}>
                        {fmtTime(msg.timestamp)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </TabsContent>

        {/* Tab: Need Draft */}
        <TabsContent value="need" className="flex-1 min-h-0 mt-0">
          <ScrollArea className="h-full px-4 py-3">
            {!need_draft ? (
              <p className="text-center text-slate-600 text-sm py-8">No need draft for this session</p>
            ) : (
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${NEED_STATUS_COLOR[need_draft.status] || 'bg-slate-700 text-slate-300'}`}>
                    {need_draft.status}
                  </span>
                  {need_draft.submitted_at && (
                    <span className="text-xs text-slate-500">Submitted {timeAgo(need_draft.submitted_at)}</span>
                  )}
                </div>
                <FieldRow label="Subjects"            value={(need_draft.subjects || []).join(', ') || null} />
                <FieldRow label="Grade Levels"        value={(need_draft.grade_levels || []).join(', ') || null} />
                <FieldRow label="Student Count"       value={need_draft.student_count} />
                <FieldRow label="Schedule Preference" value={need_draft.schedule_preference} />
                <FieldRow label="Start Date"          value={need_draft.start_date} />
                <FieldRow label="Duration (weeks)"    value={need_draft.duration_weeks} />
                <FieldRow label="Coordinator OSID"    value={need_draft.coordinator_osid} />
                <FieldRow label="Entity ID"           value={need_draft.entity_id} />
                <FieldRow label="Serve Need ID"       value={need_draft.serve_need_id} />
                <FieldRow label="Special Requirements" value={need_draft.special_requirements} />
                <FieldRow label="Admin Comments"      value={need_draft.admin_comments} />
                <CollapsibleJson label="Time Slots"   value={need_draft.time_slots} />
                <FieldRow label="Created"             value={need_draft.created_at ? new Date(need_draft.created_at).toLocaleString() : null} />
                <FieldRow label="Updated"             value={need_draft.updated_at ? new Date(need_draft.updated_at).toLocaleString() : null} />
              </div>
            )}
          </ScrollArea>
        </TabsContent>

        {/* Tab: Session Info */}
        <TabsContent value="info" className="flex-1 min-h-0 mt-0">
          <ScrollArea className="h-full px-4 py-3">
            <FieldRow label="Session ID"    value={session.id} />
            <FieldRow label="Actor ID"      value={session.actor_id} />
            <FieldRow label="Identity Type" value={session.identity_type} />
            <FieldRow label="Channel"       value={session.channel} />
            <FieldRow label="Persona"       value={session.persona} />
            <FieldRow label="User Type"     value={session.user_type} />
            <FieldRow label="Workflow"      value={session.workflow} />
            <FieldRow label="Stage"         value={session.stage} />
            <FieldRow label="Status"        value={session.status} />
            <FieldRow label="Active Agent"  value={session.active_agent} />
            <FieldRow label="Volunteer ID"  value={session.volunteer_id} />
            <FieldRow label="Coordinator ID" value={session.coordinator_id} />
            <CollapsibleJson label="Sub State"        value={session.sub_state} />
            <CollapsibleJson label="Channel Metadata" value={session.channel_metadata} />
            <FieldRow label="Created"       value={session.created_at ? new Date(session.created_at).toLocaleString() : null} />
            <FieldRow label="Updated"       value={session.updated_at ? new Date(session.updated_at).toLocaleString() : null} />
            <FieldRow label="Last Message"  value={session.last_message_at ? new Date(session.last_message_at).toLocaleString() : null} />
          </ScrollArea>
        </TabsContent>

        {/* Tab: Telemetry */}
        <TabsContent value="telemetry" className="flex-1 min-h-0 mt-0">
          <ScrollArea className="h-full">
            {telemetry.length === 0 ? (
              <p className="text-center text-slate-600 text-sm py-8">No telemetry events</p>
            ) : (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-slate-700">
                    <th className="px-3 py-2 text-[10px] text-slate-500 font-medium uppercase">Time</th>
                    <th className="px-3 py-2 text-[10px] text-slate-500 font-medium uppercase">Event</th>
                    <th className="px-3 py-2 text-[10px] text-slate-500 font-medium uppercase">Agent</th>
                    <th className="px-3 py-2 text-[10px] text-slate-500 font-medium uppercase text-right">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {telemetry.map((ev, i) => <TelemetryRow key={i} event={ev} />)}
                </tbody>
              </table>
            )}
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  );
};


// ── NeedsTable ────────────────────────────────────────────────────────────────

const NeedsTable = ({ needs, onJumpToSession }) => (
  <Card className="border-none shadow-sm bg-slate-800">
    <CardHeader className="pb-2 pt-4 px-5">
      <CardTitle className="text-sm text-slate-300 flex items-center gap-2">
        <BookOpen className="w-4 h-4" /> Recent Needs
      </CardTitle>
    </CardHeader>
    <CardContent className="px-0 pb-2">
      {needs.length === 0 ? (
        <p className="text-xs text-slate-500 px-5 py-4">No needs raised yet</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">School</th>
                <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Coordinator</th>
                <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Subjects</th>
                <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Grades</th>
                <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Students</th>
                <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Schedule</th>
                <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Status</th>
                <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Submitted</th>
              </tr>
            </thead>
            <tbody>
              {needs.map(n => (
                <tr
                  key={n.id}
                  className="border-b border-slate-700 hover:bg-slate-750 cursor-pointer"
                  onClick={() => onJumpToSession(n.session_id)}
                >
                  <td className="px-4 py-2 text-xs text-slate-300 max-w-[160px] truncate" title={n.school_name || n.entity_id}>
                    {n.school_name || (n.entity_id ? n.entity_id.slice(0, 12) + '…' : '—')}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-400 max-w-[120px] truncate" title={n.coordinator_name}>
                    {n.coordinator_name || '—'}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-300">
                    {(n.subjects || []).join(', ') || '—'}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-400">
                    {(n.grade_levels || []).join(', ') || '—'}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-400">{n.student_count ?? '—'}</td>
                  <td className="px-4 py-2 text-xs text-slate-400">{n.schedule_preference || '—'}</td>
                  <td className="px-4 py-2">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${NEED_STATUS_COLOR[n.status] || 'bg-slate-700 text-slate-300'}`}>
                      {n.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500">{timeAgo(n.submitted_at || n.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </CardContent>
  </Card>
);

// ── EngagementTable (Tech) ─────────────────────────────────────────────────────

const EngagementTable = ({ sessions, onSelect }) => {
  // Filter to engagement/returning_volunteer sessions
  const engSessions = sessions.filter(s =>
    s.workflow === 'returning_volunteer' || s.active_agent === 'engagement'
  );

  // Parse sub_state for each session
  const rows = engSessions.map(s => {
    let outcome = null, continuity = null, volunteerName = s.volunteer_name;
    let volunteerPhone = null, volunteerId = s.volunteer_id, preferenceNotes = null;
    try {
      const ss = s.sub_state ? JSON.parse(s.sub_state) : {};
      continuity      = ss.continuity || ss.handoff?.continuity;
      preferenceNotes = ss.preference_notes || ss.handoff?.preference_notes;
      volunteerName   = ss.engagement_context?.volunteer_name || ss.handoff?.volunteer_name || volunteerName;
      volunteerPhone  = ss.engagement_context?.volunteer_phone || ss.handoff?.volunteer_phone;
      volunteerId     = ss.engagement_context?.volunteer_id || ss.handoff?.volunteer_id || volunteerId;
      if (ss.deferred) outcome = 'deferred';
      else if (ss.human_review_reason === 'volunteer_declined') outcome = 'declined';
      else if (ss.handoff?.volunteer_id) outcome = 'ready';
    } catch (_) {}
    const deferredReason = (() => {
      try {
        const ss = s.sub_state ? JSON.parse(s.sub_state) : {};
        return ss.deferred_reason || ss.human_review_reason?.replace(/_/g, ' ') || null;
      } catch (_) { return null; }
    })();
    return { ...s, outcome, continuity, volunteerName, volunteerPhone, volunteerId, preferenceNotes, deferredReason };
  });

  const consentLabel = (o) => {
    if (o === 'ready') return <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-900/40 text-green-400 font-medium">Yes</span>;
    if (o === 'declined') return <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/40 text-red-400 font-medium">No</span>;
    if (o === 'deferred') return <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-400 font-medium">Later</span>;
    return <span className="text-[10px] text-slate-500">—</span>;
  };

  return (
    <Card className="border-none shadow-sm bg-slate-800">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-300 flex items-center gap-2">
          <Users className="w-4 h-4" /> Engagement Sessions
          <span className="text-slate-600 font-normal text-xs ml-1">({rows.length})</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-2">
        {rows.length === 0 ? (
          <p className="text-xs text-slate-500 px-5 py-4">No engagement sessions yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Volunteer ID</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Name</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Phone</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Consent</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Preference</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Reason</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Stage</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(s => (
                  <tr
                    key={s.id}
                    className="border-b border-slate-700 hover:bg-slate-750 cursor-pointer"
                    onClick={() => onSelect(s.id)}
                  >
                    <td className="px-4 py-2 text-xs text-slate-400 font-mono">{s.volunteerId?.slice(0, 12) || '—'}</td>
                    <td className="px-4 py-2 text-xs text-slate-300">{s.volunteerName || '—'}</td>
                    <td className="px-4 py-2 text-xs text-slate-400">{s.volunteerPhone || '—'}</td>
                    <td className="px-4 py-2">{consentLabel(s.outcome)}</td>
                    <td className="px-4 py-2 text-xs text-slate-400 max-w-[180px] truncate" title={s.preferenceNotes || ''}>
                      {s.preferenceNotes || (s.continuity ? `Continuity: ${s.continuity}` : '—')}
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-400 max-w-[140px] truncate" title={s.deferredReason || ''}>
                      {s.deferredReason || '—'}
                    </td>
                    <td className="px-4 py-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                        s.stage === 're_engaging' ? 'bg-blue-900/40 text-blue-400' :
                        s.stage === 'human_review' ? 'bg-orange-900/40 text-orange-400' :
                        s.stage === 'paused' ? 'bg-slate-700 text-slate-400' :
                        s.stage === 'active' ? 'bg-green-900/40 text-green-400' :
                        'bg-slate-700 text-slate-300'
                      }`}>{s.stage}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-500">{timeAgo(s.last_message_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

// ── FulfillmentTable (Tech) ────────────────────────────────────────────────────

const FulfillmentTable = ({ sessions, onSelect }) => {
  const fulSessions = sessions.filter(s => s.active_agent === 'fulfillment');

  const rows = fulSessions.map(s => {
    let nominatedNeedId = null, volunteerName = s.volunteer_name;
    let volunteerId = s.volunteer_id, volunteerPhone = null;
    let preferenceNotes = null, candidateNames = [], matchStatus = null;
    try {
      const ss = s.sub_state ? JSON.parse(s.sub_state) : {};
      nominatedNeedId = ss.nominated_need_id;
      matchStatus     = ss.match_result?.status;
      volunteerName   = ss.handoff?.volunteer_name || volunteerName;
      volunteerId     = ss.handoff?.volunteer_id || volunteerId;
      preferenceNotes = ss.handoff?.preference_notes;
      volunteerPhone  = ss.engagement_context?.volunteer_phone;
      const candidates = ss.match_result?.candidates || [];
      candidateNames = candidates.map(c => c.name || c.school_name || c.id?.slice(0, 10) || '?');
    } catch (_) {}
    return { ...s, nominatedNeedId, matchStatus, volunteerName, volunteerId, volunteerPhone, preferenceNotes, candidateNames };
  });

  return (
    <Card className="border-none shadow-sm bg-slate-800">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-300 flex items-center gap-2">
          <Handshake className="w-4 h-4" /> Fulfillment Sessions
          <span className="text-slate-600 font-normal text-xs ml-1">({rows.length})</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-2">
        {rows.length === 0 ? (
          <p className="text-xs text-slate-500 px-5 py-4">No fulfillment sessions yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Volunteer ID</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Name</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Phone</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Preference</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Needs Shown</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Nominated Need</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Stage</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(s => (
                  <tr
                    key={s.id}
                    className="border-b border-slate-700 hover:bg-slate-750 cursor-pointer"
                    onClick={() => onSelect(s.id)}
                  >
                    <td className="px-4 py-2 text-xs text-slate-400 font-mono">{s.volunteerId?.slice(0, 12) || '—'}</td>
                    <td className="px-4 py-2 text-xs text-slate-300">{s.volunteerName || '—'}</td>
                    <td className="px-4 py-2 text-xs text-slate-400">{s.volunteerPhone || '—'}</td>
                    <td className="px-4 py-2 text-xs text-slate-400 max-w-[150px] truncate" title={s.preferenceNotes || ''}>
                      {s.preferenceNotes || '—'}
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-400 max-w-[150px] truncate" title={s.candidateNames.join(', ')}>
                      {s.candidateNames.length > 0 ? s.candidateNames.join(', ') : (s.matchStatus === 'not_found' ? 'No match' : '—')}
                    </td>
                    <td className="px-4 py-2">
                      {s.nominatedNeedId
                        ? <span className="text-xs font-mono text-green-400" title={s.nominatedNeedId}>{s.nominatedNeedId.slice(0, 12)}…</span>
                        : <span className="text-xs text-slate-500">—</span>
                      }
                    </td>
                    <td className="px-4 py-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                        s.stage === 'active' ? 'bg-blue-900/40 text-blue-400' :
                        s.stage === 'complete' ? 'bg-green-900/40 text-green-400' :
                        s.stage === 'human_review' ? 'bg-orange-900/40 text-orange-400' :
                        'bg-slate-700 text-slate-400'
                      }`}>{s.stage}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-500">{timeAgo(s.last_message_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

// ── RecommendedTable (Tech) ─────────────────────────────────────────────────

const RECOMMENDED_STAGE_COLOR = {
  verifying_identity:      'bg-indigo-900/40 text-indigo-400',
  gathering_preferences:   'bg-yellow-900/40 text-yellow-400',
  active:                  'bg-green-900/40 text-green-400',
  not_registered:          'bg-red-900/40 text-red-400',
  human_review:            'bg-orange-900/40 text-orange-400',
  paused:                  'bg-slate-700 text-slate-400',
};

const RecommendedTable = ({ sessions, onSelect }) => {
  const recSessions = sessions.filter(s => s.workflow === 'recommended_volunteer');

  const rows = recSessions.map(s => {
    let volunteerName = s.volunteer_name, volunteerId = s.volunteer_id;
    let volunteerPhone = null, identityStatus = null, preferenceNotes = null;
    try {
      const ss = s.sub_state ? JSON.parse(s.sub_state) : {};
      identityStatus  = ss.identity_verified === true ? 'verified'
                       : ss.identity_verified === false ? 'not_registered'
                       : 'pending';
      preferenceNotes = ss.preference_notes;
      volunteerName   = ss.engagement_context?.volunteer_name || volunteerName;
      volunteerId     = ss.engagement_context?.volunteer_id || volunteerId;
      volunteerPhone  = ss.engagement_context?.volunteer_phone;
      if (!volunteerPhone) {
        try {
          const cm = typeof s.channel_metadata === 'string' ? JSON.parse(s.channel_metadata) : (s.channel_metadata || {});
          volunteerPhone = cm.volunteer_phone;
        } catch (_) {}
      }
    } catch (_) {}
    return { ...s, volunteerName, volunteerId, volunteerPhone, identityStatus, preferenceNotes };
  });

  const identityBadge = (status) => {
    if (status === 'verified') return <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-900/40 text-green-400 font-medium">Verified</span>;
    if (status === 'not_registered') return <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/40 text-red-400 font-medium">Not Registered</span>;
    return <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400 font-medium">Pending</span>;
  };

  return (
    <Card className="border-none shadow-sm bg-slate-800">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-300 flex items-center gap-2">
          <UserPlus className="w-4 h-4" /> Recommended Volunteers
          <span className="text-slate-600 font-normal text-xs ml-1">({rows.length})</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-2">
        {rows.length === 0 ? (
          <p className="text-xs text-slate-500 px-5 py-4">No recommended volunteer sessions yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Volunteer ID</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Name</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Phone</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Identity Status</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Preference</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Stage</th>
                  <th className="px-4 py-2 text-[10px] text-slate-500 font-medium uppercase">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(s => (
                  <tr
                    key={s.id}
                    className="border-b border-slate-700 hover:bg-slate-750 cursor-pointer"
                    onClick={() => onSelect(s.id)}
                  >
                    <td className="px-4 py-2 text-xs text-slate-400 font-mono">{s.volunteerId?.slice(0, 12) || '—'}</td>
                    <td className="px-4 py-2 text-xs text-slate-300">{s.volunteerName || '—'}</td>
                    <td className="px-4 py-2 text-xs text-slate-400">{s.volunteerPhone || '—'}</td>
                    <td className="px-4 py-2">{identityBadge(s.identityStatus)}</td>
                    <td className="px-4 py-2 text-xs text-slate-400 max-w-[180px] truncate" title={s.preferenceNotes || ''}>
                      {s.preferenceNotes || '—'}
                    </td>
                    <td className="px-4 py-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                        RECOMMENDED_STAGE_COLOR[s.stage] || 'bg-slate-700 text-slate-300'
                      }`}>{s.stage || '—'}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-500">{timeAgo(s.last_message_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

// ── Pagination Controls ─────────────────────────────────────────────────────

const PaginationControls = ({ page, totalPages, onPageChange }) => {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-3 py-2">
      <Button
        variant="outline"
        size="sm"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        className="bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700 text-xs h-7 px-3"
      >
        Previous
      </Button>
      <span className="text-xs text-slate-400">
        Page {page} of {totalPages}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
        className="bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700 text-xs h-7 px-3"
      >
        Next
      </Button>
    </div>
  );
};

// ── AdminView (main) ──────────────────────────────────────────────────────────

export const AdminView = () => {
  const [authed, setAuthed] = useState(dashboardAuth.isAuthenticated());
  const [data, setData]             = useState(null);
  const [health, setHealth]         = useState(null);
  const [loading, setLoading]       = useState(true);
  const [selectedSession, setSelectedSession] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [secondsAgo, setSecondsAgo] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [sessionsPagination, setSessionsPagination] = useState(null);
  const timerRef = useRef(null);

  const load = useCallback(async (page = currentPage) => {
    setLoading(true);
    try {
      const [stats, h] = await Promise.all([
        dashboardApi.getStats(page, 25),
        orchestratorApi.health().catch(() => null),
      ]);
      if (stats.status === 'success') {
        setData(stats);
        setSessionsPagination(stats.sessions_pagination || null);
      }
      setHealth(h);
      setLastRefresh(new Date());
      setSecondsAgo(0);
    } catch (e) {
      console.error('Dashboard load failed', e);
    }
    setLoading(false);
  }, [currentPage]);

  useEffect(() => {
    load();
    const refresh = setInterval(() => load(), 30000);
    return () => clearInterval(refresh);
  }, [load]);

  // Tick "X seconds ago" counter
  useEffect(() => {
    timerRef.current = setInterval(() => setSecondsAgo(s => s + 1), 1000);
    return () => clearInterval(timerRef.current);
  }, []);

  const handlePageChange = (newPage) => {
    setCurrentPage(newPage);
    load(newPage);
  };

  const stats    = data?.stats;
  const sessions = data?.recent_sessions || [];
  const needs    = data?.recent_needs    || [];

  if (!authed) {
    return <DashboardLogin onAuthenticated={() => setAuthed(true)} />;
  }

  const handleSignOut = () => {
    dashboardAuth.clearToken();
    setAuthed(false);
  };

  const handleJumpToSession = (sessionId) => {
    setSelectedSession(sessionId);
    // Scroll to top of sessions list if needed
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div className="bg-slate-900 min-h-[calc(100vh-64px)] text-slate-100">
      <div className="p-5 max-w-[1600px] mx-auto space-y-4">

        {/* ── Header ── */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Tech Dashboard</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {lastRefresh
                ? `Updated ${secondsAgo}s ago`
                : 'Loading…'}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <AgentHealthStrip orchestratorHealth={health} />
            <div className="flex items-center gap-1.5 bg-slate-800 rounded-full px-3 py-1">
              {health
                ? <><Wifi className="w-3 h-3 text-green-400" /><span className="text-xs text-green-400">Online</span></>
                : <><WifiOff className="w-3 h-3 text-red-400" /><span className="text-xs text-red-400">Offline</span></>
              }
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={load}
              disabled={loading}
              className="bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
            >
              <RefreshCw className={`w-4 h-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleSignOut}
              className="bg-slate-800 border-slate-700 text-slate-500 hover:bg-slate-700 hover:text-slate-300"
            >
              Sign out
            </Button>
          </div>
        </div>

        {loading && !data ? (
          <div className="flex items-center justify-center py-24">
            <RefreshCw className="w-8 h-8 animate-spin text-slate-600" />
          </div>
        ) : (
          <>
            {/* ── Stat cards ── */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <StatCard icon={Users}       label="Total Sessions"  value={stats?.sessions?.total}     sub={`${fmt(stats?.sessions?.today)} today`} />
              <StatCard icon={Activity}    label="Active Now"      value={stats?.sessions?.active}    color="text-green-400" />
              <StatCard icon={BookOpen}    label="Needs Raised"    value={stats?.needs?.total}        sub={`${fmt(stats?.needs?.submitted)} submitted`} />
              <StatCard icon={CheckCircle} label="This Week"       value={stats?.sessions?.this_week} sub="new sessions" color="text-blue-400" />
            </div>

            {/* ── Sessions + Detail ── */}
            <div className="grid grid-cols-1 lg:grid-cols-[35%_65%] gap-3" style={{ height: '60vh' }}>
              {/* Sessions list */}
              <Card className="border-none shadow-sm bg-slate-800 flex flex-col overflow-hidden">
                <CardHeader className="pb-2 pt-3 px-3 shrink-0">
                  <CardTitle className="text-sm text-slate-300 flex items-center gap-2">
                    <MessageSquare className="w-4 h-4" />
                    Sessions
                    <span className="text-slate-600 font-normal text-xs ml-1">
                      ({sessionsPagination ? sessionsPagination.total_count : sessions.length})
                    </span>
                  </CardTitle>
                </CardHeader>
                <div className="flex-1 min-h-0">
                  <SessionsList
                    sessions={sessions}
                    selectedId={selectedSession}
                    onSelect={setSelectedSession}
                    onJumpToSession={handleJumpToSession}
                  />
                </div>
                {sessionsPagination && (
                  <PaginationControls
                    page={sessionsPagination.page}
                    totalPages={sessionsPagination.total_pages}
                    onPageChange={handlePageChange}
                  />
                )}
              </Card>

              {/* Session detail */}
              <Card className="border-none shadow-sm bg-slate-800 flex flex-col overflow-hidden">
                <SessionDetail sessionId={selectedSession} />
              </Card>
            </div>

            {/* ── Needs table ── */}
            <NeedsTable needs={needs} onJumpToSession={handleJumpToSession} />

            {/* ── Engagement table ── */}
            <EngagementTable sessions={sessions} onSelect={handleJumpToSession} />

            {/* ── Fulfillment table ── */}
            <FulfillmentTable sessions={sessions} onSelect={handleJumpToSession} />

            {/* ── Recommended Volunteers table ── */}
            <RecommendedTable sessions={sessions} onSelect={handleJumpToSession} />
          </>
        )}
      </div>
    </div>
  );
};

export default AdminView;

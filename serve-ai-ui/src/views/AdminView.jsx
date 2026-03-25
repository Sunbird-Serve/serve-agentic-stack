/**
 * SERVE AI - Tech Team Dashboard
 */
import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw, Activity, Users, MessageSquare, BookOpen,
  CheckCircle, Clock, Wifi, WifiOff, ChevronRight, X,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { ScrollArea } from '../components/ui/scroll-area';
import { dashboardApi, healthApi } from '../services/api';

// ── helpers ──────────────────────────────────────────────────────────────────

const fmt = (n) => (n ?? 0).toLocaleString();

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60)  return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const STAGE_COLOR = {
  initiated:              'bg-slate-100 text-slate-600',
  capturing_phone:        'bg-yellow-100 text-yellow-700',
  resolving_coordinator:  'bg-blue-100 text-blue-700',
  confirming_identity:    'bg-indigo-100 text-indigo-700',
  resolving_school:       'bg-purple-100 text-purple-700',
  drafting_need:          'bg-orange-100 text-orange-700',
  pending_approval:       'bg-amber-100 text-amber-700',
  submitted:              'bg-green-100 text-green-700',
  paused:                 'bg-slate-100 text-slate-500',
};

const NEED_STATUS_COLOR = {
  draft:              'bg-slate-100 text-slate-600',
  pending_approval:   'bg-amber-100 text-amber-700',
  submitted:          'bg-green-100 text-green-700',
  approved:           'bg-emerald-100 text-emerald-700',
  rejected:           'bg-red-100 text-red-700',
  refinement_required:'bg-orange-100 text-orange-700',
};

// ── sub-components ────────────────────────────────────────────────────────────

const StatCard = ({ icon: Icon, label, value, sub, color = 'text-slate-700' }) => (
  <Card className="border-none shadow-sm">
    <CardContent className="pt-5 pb-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-slate-500 mb-1">{label}</p>
          <p className={`text-2xl font-bold ${color}`}>{fmt(value)}</p>
          {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
        </div>
        <div className="p-2 rounded-lg bg-slate-50">
          <Icon className="w-5 h-5 text-slate-400" />
        </div>
      </div>
    </CardContent>
  </Card>
);

const BarChart = ({ data, title }) => {
  const max = Math.max(...Object.values(data), 1);
  return (
    <div>
      <p className="text-xs font-medium text-slate-500 mb-3 uppercase tracking-wide">{title}</p>
      <div className="space-y-2">
        {Object.entries(data).map(([key, val]) => (
          <div key={key} className="flex items-center gap-2">
            <span className="text-xs text-slate-500 w-32 truncate">{key}</span>
            <div className="flex-1 bg-slate-100 rounded-full h-2">
              <div
                className="bg-blue-400 h-2 rounded-full transition-all"
                style={{ width: `${(val / max) * 100}%` }}
              />
            </div>
            <span className="text-xs font-medium text-slate-700 w-6 text-right">{val}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

const ConversationPanel = ({ sessionId, onClose }) => {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    dashboardApi.getConversation(sessionId)
      .then(r => setMessages(r.messages || []))
      .catch(() => setMessages([]))
      .finally(() => setLoading(false));
  }, [sessionId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 flex flex-col max-h-[80vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div>
            <p className="font-semibold text-slate-800">Conversation</p>
            <p className="text-xs text-slate-400 font-mono">{sessionId.slice(0, 16)}…</p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}><X className="w-4 h-4" /></Button>
        </div>
        <ScrollArea className="flex-1 px-4 py-3">
          {loading ? (
            <div className="flex justify-center py-8"><RefreshCw className="w-5 h-5 animate-spin text-slate-300" /></div>
          ) : messages.length === 0 ? (
            <p className="text-center text-slate-400 text-sm py-8">No messages yet</p>
          ) : (
            <div className="space-y-3">
              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] px-3 py-2 rounded-xl text-sm ${
                    msg.role === 'user'
                      ? 'bg-blue-500 text-white rounded-br-sm'
                      : 'bg-slate-100 text-slate-800 rounded-bl-sm'
                  }`}>
                    <p>{msg.content}</p>
                    <p className={`text-[10px] mt-1 ${msg.role === 'user' ? 'text-blue-200' : 'text-slate-400'}`}>
                      {timeAgo(msg.timestamp)}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  );
};

// ── main view ─────────────────────────────────────────────────────────────────

export const AdminView = () => {
  const [data, setData]           = useState(null);
  const [health, setHealth]       = useState(null);
  const [loading, setLoading]     = useState(true);
  const [activeConv, setActiveConv] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [stats, h] = await Promise.all([
        dashboardApi.getStats(),
        healthApi.checkAll().catch(() => null),
      ]);
      if (stats.status === 'success') setData(stats);
      setHealth(h);
      setLastRefresh(new Date());
    } catch (e) {
      console.error('Dashboard load failed', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const stats    = data?.stats;
  const sessions = data?.recent_sessions || [];
  const needs    = data?.recent_needs    || [];

  return (
    <div className="p-6 bg-slate-50 min-h-[calc(100vh-64px)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Tech Dashboard</h2>
          <p className="text-xs text-slate-400 mt-0.5">
            {lastRefresh ? `Updated ${timeAgo(lastRefresh.toISOString())}` : 'Loading…'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge className={health?.status === 'healthy' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}>
            {health?.status === 'healthy'
              ? <><Wifi className="w-3 h-3 mr-1" />Healthy</>
              : <><WifiOff className="w-3 h-3 mr-1" />{health?.status || 'Unknown'}</>
            }
          </Badge>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`w-4 h-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {loading && !data ? (
        <div className="flex items-center justify-center py-24">
          <RefreshCw className="w-8 h-8 animate-spin text-slate-300" />
        </div>
      ) : (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <StatCard icon={Users}        label="Total Sessions"   value={stats?.sessions?.total}    sub={`${fmt(stats?.sessions?.today)} today`} />
            <StatCard icon={Activity}     label="Active Now"       value={stats?.sessions?.active}   color="text-green-600" />
            <StatCard icon={BookOpen}     label="Needs Raised"     value={stats?.needs?.total}       sub={`${fmt(stats?.needs?.submitted)} submitted`} />
            <StatCard icon={CheckCircle}  label="This Week"        value={stats?.sessions?.this_week} sub="new sessions" color="text-blue-600" />
          </div>

          {/* Charts row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
            <Card className="border-none shadow-sm">
              <CardHeader className="pb-2 pt-4 px-5">
                <CardTitle className="text-sm text-slate-600">Sessions by Channel</CardTitle>
              </CardHeader>
              <CardContent className="px-5 pb-5">
                {stats?.sessions?.by_channel && Object.keys(stats.sessions.by_channel).length > 0
                  ? <BarChart data={stats.sessions.by_channel} title="" />
                  : <p className="text-xs text-slate-400">No data</p>
                }
              </CardContent>
            </Card>

            <Card className="border-none shadow-sm">
              <CardHeader className="pb-2 pt-4 px-5">
                <CardTitle className="text-sm text-slate-600">Sessions by Stage</CardTitle>
              </CardHeader>
              <CardContent className="px-5 pb-5">
                {stats?.sessions?.by_stage && Object.keys(stats.sessions.by_stage).length > 0
                  ? <BarChart data={stats.sessions.by_stage} title="" />
                  : <p className="text-xs text-slate-400">No data</p>
                }
              </CardContent>
            </Card>

            <Card className="border-none shadow-sm">
              <CardHeader className="pb-2 pt-4 px-5">
                <CardTitle className="text-sm text-slate-600">Needs by Status</CardTitle>
              </CardHeader>
              <CardContent className="px-5 pb-5">
                {stats?.needs?.by_status && Object.keys(stats.needs.by_status).length > 0
                  ? <BarChart data={stats.needs.by_status} title="" />
                  : <p className="text-xs text-slate-400">No data</p>
                }
              </CardContent>
            </Card>
          </div>

          {/* Tables row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Recent sessions */}
            <Card className="border-none shadow-sm">
              <CardHeader className="pb-2 pt-4 px-5">
                <CardTitle className="text-sm text-slate-600 flex items-center gap-2">
                  <MessageSquare className="w-4 h-4" /> Recent Sessions
                </CardTitle>
              </CardHeader>
              <CardContent className="px-0 pb-2">
                <ScrollArea className="h-72">
                  {sessions.length === 0 ? (
                    <p className="text-xs text-slate-400 px-5 py-4">No sessions yet</p>
                  ) : sessions.map((s) => (
                    <div
                      key={s.id}
                      className="flex items-center gap-3 px-5 py-2.5 hover:bg-slate-50 cursor-pointer group"
                      onClick={() => setActiveConv(s.id)}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono text-slate-400 truncate">{s.actor_id?.slice(0, 14) || '—'}</span>
                          <Badge className={`text-[10px] px-1.5 py-0 ${STAGE_COLOR[s.stage] || 'bg-slate-100 text-slate-500'}`}>
                            {s.stage}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-[10px] text-slate-400">{s.channel}</span>
                          <span className="text-[10px] text-slate-300">·</span>
                          <span className="text-[10px] text-slate-400">{timeAgo(s.last_message_at || s.created_at)}</span>
                        </div>
                      </div>
                      <ChevronRight className="w-3 h-3 text-slate-300 group-hover:text-slate-500" />
                    </div>
                  ))}
                </ScrollArea>
              </CardContent>
            </Card>

            {/* Recent needs */}
            <Card className="border-none shadow-sm">
              <CardHeader className="pb-2 pt-4 px-5">
                <CardTitle className="text-sm text-slate-600 flex items-center gap-2">
                  <BookOpen className="w-4 h-4" /> Recent Needs
                </CardTitle>
              </CardHeader>
              <CardContent className="px-0 pb-2">
                <ScrollArea className="h-72">
                  {needs.length === 0 ? (
                    <p className="text-xs text-slate-400 px-5 py-4">No needs raised yet</p>
                  ) : needs.map((n) => (
                    <div key={n.id} className="px-5 py-2.5 hover:bg-slate-50">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-slate-700 font-medium">
                          {(n.subjects || []).join(', ') || '—'}
                        </span>
                        {(n.grade_levels || []).length > 0 && (
                          <span className="text-[10px] text-slate-400">
                            Grade {n.grade_levels.join(', ')}
                          </span>
                        )}
                        <Badge className={`ml-auto text-[10px] px-1.5 py-0 ${NEED_STATUS_COLOR[n.status] || 'bg-slate-100 text-slate-500'}`}>
                          {n.status}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        {n.student_count && (
                          <span className="text-[10px] text-slate-400">{n.student_count} students</span>
                        )}
                        {n.schedule_preference && (
                          <><span className="text-[10px] text-slate-300">·</span>
                          <span className="text-[10px] text-slate-400">{n.schedule_preference}</span></>
                        )}
                        <span className="text-[10px] text-slate-300 ml-auto">
                          {timeAgo(n.submitted_at || n.created_at)}
                        </span>
                      </div>
                    </div>
                  ))}
                </ScrollArea>
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {/* Conversation modal */}
      {activeConv && (
        <ConversationPanel sessionId={activeConv} onClose={() => setActiveConv(null)} />
      )}
    </div>
  );
};

export default AdminView;

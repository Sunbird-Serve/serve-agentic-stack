/**
 * AgentsTab — Operations > Agents & Tools monitoring.
 * Agent health, performance charts, per-agent session tables.
 * Migrated from AdminView PerformancePanel with light theme.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw, Activity, Users, Handshake, UserPlus, TrendingUp,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { dashboardApi, orchestratorApi } from '../../services/api';

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (n) => (n ?? 0).toLocaleString();
const BAR_COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#ec4899'];

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

// ── Agent Health ─────────────────────────────────────────────────────────────

const AGENTS = [
  { key: 'onboarding', label: 'Onboarding Agent' },
  { key: 'selection', label: 'Selection Agent' },
  { key: 'engagement', label: 'Engagement Agent' },
  { key: 'fulfillment', label: 'Fulfillment Agent' },
  { key: 'need', label: 'Need Agent' },
];

const AgentHealthPanel = ({ health }) => {
  const agentStatuses = health?.agents || {};
  return (
    <Card className="border border-slate-200 shadow-sm">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-600 font-medium flex items-center gap-2">
          <Activity className="w-4 h-4" /> Agent Status
        </CardTitle>
      </CardHeader>
      <CardContent className="px-5 pb-4">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {AGENTS.map(({ key, label }) => {
            const info = agentStatuses[key];
            const healthy = info?.status === 'healthy' || info?.healthy === true;
            const unknown = !info;
            return (
              <div key={key} className="flex items-center gap-2 p-3 rounded-lg border border-slate-200 bg-slate-50">
                <span className={`w-3 h-3 rounded-full ${unknown ? 'bg-slate-300' : healthy ? 'bg-emerald-500' : 'bg-red-500'}`} />
                <div>
                  <p className="text-xs font-medium text-slate-700">{label}</p>
                  <p className="text-[10px] text-slate-400">{unknown ? 'Unknown' : healthy ? 'Healthy' : 'Unhealthy'}</p>
                </div>
              </div>
            );
          })}
          <div className="flex items-center gap-2 p-3 rounded-lg border border-slate-200 bg-slate-50">
            <span className={`w-3 h-3 rounded-full ${health ? 'bg-emerald-500' : 'bg-red-500'}`} />
            <div>
              <p className="text-xs font-medium text-slate-700">Orchestrator</p>
              <p className="text-[10px] text-slate-400">{health ? 'Healthy' : 'Unreachable'}</p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

// ── Performance Charts ───────────────────────────────────────────────────────

const PerformancePanel = ({ stats, sessions }) => {
  const byStage = stats?.sessions?.by_stage || {};
  const stageData = Object.entries(byStage)
    .map(([stage, count]) => ({ stage, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);

  const total = sessions.length;
  const completed = sessions.filter(s => s.status === 'completed').length;
  const conversionRate = total > 0 ? Math.round((completed / total) * 100) : 0;

  const agentMap = {};
  sessions.forEach(s => {
    const agent = s.active_agent || 'unknown';
    if (!agentMap[agent]) agentMap[agent] = { total: 0, completed: 0 };
    agentMap[agent].total += 1;
    if (s.status === 'completed') agentMap[agent].completed += 1;
  });
  const agentData = Object.entries(agentMap)
    .map(([agent, { total: t, completed: c }]) => ({
      agent,
      rate: t > 0 ? Math.round((c / t) * 100) : 0,
      total: t,
    }))
    .sort((a, b) => b.rate - a.rate);

  return (
    <Card className="border border-slate-200 shadow-sm">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-600 font-medium flex items-center gap-2">
          <TrendingUp className="w-4 h-4" /> Performance
        </CardTitle>
      </CardHeader>
      <CardContent className="px-5 pb-5">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Conversion Rate */}
          <div>
            <p className="text-xs text-slate-500 mb-3 uppercase tracking-wide font-medium">Conversion Rate</p>
            <div className="flex items-end gap-3">
              <span className={`text-4xl font-bold ${conversionRate >= 50 ? 'text-emerald-600' : conversionRate >= 25 ? 'text-amber-600' : 'text-red-600'}`}>
                {conversionRate}%
              </span>
              <span className="text-xs text-slate-500 pb-1">{completed} of {total} completed</span>
            </div>
            <div className="mt-3 h-2 rounded-full bg-slate-200">
              <div
                className={`h-2 rounded-full transition-all ${conversionRate >= 50 ? 'bg-emerald-500' : conversionRate >= 25 ? 'bg-amber-500' : 'bg-red-500'}`}
                style={{ width: `${conversionRate}%` }}
              />
            </div>
          </div>

          {/* Sessions by Stage */}
          <div>
            <p className="text-xs text-slate-500 mb-3 uppercase tracking-wide font-medium">Sessions by Stage</p>
            {stageData.length === 0 ? (
              <p className="text-xs text-slate-400">No data yet</p>
            ) : (
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={stageData} margin={{ top: 0, right: 0, left: -20, bottom: 40 }}>
                  <XAxis dataKey="stage" tick={{ fontSize: 9, fill: '#64748b' }} tickLine={false} axisLine={false} interval={0} angle={-35} textAnchor="end" />
                  <YAxis tick={{ fontSize: 9, fill: '#64748b' }} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 6, fontSize: 11 }} />
                  <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                    {stageData.map((_, i) => <Cell key={i} fill={BAR_COLORS[i % BAR_COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Agent Success Rates */}
          <div>
            <p className="text-xs text-slate-500 mb-3 uppercase tracking-wide font-medium">Agent Success Rates</p>
            {agentData.length === 0 ? (
              <p className="text-xs text-slate-400">No data yet</p>
            ) : (
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={agentData} margin={{ top: 0, right: 0, left: -20, bottom: 40 }}>
                  <XAxis dataKey="agent" tick={{ fontSize: 9, fill: '#64748b' }} tickLine={false} axisLine={false} interval={0} angle={-35} textAnchor="end" />
                  <YAxis tick={{ fontSize: 9, fill: '#64748b' }} tickLine={false} axisLine={false} domain={[0, 100]} unit="%" />
                  <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 6, fontSize: 11 }} formatter={(v) => [`${v}%`, 'Success']} />
                  <Bar dataKey="rate" radius={[3, 3, 0, 0]}>
                    {agentData.map((_, i) => <Cell key={i} fill={BAR_COLORS[i % BAR_COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

// ── Main ─────────────────────────────────────────────────────────────────────

export function AgentsTab() {
  const [stats, setStats] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, healthRes] = await Promise.all([
        dashboardApi.getStats(1, 500).catch(() => null),
        orchestratorApi.health().catch(() => null),
      ]);
      if (statsRes?.status === 'success') {
        setStats(statsRes.stats);
        setSessions(statsRes.recent_sessions || []);
      }
      setHealth(healthRes);
    } catch (e) {
      console.error('Agents load failed:', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Agents & Tools</h2>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Agent Health */}
      <AgentHealthPanel health={health} />

      {/* Performance */}
      {stats && <PerformancePanel stats={stats} sessions={sessions} />}
    </div>
  );
}

export default AgentsTab;

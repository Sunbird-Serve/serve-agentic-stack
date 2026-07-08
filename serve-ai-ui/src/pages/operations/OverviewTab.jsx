/**
 * OverviewTab — Operations Console landing page.
 * Shows KPI cards, agent health, and quick metrics.
 * Data from dashboardApi.getStats() and orchestratorApi.health().
 */
import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw, Users, Activity, MessageSquare, CheckCircle,
  Wifi, WifiOff, TrendingUp, AlertTriangle,
} from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { dashboardApi, orchestratorApi } from '../../services/api';

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (n) => (n ?? 0).toLocaleString();

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

// ── KPI Card ─────────────────────────────────────────────────────────────────

const KpiCard = ({ label, value, sub, icon: Icon, color = 'bg-blue-50', iconColor = 'text-blue-600' }) => (
  <Card className="border border-slate-200 shadow-sm">
    <CardContent className="p-4 flex items-center gap-3">
      <div className={`w-10 h-10 rounded-lg ${color} flex items-center justify-center shrink-0`}>
        <Icon className={`w-5 h-5 ${iconColor}`} />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-slate-500 truncate">{label}</p>
        <p className="text-xl font-bold text-slate-900 leading-tight">{value ?? '—'}</p>
        {sub && <p className="text-xs text-slate-400 truncate">{sub}</p>}
      </div>
    </CardContent>
  </Card>
);

// ── Agent Health Strip ───────────────────────────────────────────────────────

const AGENTS = [
  { key: 'onboarding', label: 'Onboarding' },
  { key: 'selection', label: 'Selection' },
  { key: 'engagement', label: 'Engagement' },
  { key: 'fulfillment', label: 'Fulfillment' },
  { key: 'need', label: 'Need' },
];

const AgentHealthStrip = ({ orchestratorHealth }) => {
  const agentStatuses = orchestratorHealth?.agents || {};
  return (
    <Card className="border border-slate-200 shadow-sm">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-600 font-medium flex items-center gap-2">
          <Activity className="w-4 h-4" /> Agent Health
        </CardTitle>
      </CardHeader>
      <CardContent className="px-5 pb-4">
        <div className="flex items-center gap-3 flex-wrap">
          {AGENTS.map(({ key, label }) => {
            const info = agentStatuses[key];
            const healthy = info?.status === 'healthy' || info?.healthy === true;
            const unknown = !info;
            return (
              <div key={key} className="flex items-center gap-1.5 bg-slate-50 rounded-full px-3 py-1.5 border border-slate-200">
                <span className={`w-2 h-2 rounded-full ${unknown ? 'bg-slate-400' : healthy ? 'bg-emerald-500' : 'bg-red-500'}`} />
                <span className="text-xs text-slate-700 font-medium">{label}</span>
              </div>
            );
          })}
          <div className="flex items-center gap-1.5 bg-slate-50 rounded-full px-3 py-1.5 border border-slate-200">
            <span className={`w-2 h-2 rounded-full ${orchestratorHealth ? 'bg-emerald-500' : 'bg-red-500'}`} />
            <span className="text-xs text-slate-700 font-medium">Orchestrator</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

// ── Main ─────────────────────────────────────────────────────────────────────

export function OverviewTab() {
  const [stats, setStats] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, healthRes] = await Promise.all([
        dashboardApi.getStats(1, 25).catch(() => null),
        orchestratorApi.health().catch(() => null),
      ]);
      if (statsRes?.status === 'success') {
        setStats(statsRes.stats);
      }
      setHealth(healthRes);
      setLastRefresh(new Date());
    } catch (e) {
      console.error('Overview load failed:', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [load]);

  const sessions = stats?.sessions || {};

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Platform Overview</h2>
          <p className="text-sm text-slate-500">
            {lastRefresh ? `Updated ${timeAgo(lastRefresh)}` : 'Loading...'}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          icon={Users}
          label="Total Sessions"
          value={fmt(sessions.total)}
          sub={`${fmt(sessions.today)} today`}
          color="bg-blue-50"
          iconColor="text-blue-600"
        />
        <KpiCard
          icon={Activity}
          label="Active Now"
          value={fmt(sessions.active)}
          color="bg-emerald-50"
          iconColor="text-emerald-600"
        />
        <KpiCard
          icon={MessageSquare}
          label="This Week"
          value={fmt(sessions.this_week)}
          sub="new sessions"
          color="bg-violet-50"
          iconColor="text-violet-600"
        />
        <KpiCard
          icon={CheckCircle}
          label="Completed"
          value={fmt(sessions.completed)}
          sub={sessions.total ? `${Math.round((sessions.completed / sessions.total) * 100)}% rate` : ''}
          color="bg-cyan-50"
          iconColor="text-cyan-600"
        />
      </div>

      {/* Agent Health */}
      <AgentHealthStrip orchestratorHealth={health} />

      {/* Connection Status */}
      <div className="flex items-center gap-2 text-sm">
        {health ? (
          <>
            <Wifi className="w-4 h-4 text-emerald-500" />
            <span className="text-emerald-600 font-medium">All systems operational</span>
          </>
        ) : (
          <>
            <WifiOff className="w-4 h-4 text-red-500" />
            <span className="text-red-600 font-medium">Cannot reach orchestrator</span>
          </>
        )}
      </div>
    </div>
  );
}

export default OverviewTab;

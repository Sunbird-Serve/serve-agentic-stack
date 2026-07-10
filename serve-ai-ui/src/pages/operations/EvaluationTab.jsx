/**
 * EvaluationTab — Operations > Evaluation.
 * Shows volunteer funnel (drop-off analysis), fulfillment metrics,
 * agent handoff decisions, and outcome analytics.
 * Data from dashboardApi.getAnalytics() + getStats().
 */
import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw, TrendingDown, BarChart3, ArrowRight,
  CheckCircle, XCircle, Activity,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { dashboardApi } from '../../services/api';

// ── Helpers ──────────────────────────────────────────────────────────────────

const BAR_COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#ec4899'];

const fmt = (n) => (n ?? 0).toLocaleString();

// ── Funnel Chart ─────────────────────────────────────────────────────────────

function FunnelSection({ funnel }) {
  if (!funnel || funnel.length === 0) {
    return (
      <Card className="border border-slate-200 shadow-sm">
        <CardContent className="py-8 text-center">
          <p className="text-sm text-slate-400">No funnel data available</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border border-slate-200 shadow-sm">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-600 font-medium flex items-center gap-2">
          <TrendingDown className="w-4 h-4" /> Volunteer Drop-off Funnel
        </CardTitle>
      </CardHeader>
      <CardContent className="px-5 pb-5">
        <div className="mb-4">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={funnel} margin={{ top: 10, right: 0, left: -20, bottom: 50 }}>
              <XAxis
                dataKey="stage"
                tick={{ fontSize: 10, fill: '#64748b' }}
                tickLine={false}
                axisLine={false}
                interval={0}
                angle={-40}
                textAnchor="end"
              />
              <YAxis tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip
                contentStyle={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 6, fontSize: 11 }}
                formatter={(value, name) => [value, name === 'count' ? 'Sessions' : name]}
              />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {funnel.map((_, i) => (
                  <Cell key={i} fill={BAR_COLORS[i % BAR_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Drop-off table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200">
                <th className="text-left text-xs text-slate-500 font-medium py-2 px-3">Stage</th>
                <th className="text-right text-xs text-slate-500 font-medium py-2 px-3">Count</th>
                <th className="text-right text-xs text-slate-500 font-medium py-2 px-3">Drop-off</th>
              </tr>
            </thead>
            <tbody>
              {funnel.map((stage, i) => (
                <tr key={stage.stage} className="border-b border-slate-100">
                  <td className="py-2 px-3 text-xs text-slate-700 font-medium">{stage.stage}</td>
                  <td className="py-2 px-3 text-xs text-slate-600 text-right">{fmt(stage.count)}</td>
                  <td className="py-2 px-3 text-right">
                    {stage.drop_off_pct > 0 ? (
                      <span className="text-xs text-red-600 font-medium">-{stage.drop_off_pct}%</span>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Fulfillment Metrics ──────────────────────────────────────────────────────

function FulfillmentSection({ fulfillment }) {
  if (!fulfillment) {
    return null;
  }

  const { by_status, total, conversion_pct } = fulfillment;
  const statusData = Object.entries(by_status || {}).map(([status, count]) => ({ status, count }));

  return (
    <Card className="border border-slate-200 shadow-sm">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-600 font-medium flex items-center gap-2">
          <CheckCircle className="w-4 h-4" /> Need Fulfillment
        </CardTitle>
      </CardHeader>
      <CardContent className="px-5 pb-5">
        <div className="grid grid-cols-3 gap-4 mb-4">
          <div className="text-center p-3 rounded-lg bg-blue-50">
            <p className="text-2xl font-bold text-blue-700">{fmt(total)}</p>
            <p className="text-xs text-blue-600">Total Needs</p>
          </div>
          <div className="text-center p-3 rounded-lg bg-emerald-50">
            <p className="text-2xl font-bold text-emerald-700">{conversion_pct}%</p>
            <p className="text-xs text-emerald-600">Conversion</p>
          </div>
          <div className="text-center p-3 rounded-lg bg-amber-50">
            <p className="text-2xl font-bold text-amber-700">{fmt(by_status?.pending_approval || 0)}</p>
            <p className="text-xs text-amber-600">Pending</p>
          </div>
        </div>

        {statusData.length > 0 && (
          <ResponsiveContainer width="100%" height={120}>
            <BarChart data={statusData} layout="vertical" margin={{ top: 0, right: 10, left: 80, bottom: 0 }}>
              <XAxis type="number" tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="status" tick={{ fontSize: 10, fill: '#64748b' }} tickLine={false} axisLine={false} width={80} />
              <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 6, fontSize: 11 }} />
              <Bar dataKey="count" radius={[0, 4, 4, 0]} fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

// ── Agent Decisions ──────────────────────────────────────────────────────────

function DecisionsSection({ decisions }) {
  if (!decisions || decisions.length === 0) {
    return null;
  }

  return (
    <Card className="border border-slate-200 shadow-sm">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-600 font-medium flex items-center gap-2">
          <Activity className="w-4 h-4" /> Agent Handoff Decisions
        </CardTitle>
      </CardHeader>
      <CardContent className="px-5 pb-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200">
                <th className="text-left text-xs text-slate-500 font-medium py-2 px-3">From</th>
                <th className="text-left text-xs text-slate-500 font-medium py-2 px-3"></th>
                <th className="text-left text-xs text-slate-500 font-medium py-2 px-3">To</th>
                <th className="text-left text-xs text-slate-500 font-medium py-2 px-3">Type</th>
                <th className="text-left text-xs text-slate-500 font-medium py-2 px-3">Reason</th>
                <th className="text-right text-xs text-slate-500 font-medium py-2 px-3">Count</th>
              </tr>
            </thead>
            <tbody>
              {decisions.slice(0, 20).map((d, i) => (
                <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-2 px-3">
                    <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 font-medium">
                      {d.from_agent}
                    </span>
                  </td>
                  <td className="py-2 px-3">
                    <ArrowRight className="w-3 h-3 text-slate-400" />
                  </td>
                  <td className="py-2 px-3">
                    <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 font-medium">
                      {d.to_agent}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-xs text-slate-600">{d.handoff_type}</td>
                  <td className="py-2 px-3 text-xs text-slate-500 max-w-[200px] truncate" title={d.reason}>
                    {d.reason || '—'}
                  </td>
                  <td className="py-2 px-3 text-xs text-slate-700 font-medium text-right">{fmt(d.count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Session Outcomes ─────────────────────────────────────────────────────────

function OutcomesSection({ stats }) {
  if (!stats) return null;

  const sessions = stats.sessions || {};
  const total = sessions.total || 0;
  const completed = sessions.completed || 0;
  const active = sessions.active || 0;
  const paused = sessions.paused || 0;

  const outcomes = [
    { label: 'Completed', value: completed, color: 'bg-emerald-500' },
    { label: 'Active', value: active, color: 'bg-blue-500' },
    { label: 'Paused/Dropped', value: paused, color: 'bg-amber-500' },
    { label: 'Other', value: Math.max(0, total - completed - active - paused), color: 'bg-slate-400' },
  ].filter(o => o.value > 0);

  return (
    <Card className="border border-slate-200 shadow-sm">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-600 font-medium flex items-center gap-2">
          <BarChart3 className="w-4 h-4" /> Conversation Outcomes
        </CardTitle>
      </CardHeader>
      <CardContent className="px-5 pb-5">
        <div className="flex items-center gap-4 mb-4">
          <div>
            <p className="text-3xl font-bold text-slate-900">{fmt(total)}</p>
            <p className="text-xs text-slate-500">Total conversations</p>
          </div>
          <div className="flex-1">
            <div className="flex h-3 rounded-full overflow-hidden bg-slate-100">
              {outcomes.map((o, i) => (
                <div
                  key={i}
                  className={`${o.color} transition-all`}
                  style={{ width: `${total > 0 ? (o.value / total) * 100 : 0}%` }}
                  title={`${o.label}: ${o.value}`}
                />
              ))}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-4">
          {outcomes.map((o, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className={`w-3 h-3 rounded-full ${o.color}`} />
              <span className="text-xs text-slate-600">{o.label}: {fmt(o.value)}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────

export function EvaluationTab() {
  const [analytics, setAnalytics] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [analyticsRes, statsRes] = await Promise.all([
        dashboardApi.getAnalytics().catch(() => null),
        dashboardApi.getStats(1, 25).catch(() => null),
      ]);
      if (analyticsRes?.status === 'success') {
        setAnalytics(analyticsRes);
      } else if (analyticsRes?.status === 'error') {
        setError(analyticsRes.error);
      }
      if (statsRes?.status === 'success') {
        setStats(statsRes.stats);
      }
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <RefreshCw className="w-6 h-6 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-center">
        <XCircle className="w-8 h-8 text-red-400 mx-auto mb-2" />
        <p className="text-sm text-red-600">{error}</p>
        <Button variant="outline" size="sm" onClick={load} className="mt-4">
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Evaluation</h2>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Conversation Outcomes */}
      <OutcomesSection stats={stats} />

      {/* Funnel */}
      <FunnelSection funnel={analytics?.funnel} />

      {/* Fulfillment */}
      <FulfillmentSection fulfillment={analytics?.fulfillment} />

      {/* Agent Decisions */}
      <DecisionsSection decisions={analytics?.decisions} />
    </div>
  );
}

export default EvaluationTab;

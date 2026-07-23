/**
 * NeedsDashboard — KPIs + funnel for need coordination pipeline.
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileText, School, CheckCircle2, Clock, AlertTriangle } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { dashboardApi } from '../../services/api';

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const KpiCard = ({ label, value, icon: Icon, color = 'bg-slate-50', iconColor = 'text-slate-600' }) => (
  <Card className="border-none shadow-sm">
    <CardContent className="p-4 flex items-center gap-3">
      <div className={`w-10 h-10 rounded-lg ${color} flex items-center justify-center shrink-0`}>
        <Icon className={`w-5 h-5 ${iconColor}`} />
      </div>
      <div>
        <p className="text-xs text-slate-500">{label}</p>
        <p className="text-xl font-bold text-slate-900">{value ?? '—'}</p>
      </div>
    </CardContent>
  </Card>
);

function classifyNeeds(sessions) {
  const needs = { initiated: 0, drafting: 0, submitted: 0, approved: 0, fulfilled: 0, rejected: 0, total: 0, actionItems: [] };

  for (const s of sessions) {
    if (s.workflow !== 'need_coordination') continue;
    needs.total++;

    const stage = s.stage || '';
    if (['initiated', 'capturing_phone', 'resolving_coordinator', 'resolving_school'].includes(stage)) {
      needs.initiated++;
    } else if (stage === 'drafting_need') {
      needs.drafting++;
    } else if (['pending_approval', 'submitted'].includes(stage)) {
      needs.submitted++;
    } else if (stage === 'approved') {
      needs.approved++;
    } else if (stage === 'fulfillment_handoff_ready') {
      needs.fulfilled++;
    } else if (stage === 'rejected') {
      needs.rejected++;
    }

    // Action items
    if (stage === 'drafting_need' && s.last_message_at) {
      const days = Math.floor((Date.now() - new Date(s.last_message_at)) / 86400000);
      if (days >= 3) {
        needs.actionItems.push({ id: s.id, issue: `Drafting stuck (${days} days)`, since: s.last_message_at });
      }
    }
    if (stage === 'refinement_required') {
      needs.actionItems.push({ id: s.id, issue: 'Needs refinement', since: s.last_message_at });
    }
  }

  needs.actionItems.sort((a, b) => new Date(a.since) - new Date(b.since));
  return needs;
}

export function NeedsDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await dashboardApi.getStats(1, 500);
      if (res.status === 'success') setData(res);
    } catch (e) {
      console.error('Load failed:', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const sessions = data?.recent_sessions || [];
  const needs = classifyNeeds(sessions);

  return (
    <div className="p-6 max-w-[1200px] mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Need Coordination Pipeline</h1>
          <p className="text-sm text-slate-500">School teaching needs lifecycle</p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <KpiCard label="Total Needs" value={needs.total} icon={FileText} color="bg-blue-50" iconColor="text-blue-600" />
        <KpiCard label="In Progress" value={needs.initiated + needs.drafting} icon={Clock} color="bg-amber-50" iconColor="text-amber-600" />
        <KpiCard label="Submitted" value={needs.submitted} icon={School} color="bg-violet-50" iconColor="text-violet-600" />
        <KpiCard label="Approved" value={needs.approved} icon={CheckCircle2} color="bg-emerald-50" iconColor="text-emerald-600" />
        <KpiCard label="Fulfilled" value={needs.fulfilled} icon={CheckCircle2} color="bg-teal-50" iconColor="text-teal-600" />
      </div>

      {/* Funnel */}
      <Card className="border-none shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-slate-600">Need Lifecycle Funnel</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center gap-2 py-4 overflow-x-auto">
            {[
              { label: 'Initiated', count: needs.initiated, color: 'bg-blue-100 text-blue-800' },
              { label: 'Drafting', count: needs.drafting, color: 'bg-amber-100 text-amber-800' },
              { label: 'Submitted', count: needs.submitted, color: 'bg-violet-100 text-violet-800' },
              { label: 'Approved', count: needs.approved, color: 'bg-emerald-100 text-emerald-800' },
              { label: 'Fulfilled', count: needs.fulfilled, color: 'bg-teal-100 text-teal-800' },
            ].map((stage, i, arr) => (
              <div key={stage.label} className="flex items-center gap-2">
                <div className={`rounded-xl px-4 py-3 text-center min-w-[100px] ${stage.color}`}>
                  <p className="text-2xl font-bold">{stage.count}</p>
                  <p className="text-xs font-medium opacity-80">{stage.label}</p>
                </div>
                {i < arr.length - 1 && <span className="text-slate-300">→</span>}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Action Items */}
      {needs.actionItems.length > 0 && (
        <Card className="border-none shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-slate-600 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-500" /> Action Required ({needs.actionItems.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {needs.actionItems.slice(0, 10).map((item, i) => (
                <div key={i} className="flex items-center justify-between py-2 border-b border-slate-50 last:border-0">
                  <span className="text-sm text-slate-700">{item.issue}</span>
                  <span className="text-xs text-slate-400">{timeAgo(item.since)}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default NeedsDashboard;

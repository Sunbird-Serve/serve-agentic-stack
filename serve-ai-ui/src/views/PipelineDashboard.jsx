/**
 * SERVE AI - Volunteer Pipeline Dashboard
 * Single-screen view showing the volunteer journey funnel:
 * Onboarding → Selection → Engagement → Fulfillment
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Users, UserCheck, UserX, Clock, ArrowRight, CheckCircle2, PauseCircle, AlertTriangle } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { ScrollArea } from '../components/ui/scroll-area';
import { dashboardApi } from '../services/api';

const timeAgo = (iso) => {
  if (!iso) return '';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const Metric = ({ label, value, sub, color = 'bg-slate-100', textColor = 'text-slate-700' }) => (
  <div className={`rounded-xl p-4 ${color}`}>
    <p className="text-xs text-slate-500">{label}</p>
    <p className={`text-2xl font-bold ${textColor}`}>{value}</p>
    {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
  </div>
);

const FunnelStage = ({ title, icon: Icon, color, metrics, sessions }) => (
  <Card className="border-none shadow-sm">
    <CardContent className="p-5">
      <div className="flex items-center gap-2 mb-4">
        <div className={`w-8 h-8 rounded-lg ${color} flex items-center justify-center`}>
          <Icon className="w-4 h-4 text-white" />
        </div>
        <h3 className="font-semibold text-slate-800">{title}</h3>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        {metrics.map((m, i) => (
          <Metric key={i} {...m} />
        ))}
      </div>
      {sessions.length > 0 && (
        <ScrollArea className="h-48">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100">
                <th className="text-left text-xs text-slate-400 font-medium py-1.5 px-2">Name</th>
                <th className="text-left text-xs text-slate-400 font-medium py-1.5 px-2">Stage</th>
                <th className="text-left text-xs text-slate-400 font-medium py-1.5 px-2">Status</th>
                <th className="text-left text-xs text-slate-400 font-medium py-1.5 px-2">Last Active</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id} className="border-b border-slate-50 hover:bg-slate-50">
                  <td className="py-1.5 px-2 text-slate-700">{s.name || 'Volunteer'}</td>
                  <td className="py-1.5 px-2 text-slate-500 text-xs">{s.stage}</td>
                  <td className="py-1.5 px-2">
                    <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                      s.status === 'active' ? 'bg-emerald-100 text-emerald-700' :
                      s.status === 'completed' ? 'bg-cyan-100 text-cyan-700' :
                      s.status === 'paused' ? 'bg-amber-100 text-amber-700' :
                      'bg-slate-100 text-slate-600'
                    }`}>{s.status}</span>
                  </td>
                  <td className="py-1.5 px-2 text-slate-400 text-xs">{timeAgo(s.last_message_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollArea>
      )}
    </CardContent>
  </Card>
);

function classifySessions(sessions) {
  const onboarding = { entered: 0, registered: 0, eligible: 0, ineligible: 0, inProgress: 0, sessions: [] };
  const selection = { entered: 0, recommended: 0, notRecommended: 0, onHold: 0, sessions: [] };
  const engagement = { entered: 0, prefsGiven: 0, deferred: 0, sessions: [] };
  const fulfillment = { entered: 0, matched: 0, noMatch: 0, nominated: 0, sessions: [] };

  for (const s of sessions) {
    const name = s.volunteer_name || (s.channel_metadata ? (typeof s.channel_metadata === 'string' ? (() => { try { return JSON.parse(s.channel_metadata); } catch { return {}; } })() : s.channel_metadata).volunteer_name : null) || 'Volunteer';
    const row = { id: s.id, name, stage: s.stage, status: s.status, last_message_at: s.last_message_at };

    // Parse sub_state safely
    let ss = {};
    try { ss = s.sub_state ? JSON.parse(s.sub_state) : {}; } catch {}

    const agent = s.active_agent;
    const workflow = s.workflow;

    // Onboarding
    if (agent === 'onboarding' || ['welcome', 'orientation_video', 'eligibility_screening', 'contact_capture', 'registration_review', 'onboarding_complete'].includes(s.stage)) {
      onboarding.entered++;
      if (s.stage === 'onboarding_complete') onboarding.registered++;
      if (['contact_capture', 'registration_review', 'onboarding_complete'].includes(s.stage)) onboarding.eligible++;
      if (s.stage === 'human_review' && agent === 'onboarding') onboarding.ineligible++;
      if (s.status === 'active' && agent === 'onboarding') { onboarding.inProgress++; onboarding.sessions.push(row); }
    }

    // Selection
    if (agent === 'selection' || ['selection_conversation', 'gathering_preferences'].includes(s.stage)) {
      selection.entered++;
      const outcome = ss.outcome;
      if (outcome === 'recommended') selection.recommended++;
      else if (outcome === 'not_matched') selection.notRecommended++;
      else if (outcome === 'human_review' || s.stage === 'human_review') selection.onHold++;
      if (s.status === 'active' && agent === 'selection') selection.sessions.push(row);
    }

    // Engagement
    if (agent === 'engagement' || workflow === 'returning_volunteer' || workflow === 'recommended_volunteer') {
      if (agent === 'engagement') {
        engagement.entered++;
        if (ss.preference_notes) engagement.prefsGiven++;
        if (ss.deferred) engagement.deferred++;
        if (s.status === 'active' && agent === 'engagement') engagement.sessions.push({ ...row, prefs: ss.preference_notes || '' });
      }
    }

    // Fulfillment
    if (agent === 'fulfillment') {
      fulfillment.entered++;
      const mr = ss.match_result || {};
      if (mr.status === 'found' || mr.status === 'multiple') fulfillment.matched++;
      if (mr.status === 'not_found') fulfillment.noMatch++;
      if (ss.nominated_need_id) fulfillment.nominated++;
      if (s.status === 'active' && agent === 'fulfillment') fulfillment.sessions.push(row);
    }
  }

  return { onboarding, selection, engagement, fulfillment };
}

export const PipelineDashboard = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await dashboardApi.getStats(1, 100);
      if (res.status === 'success') {
        setData(res);
        setLastRefresh(new Date());
      }
    } catch (e) {
      console.error('Dashboard load failed:', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const sessions = data?.recent_sessions || [];
  const stats = data?.stats || {};
  const { onboarding, selection, engagement, fulfillment } = classifySessions(sessions);

  return (
    <div className="p-6 bg-slate-50 min-h-[calc(100vh-64px)]">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Volunteer Pipeline</h2>
          <p className="text-sm text-slate-500">
            End-to-end journey tracking
            {lastRefresh && <span className="ml-2 text-slate-400">Updated {timeAgo(lastRefresh)}</span>}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Top-level summary */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
        <Metric label="Total Sessions" value={stats.sessions?.total || 0} color="bg-blue-50" textColor="text-blue-700" />
        <Metric label="Active Now" value={stats.sessions?.active || 0} color="bg-emerald-50" textColor="text-emerald-700" />
        <Metric label="Today" value={stats.sessions?.today || 0} color="bg-violet-50" textColor="text-violet-700" />
        <Metric label="This Week" value={stats.sessions?.this_week || 0} color="bg-amber-50" textColor="text-amber-700" />
        <Metric label="Nominations" value={fulfillment.nominated} color="bg-teal-50" textColor="text-teal-700" />
      </div>

      {/* Funnel arrow */}
      <div className="hidden sm:flex items-center justify-center gap-2 mb-4 text-slate-300">
        <span className="text-sm font-medium text-slate-500">Onboarding</span>
        <ArrowRight className="w-4 h-4" />
        <span className="text-sm font-medium text-slate-500">Selection</span>
        <ArrowRight className="w-4 h-4" />
        <span className="text-sm font-medium text-slate-500">Engagement</span>
        <ArrowRight className="w-4 h-4" />
        <span className="text-sm font-medium text-slate-500">Fulfillment</span>
      </div>

      {/* Pipeline stages */}
      <div className="space-y-4">
        <FunnelStage
          title="Onboarding"
          icon={Users}
          color="bg-blue-500"
          metrics={[
            { label: 'Entered', value: onboarding.entered, color: 'bg-blue-50', textColor: 'text-blue-700' },
            { label: 'Eligible', value: onboarding.eligible, color: 'bg-emerald-50', textColor: 'text-emerald-700' },
            { label: 'Registered', value: onboarding.registered, color: 'bg-cyan-50', textColor: 'text-cyan-700' },
            { label: 'Needs Review', value: onboarding.ineligible, color: 'bg-amber-50', textColor: 'text-amber-700' },
          ]}
          sessions={onboarding.sessions}
        />

        <FunnelStage
          title="Selection"
          icon={UserCheck}
          color="bg-violet-500"
          metrics={[
            { label: 'Entered', value: selection.entered, color: 'bg-violet-50', textColor: 'text-violet-700' },
            { label: 'Recommended', value: selection.recommended, color: 'bg-emerald-50', textColor: 'text-emerald-700' },
            { label: 'Not Matched', value: selection.notRecommended, color: 'bg-red-50', textColor: 'text-red-600' },
            { label: 'On Hold', value: selection.onHold, color: 'bg-amber-50', textColor: 'text-amber-700' },
          ]}
          sessions={selection.sessions}
        />

        <FunnelStage
          title="Engagement"
          icon={Clock}
          color="bg-emerald-500"
          metrics={[
            { label: 'Entered', value: engagement.entered, color: 'bg-emerald-50', textColor: 'text-emerald-700' },
            { label: 'Prefs Given', value: engagement.prefsGiven, color: 'bg-cyan-50', textColor: 'text-cyan-700' },
            { label: 'Deferred', value: engagement.deferred, color: 'bg-amber-50', textColor: 'text-amber-700' },
          ]}
          sessions={engagement.sessions}
        />

        <FunnelStage
          title="Fulfillment"
          icon={CheckCircle2}
          color="bg-teal-500"
          metrics={[
            { label: 'Entered', value: fulfillment.entered, color: 'bg-teal-50', textColor: 'text-teal-700' },
            { label: 'Matched', value: fulfillment.matched, color: 'bg-emerald-50', textColor: 'text-emerald-700' },
            { label: 'No Match', value: fulfillment.noMatch, color: 'bg-red-50', textColor: 'text-red-600' },
            { label: 'Nominated', value: fulfillment.nominated, color: 'bg-cyan-50', textColor: 'text-cyan-700' },
          ]}
          sessions={fulfillment.sessions}
        />
      </div>
    </div>
  );
};

export default PipelineDashboard;

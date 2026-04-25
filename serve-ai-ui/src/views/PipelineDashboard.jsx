/**
 * SERVE AI - Volunteer Pipeline Dashboard
 * Single-screen funnel: Onboarding → Selection → Engagement → Fulfillment
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Users, UserCheck, Clock, CheckCircle2, ArrowRight, ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { dashboardApi } from '../services/api';

const timeAgo = (iso) => {
  if (!iso) return '';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const Metric = ({ label, value, color = 'bg-slate-100', textColor = 'text-slate-700' }) => (
  <div className={`rounded-xl p-4 ${color}`}>
    <p className="text-xs text-slate-500">{label}</p>
    <p className={`text-2xl font-bold ${textColor}`}>{value}</p>
  </div>
);

const OutcomePill = ({ outcome }) => {
  const map = {
    'Eligible': 'bg-emerald-100 text-emerald-700',
    'Registered': 'bg-cyan-100 text-cyan-700',
    'Needs Review': 'bg-amber-100 text-amber-700',
    'In Progress': 'bg-blue-100 text-blue-700',
    'Recommended': 'bg-emerald-100 text-emerald-700',
    'Not Matched': 'bg-red-100 text-red-600',
    'On Hold': 'bg-amber-100 text-amber-700',
    'Prefs Given': 'bg-cyan-100 text-cyan-700',
    'Deferred': 'bg-amber-100 text-amber-700',
    'Matched': 'bg-emerald-100 text-emerald-700',
    'Nominated': 'bg-teal-100 text-teal-700',
    'No Match': 'bg-red-100 text-red-600',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${map[outcome] || 'bg-slate-100 text-slate-600'}`}>
      {outcome}
    </span>
  );
};

// Extract volunteer name from multiple sources
function extractName(s, ss) {
  return s.volunteer_name
    || ss.engagement_context?.volunteer_name
    || ss.handoff?.volunteer_name
    || ss.handoff?.confirmed_fields?.full_name
    || (s.channel_metadata?.volunteer_name)
    || null;
}

function extractPhone(s, ss) {
  return s.volunteer_phone
    || ss.engagement_context?.volunteer_phone
    || s.channel_metadata?.volunteer_phone
    || s.channel_metadata?.phone_number
    || s.channel_metadata?.from
    || null;
}

function parseSS(s) {
  try { return s.sub_state ? JSON.parse(s.sub_state) : {}; } catch { return {}; }
}

function classifySessions(sessions) {
  const onboarding = { entered: 0, registered: 0, eligible: 0, ineligible: 0, rows: [] };
  const selection = { entered: 0, recommended: 0, notRecommended: 0, onHold: 0, rows: [] };
  const engagement = { entered: 0, prefsGiven: 0, deferred: 0, rows: [] };
  const fulfillment = { entered: 0, matched: 0, noMatch: 0, nominated: 0, rows: [] };

  for (const s of sessions) {
    const ss = parseSS(s);
    const name = extractName(s, ss) || 'Volunteer';
    const phone = extractPhone(s, ss) || '';
    const agent = s.active_agent;

    // Onboarding
    if (agent === 'onboarding' || ['welcome','orientation_video','eligibility_screening','contact_capture','registration_review','onboarding_complete'].includes(s.stage)) {
      onboarding.entered++;
      let outcome = 'In Progress';
      if (s.stage === 'onboarding_complete') { onboarding.registered++; outcome = 'Registered'; }
      if (['contact_capture','registration_review','onboarding_complete'].includes(s.stage)) { onboarding.eligible++; if (outcome === 'In Progress') outcome = 'Eligible'; }
      if (s.stage === 'human_review' && agent === 'onboarding') { onboarding.ineligible++; outcome = 'Needs Review'; }
      onboarding.rows.push({ id: s.id, name, phone, stage: s.stage, status: s.status, outcome, last: s.last_message_at });
    }

    // Selection
    if (agent === 'selection' || ['selection_conversation','gathering_preferences'].includes(s.stage)) {
      selection.entered++;
      let outcome = 'In Progress';
      const selOutcome = ss.outcome;
      if (selOutcome === 'recommended') { selection.recommended++; outcome = 'Recommended'; }
      else if (selOutcome === 'not_matched') { selection.notRecommended++; outcome = 'Not Matched'; }
      else if (selOutcome === 'human_review' || s.stage === 'human_review') { selection.onHold++; outcome = 'On Hold'; }
      selection.rows.push({ id: s.id, name, phone, stage: s.stage, status: s.status, outcome, last: s.last_message_at });
    }

    // Engagement
    if (agent === 'engagement') {
      engagement.entered++;
      let outcome = 'In Progress';
      if (ss.preference_notes) { engagement.prefsGiven++; outcome = 'Prefs Given'; }
      if (ss.deferred) { engagement.deferred++; outcome = 'Deferred'; }
      engagement.rows.push({ id: s.id, name, phone, stage: s.stage, status: s.status, outcome, prefs: ss.preference_notes || '', last: s.last_message_at });
    }

    // Fulfillment
    if (agent === 'fulfillment') {
      fulfillment.entered++;
      let outcome = 'In Progress';
      const mr = ss.match_result || {};
      if (mr.status === 'found' || mr.status === 'multiple') { fulfillment.matched++; outcome = 'Matched'; }
      if (mr.status === 'not_found') { fulfillment.noMatch++; outcome = 'No Match'; }
      if (ss.nominated_need_id) { fulfillment.nominated++; outcome = 'Nominated'; }
      fulfillment.rows.push({ id: s.id, name, phone, stage: s.stage, status: s.status, outcome, last: s.last_message_at });
    }
  }

  return { onboarding, selection, engagement, fulfillment };
}

const PAGE_SIZE = 10;

const PaginatedTable = ({ rows, columns }) => {
  const [page, setPage] = useState(0);
  const totalPages = Math.ceil(rows.length / PAGE_SIZE);
  const pageRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-100">
            {columns.map(c => (
              <th key={c.key} className="text-left text-xs text-slate-400 font-medium py-1.5 px-2">{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pageRows.length === 0 ? (
            <tr><td colSpan={columns.length} className="text-center text-slate-400 py-6 text-sm">No sessions</td></tr>
          ) : pageRows.map((row) => (
            <tr key={row.id} className="border-b border-slate-50 hover:bg-slate-50">
              {columns.map(c => (
                <td key={c.key} className="py-1.5 px-2 text-slate-700 text-xs">
                  {c.render ? c.render(row) : row[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-2 py-2 text-xs text-slate-500">
          <span>Showing {page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, rows.length)} of {rows.length}</span>
          <div className="flex items-center gap-1">
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="p-1 rounded hover:bg-slate-100 disabled:opacity-30">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span>Page {page + 1} of {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="p-1 rounded hover:bg-slate-100 disabled:opacity-30">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </>
  );
};

const FunnelStage = ({ title, icon: Icon, color, metrics, rows, extraColumns = [] }) => {
  const baseColumns = [
    { key: 'name', label: 'Name' },
    { key: 'phone', label: 'Phone', render: (r) => r.phone ? r.phone.replace(/^91/, '') : '—' },
    { key: 'stage', label: 'Stage' },
    { key: 'outcome', label: 'Outcome', render: (r) => <OutcomePill outcome={r.outcome} /> },
    ...extraColumns,
    { key: 'status', label: 'Status', render: (r) => (
      <span className={`text-xs px-1.5 py-0.5 rounded-full ${
        r.status === 'active' ? 'bg-emerald-100 text-emerald-700' :
        r.status === 'completed' ? 'bg-cyan-100 text-cyan-700' :
        r.status === 'paused' ? 'bg-amber-100 text-amber-700' :
        'bg-slate-100 text-slate-600'
      }`}>{r.status}</span>
    )},
    { key: 'last', label: 'Last Active', render: (r) => timeAgo(r.last) },
  ];

  return (
    <Card className="border-none shadow-sm">
      <CardContent className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className={`w-8 h-8 rounded-lg ${color} flex items-center justify-center`}>
            <Icon className="w-4 h-4 text-white" />
          </div>
          <h3 className="font-semibold text-slate-800">{title}</h3>
          <span className="text-xs text-slate-400 ml-auto">{rows.length} sessions</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          {metrics.map((m, i) => <Metric key={i} {...m} />)}
        </div>
        <PaginatedTable rows={rows} columns={baseColumns} />
      </CardContent>
    </Card>
  );
};

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

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
        <Metric label="Total Sessions" value={stats.sessions?.total || 0} color="bg-blue-50" textColor="text-blue-700" />
        <Metric label="Active Now" value={stats.sessions?.active || 0} color="bg-emerald-50" textColor="text-emerald-700" />
        <Metric label="Today" value={stats.sessions?.today || 0} color="bg-violet-50" textColor="text-violet-700" />
        <Metric label="This Week" value={stats.sessions?.this_week || 0} color="bg-amber-50" textColor="text-amber-700" />
        <Metric label="Nominations" value={fulfillment.nominated} color="bg-teal-50" textColor="text-teal-700" />
      </div>

      <div className="hidden sm:flex items-center justify-center gap-2 mb-4 text-slate-300">
        <span className="text-sm font-medium text-slate-500">Onboarding</span>
        <ArrowRight className="w-4 h-4" />
        <span className="text-sm font-medium text-slate-500">Getting to Know You</span>
        <ArrowRight className="w-4 h-4" />
        <span className="text-sm font-medium text-slate-500">Preferences</span>
        <ArrowRight className="w-4 h-4" />
        <span className="text-sm font-medium text-slate-500">Assignment</span>
      </div>

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
          rows={onboarding.rows}
        />

        <FunnelStage
          title="Getting to Know You"
          icon={UserCheck}
          color="bg-violet-500"
          metrics={[
            { label: 'Entered', value: selection.entered, color: 'bg-violet-50', textColor: 'text-violet-700' },
            { label: 'Recommended', value: selection.recommended, color: 'bg-emerald-50', textColor: 'text-emerald-700' },
            { label: 'Not Matched', value: selection.notRecommended, color: 'bg-red-50', textColor: 'text-red-600' },
            { label: 'On Hold', value: selection.onHold, color: 'bg-amber-50', textColor: 'text-amber-700' },
          ]}
          rows={selection.rows}
        />

        <FunnelStage
          title="Schedule Preferences"
          icon={Clock}
          color="bg-emerald-500"
          metrics={[
            { label: 'Entered', value: engagement.entered, color: 'bg-emerald-50', textColor: 'text-emerald-700' },
            { label: 'Prefs Given', value: engagement.prefsGiven, color: 'bg-cyan-50', textColor: 'text-cyan-700' },
            { label: 'Deferred', value: engagement.deferred, color: 'bg-amber-50', textColor: 'text-amber-700' },
          ]}
          rows={engagement.rows}
          extraColumns={[{ key: 'prefs', label: 'Preferences', render: (r) => <span className="text-slate-500 truncate max-w-[150px] block" title={r.prefs}>{r.prefs || '—'}</span> }]}
        />

        <FunnelStage
          title="Teaching Assignment"
          icon={CheckCircle2}
          color="bg-teal-500"
          metrics={[
            { label: 'Entered', value: fulfillment.entered, color: 'bg-teal-50', textColor: 'text-teal-700' },
            { label: 'Matched', value: fulfillment.matched, color: 'bg-emerald-50', textColor: 'text-emerald-700' },
            { label: 'No Match', value: fulfillment.noMatch, color: 'bg-red-50', textColor: 'text-red-600' },
            { label: 'Nominated', value: fulfillment.nominated, color: 'bg-cyan-50', textColor: 'text-cyan-700' },
          ]}
          rows={fulfillment.rows}
        />
      </div>
    </div>
  );
};

export default PipelineDashboard;

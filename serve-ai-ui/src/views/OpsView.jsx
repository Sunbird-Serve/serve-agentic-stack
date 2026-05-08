/**
 * eVidyaloka — Volunteer Management Dashboard
 * Unified ops view: KPIs → Funnel → Per-Agent Detail → Action Queue
 */
import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw, Users, UserCheck, Clock, CheckCircle2, AlertTriangle,
  ArrowRight, ChevronLeft, ChevronRight, TrendingUp,
  XCircle, Lock, Handshake, Timer, BarChart3,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Input } from '../components/ui/input';
import { dashboardApi, dashboardAuth } from '../services/api';

// ═══════════════════════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════════════════════

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const daysBetween = (a, b) => {
  if (!a || !b) return null;
  return Math.round(Math.abs(new Date(b) - new Date(a)) / 86400000);
};

function parseSS(s) {
  try { return s.sub_state ? JSON.parse(s.sub_state) : {}; } catch { return {}; }
}

function extractName(s, ss) {
  return s.volunteer_name
    || ss.engagement_context?.volunteer_name
    || ss.handoff?.volunteer_name
    || null;
}

function extractPhone(s, ss) {
  return s.volunteer_phone
    || ss.engagement_context?.volunteer_phone
    || (typeof s.channel_metadata === 'object' ? s.channel_metadata?.volunteer_phone : null)
    || (typeof s.channel_metadata === 'object' ? s.channel_metadata?.phone_number : null)
    || null;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Data classification
// ═══════════════════════════════════════════════════════════════════════════════

function classifyAll(sessions) {
  const onboarding = { entered: 0, eligible: 0, registered: 0, review: 0, rows: [] };
  const selection  = { entered: 0, recommended: 0, notMatched: 0, hold: 0, rows: [] };
  const engagement = { entered: 0, prefsGiven: 0, deferred: 0, declined: 0, rows: [] };
  const fulfillment = { entered: 0, matched: 0, nominated: 0, noMatch: 0, rows: [] };

  const actionQueue = [];

  for (const s of sessions) {
    // Skip need_coordination sessions — this dashboard is volunteer-only
    if (s.workflow === 'need_coordination') continue;

    const ss = parseSS(s);
    const name = extractName(s, ss) || 'Volunteer';
    const phone = extractPhone(s, ss) || '';
    const agent = s.active_agent;

    // ── Onboarding ──
    if (agent === 'onboarding' || ['welcome','orientation_video','eligibility_screening','contact_capture','teaching_profile','registration_review','onboarding_complete'].includes(s.stage)) {
      onboarding.entered++;
      let outcome = 'In Progress';
      if (s.stage === 'onboarding_complete') { onboarding.registered++; outcome = 'Registered'; }
      if (['contact_capture','teaching_profile','registration_review','onboarding_complete'].includes(s.stage)) { onboarding.eligible++; if (outcome === 'In Progress') outcome = 'Eligible'; }
      if (s.stage === 'human_review' && agent === 'onboarding') { onboarding.review++; outcome = 'Needs Review'; }
      onboarding.rows.push({ id: s.id, name, phone, stage: s.stage, status: s.status, outcome, last: s.last_message_at, created: s.created_at });

      if (s.stage === 'human_review') {
        actionQueue.push({ id: s.id, name, phone, issue: 'Stuck in onboarding review', stage: 'Onboarding', since: s.last_message_at || s.created_at });
      }
    }

    // ── Selection ──
    if (agent === 'selection' || ['selection_conversation','gathering_preferences'].includes(s.stage)) {
      selection.entered++;
      let outcome = 'In Progress';
      const selOutcome = ss.outcome;
      if (selOutcome === 'recommended') { selection.recommended++; outcome = 'Recommended'; }
      else if (selOutcome === 'not_matched') { selection.notMatched++; outcome = 'Not Matched'; }
      else if (selOutcome === 'human_review' || s.stage === 'human_review') { selection.hold++; outcome = 'On Hold'; }
      selection.rows.push({ id: s.id, name, phone, stage: s.stage, status: s.status, outcome, last: s.last_message_at, created: s.created_at });

      if (s.stage === 'human_review' || selOutcome === 'human_review') {
        actionQueue.push({ id: s.id, name, phone, issue: 'Selection needs review', stage: 'Selection', since: s.last_message_at || s.created_at });
      }
    }

    // ── Engagement ──
    if (agent === 'engagement') {
      engagement.entered++;
      let outcome = 'In Progress';
      if (ss.preference_notes) { engagement.prefsGiven++; outcome = 'Prefs Given'; }
      if (ss.deferred) { engagement.deferred++; outcome = 'Deferred'; }
      const reviewReason = ss.human_review_reason;
      if (reviewReason === 'volunteer_declined') { engagement.declined++; outcome = 'Declined'; }
      engagement.rows.push({ id: s.id, name, phone, stage: s.stage, status: s.status, outcome, prefs: ss.preference_notes || '', last: s.last_message_at, created: s.created_at });

      if (ss.deferred) {
        actionQueue.push({ id: s.id, name, phone, issue: `Deferred: ${ss.deferred_reason || 'no reason'}`, stage: 'Engagement', since: s.last_message_at || s.created_at });
      }
      if (s.stage === 'human_review') {
        actionQueue.push({ id: s.id, name, phone, issue: reviewReason?.replace(/_/g, ' ') || 'Needs review', stage: 'Engagement', since: s.last_message_at || s.created_at });
      }
    }

    // ── Fulfillment ──
    if (agent === 'fulfillment') {
      fulfillment.entered++;
      let outcome = 'In Progress';
      const mr = ss.match_result || {};
      if (mr.status === 'found' || mr.status === 'multiple') { fulfillment.matched++; outcome = 'Matched'; }
      if (mr.status === 'not_found') { fulfillment.noMatch++; outcome = 'No Match'; }
      if (ss.nominated_need_id) { fulfillment.nominated++; outcome = 'Nominated'; }
      const candidateNames = (mr.candidates || []).map(c => c.name || c.school_name || c.id?.slice(0, 10) || '?');
      fulfillment.rows.push({ id: s.id, name, phone, stage: s.stage, status: s.status, outcome, needsShown: candidateNames.join(', '), nominatedNeed: ss.nominated_need_id, last: s.last_message_at, created: s.created_at });

      if (mr.status === 'not_found') {
        actionQueue.push({ id: s.id, name, phone, issue: 'No matching need found', stage: 'Fulfillment', since: s.last_message_at || s.created_at });
      }
      if (s.stage === 'human_review') {
        actionQueue.push({ id: s.id, name, phone, issue: ss.human_review_reason?.replace(/_/g, ' ') || 'Needs review', stage: 'Fulfillment', since: s.last_message_at || s.created_at });
      }
    }

    // ── Paused too long (any stage) ──
    if (s.status === 'paused' && s.last_message_at) {
      const days = daysBetween(s.last_message_at, new Date().toISOString());
      if (days && days > 3) {
        actionQueue.push({ id: s.id, name, phone, issue: `Paused for ${days} days`, stage: agent || s.stage, since: s.last_message_at });
      }
    }
  }

  // Sort action queue by urgency (oldest first)
  actionQueue.sort((a, b) => new Date(a.since) - new Date(b.since));

  // Compute placement time
  const placedSessions = sessions.filter(s => {
    const ss = parseSS(s);
    return ss.nominated_need_id && s.created_at;
  });
  let avgPlacementDays = null;
  if (placedSessions.length > 0) {
    const totalDays = placedSessions.reduce((sum, s) => {
      const d = daysBetween(s.created_at, s.last_message_at || new Date().toISOString());
      return sum + (d || 0);
    }, 0);
    avgPlacementDays = Math.round(totalDays / placedSessions.length);
  }

  // Drop-off: started onboarding but never reached fulfillment
  const totalStarted = onboarding.entered || 1;
  const reachedFulfillment = fulfillment.entered;
  const dropOffRate = totalStarted > 0 ? Math.round((1 - reachedFulfillment / totalStarted) * 100) : 0;

  return { onboarding, selection, engagement, fulfillment, actionQueue, avgPlacementDays, dropOffRate };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Shared UI components
// ═══════════════════════════════════════════════════════════════════════════════

const KpiCard = ({ label, value, sub, icon: Icon, color = 'bg-blue-50', iconColor = 'text-blue-600' }) => (
  <Card className="border-none shadow-sm">
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

const OutcomePill = ({ outcome }) => {
  const map = {
    'Eligible':      'bg-emerald-100 text-emerald-700',
    'Registered':    'bg-cyan-100 text-cyan-700',
    'Needs Review':  'bg-amber-100 text-amber-700',
    'In Progress':   'bg-blue-100 text-blue-700',
    'Recommended':   'bg-emerald-100 text-emerald-700',
    'Not Matched':   'bg-red-100 text-red-600',
    'On Hold':       'bg-amber-100 text-amber-700',
    'Prefs Given':   'bg-cyan-100 text-cyan-700',
    'Deferred':      'bg-amber-100 text-amber-700',
    'Declined':      'bg-red-100 text-red-600',
    'Matched':       'bg-emerald-100 text-emerald-700',
    'Nominated':     'bg-teal-100 text-teal-700',
    'No Match':      'bg-red-100 text-red-600',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap ${map[outcome] || 'bg-slate-100 text-slate-600'}`}>
      {outcome}
    </span>
  );
};

const PAGE_SIZE = 10;

const PaginatedTable = ({ rows, columns }) => {
  const [page, setPage] = useState(0);
  const totalPages = Math.ceil(rows.length / PAGE_SIZE);
  const pageRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100">
              {columns.map(c => (
                <th key={c.key} className="text-left text-xs text-slate-400 font-medium py-2 px-3">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 ? (
              <tr><td colSpan={columns.length} className="text-center text-slate-400 py-8 text-sm">No volunteers in this stage</td></tr>
            ) : pageRows.map((row) => (
              <tr key={row.id} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                {columns.map(c => (
                  <td key={c.key} className="py-2 px-3 text-slate-700 text-xs">
                    {c.render ? c.render(row) : row[c.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-3 py-2 text-xs text-slate-500">
          <span>{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, rows.length)} of {rows.length}</span>
          <div className="flex items-center gap-1">
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="p-1 rounded hover:bg-slate-100 disabled:opacity-30" aria-label="Previous page">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span>{page + 1} / {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className="p-1 rounded hover:bg-slate-100 disabled:opacity-30" aria-label="Next page">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </>
  );
};

// ═══════════════════════════════════════════════════════════════════════════════
// Section 1: Login gate
// ═══════════════════════════════════════════════════════════════════════════════

const OpsLogin = ({ onAuthenticated }) => {
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
        setError('Invalid token. Please try again.');
      } else {
        onAuthenticated();
      }
    } catch (err) {
      if (err.response?.status === 401) {
        dashboardAuth.clearToken();
        setError('Invalid token. Please try again.');
      } else {
        onAuthenticated();
      }
    }
    setLoading(false);
  };

  return (
    <div className="bg-slate-50 min-h-[calc(100vh-64px)] flex items-center justify-center">
      <div className="bg-white rounded-xl p-8 w-full max-w-sm shadow-lg border border-slate-200">
        <div className="flex justify-center mb-4">
          <div className="w-12 h-12 rounded-xl bg-emerald-100 flex items-center justify-center">
            <Lock className="w-6 h-6 text-emerald-600" />
          </div>
        </div>
        <h2 className="text-lg font-semibold text-slate-900 text-center mb-1">Volunteer Dashboard</h2>
        <p className="text-xs text-slate-500 text-center mb-6">Enter your access token to continue</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input type="password" placeholder="Access token" value={token} onChange={e => setToken(e.target.value)} className="border-slate-300" autoFocus />
          {error && <p className="text-xs text-red-500">{error}</p>}
          <Button type="submit" disabled={!token.trim() || loading} className="w-full bg-emerald-600 hover:bg-emerald-700 text-white">
            {loading ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : null}
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════════
// Section 2: Overall Pipeline Funnel
// ═══════════════════════════════════════════════════════════════════════════════

const FunnelStage = ({ label, count, convPct, reviewCount, color, isLast }) => (
  <div className="flex items-center gap-0">
    <div className="flex flex-col items-center min-w-[120px]">
      <div className={`w-full rounded-xl px-4 py-3 ${color} text-center`}>
        <p className="text-2xl font-bold">{count}</p>
        <p className="text-xs font-medium opacity-80">{label}</p>
      </div>
      {convPct !== null && (
        <p className="text-xs text-slate-400 mt-1">{convPct}% conv</p>
      )}
      {reviewCount > 0 && (
        <span className="mt-1 text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
          {reviewCount} need review
        </span>
      )}
    </div>
    {!isLast && (
      <ArrowRight className="w-5 h-5 text-slate-300 mx-1 shrink-0" />
    )}
  </div>
);

const PipelineFunnel = ({ onboarding, selection, engagement, fulfillment }) => {
  const conv = (from, to) => from > 0 ? Math.round((to / from) * 100) : null;

  const stages = [
    { label: 'Onboarding', count: onboarding.entered, convPct: null, review: onboarding.review, color: 'bg-blue-100 text-blue-800' },
    { label: 'Selection', count: selection.entered, convPct: conv(onboarding.entered, selection.entered), review: selection.hold, color: 'bg-violet-100 text-violet-800' },
    { label: 'Engagement', count: engagement.entered, convPct: conv(selection.entered, engagement.entered), review: 0, color: 'bg-emerald-100 text-emerald-800' },
    { label: 'Fulfillment', count: fulfillment.entered, convPct: conv(engagement.entered, fulfillment.entered), review: fulfillment.noMatch, color: 'bg-teal-100 text-teal-800' },
    { label: 'Placed', count: fulfillment.nominated, convPct: conv(fulfillment.entered, fulfillment.nominated), review: 0, color: 'bg-cyan-100 text-cyan-800' },
  ];

  return (
    <Card className="border-none shadow-sm">
      <CardHeader className="pb-2 pt-4 px-5">
        <CardTitle className="text-sm text-slate-600 font-medium flex items-center gap-2">
          <BarChart3 className="w-4 h-4" /> End-to-End Pipeline
        </CardTitle>
      </CardHeader>
      <CardContent className="px-5 pb-5">
        <div className="flex items-start justify-center gap-0 overflow-x-auto py-2">
          {stages.map((s, i) => (
            <FunnelStage key={s.label} {...s} reviewCount={s.review} isLast={i === stages.length - 1} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
};

// ═══════════════════════════════════════════════════════════════════════════════
// Section 3: Per-Agent Detail Tabs
// ═══════════════════════════════════════════════════════════════════════════════

const Metric = ({ label, value, color = 'bg-slate-50', textColor = 'text-slate-700' }) => (
  <div className={`rounded-xl p-3 ${color}`}>
    <p className="text-xs text-slate-500">{label}</p>
    <p className={`text-xl font-bold ${textColor}`}>{value}</p>
  </div>
);

const OnboardingPanel = ({ data }) => {
  const columns = [
    { key: 'name', label: 'Name' },
    { key: 'phone', label: 'Phone', render: r => r.phone || '—' },
    { key: 'stage', label: 'Stage' },
    { key: 'outcome', label: 'Outcome', render: r => <OutcomePill outcome={r.outcome} /> },
    { key: 'status', label: 'Status', render: r => <OutcomePill outcome={r.status === 'active' ? 'In Progress' : r.status} /> },
    { key: 'last', label: 'Last Active', render: r => timeAgo(r.last) },
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Metric label="Entered" value={data.entered} color="bg-blue-50" textColor="text-blue-700" />
        <Metric label="Eligible" value={data.eligible} color="bg-emerald-50" textColor="text-emerald-700" />
        <Metric label="Registered" value={data.registered} color="bg-cyan-50" textColor="text-cyan-700" />
        <Metric label="Needs Review" value={data.review} color="bg-amber-50" textColor="text-amber-700" />
      </div>
      <Card className="border-none shadow-sm">
        <CardContent className="p-0">
          <PaginatedTable rows={data.rows} columns={columns} />
        </CardContent>
      </Card>
    </div>
  );
};

const SelectionPanel = ({ data }) => {
  const columns = [
    { key: 'name', label: 'Name' },
    { key: 'phone', label: 'Phone', render: r => r.phone || '—' },
    { key: 'outcome', label: 'Outcome', render: r => <OutcomePill outcome={r.outcome} /> },
    { key: 'status', label: 'Status', render: r => <OutcomePill outcome={r.status === 'active' ? 'In Progress' : r.status} /> },
    { key: 'last', label: 'Last Active', render: r => timeAgo(r.last) },
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Metric label="Entered" value={data.entered} color="bg-violet-50" textColor="text-violet-700" />
        <Metric label="Recommended" value={data.recommended} color="bg-emerald-50" textColor="text-emerald-700" />
        <Metric label="Not Matched" value={data.notMatched} color="bg-red-50" textColor="text-red-600" />
        <Metric label="On Hold" value={data.hold} color="bg-amber-50" textColor="text-amber-700" />
      </div>
      <Card className="border-none shadow-sm">
        <CardContent className="p-0">
          <PaginatedTable rows={data.rows} columns={columns} />
        </CardContent>
      </Card>
    </div>
  );
};

const EngagementPanel = ({ data }) => {
  const columns = [
    { key: 'name', label: 'Name' },
    { key: 'phone', label: 'Phone', render: r => r.phone || '—' },
    { key: 'outcome', label: 'Consent', render: r => <OutcomePill outcome={r.outcome} /> },
    { key: 'prefs', label: 'Preferences', render: r => <span className="text-slate-500 truncate max-w-[180px] block" title={r.prefs}>{r.prefs || '—'}</span> },
    { key: 'last', label: 'Last Active', render: r => timeAgo(r.last) },
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Metric label="In Conversation" value={data.entered} color="bg-emerald-50" textColor="text-emerald-700" />
        <Metric label="Prefs Given" value={data.prefsGiven} color="bg-cyan-50" textColor="text-cyan-700" />
        <Metric label="Deferred" value={data.deferred} color="bg-amber-50" textColor="text-amber-700" />
        <Metric label="Declined" value={data.declined} color="bg-red-50" textColor="text-red-600" />
      </div>
      <Card className="border-none shadow-sm">
        <CardContent className="p-0">
          <PaginatedTable rows={data.rows} columns={columns} />
        </CardContent>
      </Card>
    </div>
  );
};

const FulfillmentPanel = ({ data }) => {
  const columns = [
    { key: 'name', label: 'Name' },
    { key: 'phone', label: 'Phone', render: r => r.phone || '—' },
    { key: 'outcome', label: 'Outcome', render: r => <OutcomePill outcome={r.outcome} /> },
    { key: 'needsShown', label: 'Needs Shown', render: r => <span className="text-slate-500 truncate max-w-[150px] block" title={r.needsShown}>{r.needsShown || '—'}</span> },
    { key: 'nominatedNeed', label: 'Nominated', render: r => r.nominatedNeed ? <span className="text-xs font-mono text-emerald-600" title={r.nominatedNeed}>{r.nominatedNeed.slice(0, 12)}…</span> : <span className="text-slate-400">—</span> },
    { key: 'last', label: 'Last Active', render: r => timeAgo(r.last) },
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Metric label="Matching Active" value={data.entered} color="bg-teal-50" textColor="text-teal-700" />
        <Metric label="Matched" value={data.matched} color="bg-emerald-50" textColor="text-emerald-700" />
        <Metric label="Nominated" value={data.nominated} color="bg-cyan-50" textColor="text-cyan-700" />
        <Metric label="No Match" value={data.noMatch} color="bg-red-50" textColor="text-red-600" />
      </div>
      <Card className="border-none shadow-sm">
        <CardContent className="p-0">
          <PaginatedTable rows={data.rows} columns={columns} />
        </CardContent>
      </Card>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════════
// Section 4: Action Required Queue
// ═══════════════════════════════════════════════════════════════════════════════

const urgencyColor = (since) => {
  if (!since) return 'bg-slate-100 text-slate-600';
  const days = daysBetween(since, new Date().toISOString());
  if (days >= 3) return 'bg-red-100 text-red-700';
  if (days >= 1) return 'bg-amber-100 text-amber-700';
  return 'bg-blue-100 text-blue-700';
};

const urgencyLabel = (since) => {
  if (!since) return '—';
  const days = daysBetween(since, new Date().toISOString());
  if (days >= 3) return `${days}d — urgent`;
  if (days >= 1) return `${days}d`;
  const hours = Math.floor((Date.now() - new Date(since)) / 3600000);
  return hours > 0 ? `${hours}h` : 'just now';
};

const ActionQueue = ({ items }) => (
  <Card className="border-none shadow-sm">
    <CardHeader className="pb-2 pt-4 px-5">
      <CardTitle className="text-sm text-slate-600 font-medium flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-amber-500" /> Action Required
        {items.length > 0 && <span className="ml-1 text-xs font-normal text-slate-400">({items.length})</span>}
      </CardTitle>
    </CardHeader>
    <CardContent className="px-0 pb-2">
      {items.length === 0 ? (
        <div className="text-center py-8 text-sm text-slate-400">
          <CheckCircle2 className="w-8 h-8 mx-auto mb-2 text-emerald-300" />
          All clear — no volunteers need attention right now
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100">
                <th className="text-left text-xs text-slate-400 font-medium py-2 px-4">Priority</th>
                <th className="text-left text-xs text-slate-400 font-medium py-2 px-4">Volunteer</th>
                <th className="text-left text-xs text-slate-400 font-medium py-2 px-4">Phone</th>
                <th className="text-left text-xs text-slate-400 font-medium py-2 px-4">Issue</th>
                <th className="text-left text-xs text-slate-400 font-medium py-2 px-4">Stage</th>
                <th className="text-left text-xs text-slate-400 font-medium py-2 px-4">Waiting</th>
              </tr>
            </thead>
            <tbody>
              {items.slice(0, 20).map((item, i) => (
                <tr key={`${item.id}-${i}`} className="border-b border-slate-50 hover:bg-slate-50">
                  <td className="py-2 px-4">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${urgencyColor(item.since)}`}>
                      {urgencyLabel(item.since)}
                    </span>
                  </td>
                  <td className="py-2 px-4 text-xs text-slate-700 font-medium">{item.name}</td>
                  <td className="py-2 px-4 text-xs text-slate-500">{item.phone || '—'}</td>
                  <td className="py-2 px-4 text-xs text-slate-600 max-w-[200px] truncate" title={item.issue}>{item.issue}</td>
                  <td className="py-2 px-4 text-xs text-slate-500">{item.stage}</td>
                  <td className="py-2 px-4 text-xs text-slate-400">{timeAgo(item.since)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </CardContent>
  </Card>
);

// ═══════════════════════════════════════════════════════════════════════════════
// Main OpsView
// ═══════════════════════════════════════════════════════════════════════════════

export const OpsView = () => {
  const [authed, setAuthed] = useState(dashboardAuth.isAuthenticated());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);

  const CACHE_KEY = 'serve_ops_dashboard_cache';
  const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

  const load = useCallback(async (bypassCache = false) => {
    // Try cache first (unless forced refresh)
    if (!bypassCache) {
      try {
        const cached = sessionStorage.getItem(CACHE_KEY);
        if (cached) {
          const { payload, timestamp } = JSON.parse(cached);
          if (Date.now() - timestamp < CACHE_TTL_MS) {
            setData(payload);
            setLastRefresh(new Date(timestamp));
            setLoading(false);
            return;
          }
        }
      } catch (_) { /* ignore parse errors */ }
    }

    setLoading(true);
    try {
      const res = await dashboardApi.getStats(1, 500);
      if (res.status === 'success') {
        setData(res);
        setLastRefresh(new Date());
        // Save to cache
        try {
          sessionStorage.setItem(CACHE_KEY, JSON.stringify({ payload: res, timestamp: Date.now() }));
        } catch (_) { /* storage full — ignore */ }
      }
    } catch (e) {
      console.error('Dashboard load failed:', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (authed) {
      load(false); // use cache on mount
    }
  }, [authed, load]);

  if (!authed) return <OpsLogin onAuthenticated={() => setAuthed(true)} />;

  const sessions = data?.recent_sessions || [];
  const stats = data?.stats || {};
  const classified = classifyAll(sessions);

  const handleSignOut = () => { dashboardAuth.clearToken(); setAuthed(false); };

  return (
    <div className="bg-slate-50 min-h-[calc(100vh-64px)]" data-testid="ops-view">
      <div className="max-w-[1400px] mx-auto px-6 py-6 space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">Volunteer Dashboard</h1>
            <p className="text-sm text-slate-500">
              eVidyaloka volunteer pipeline
              {lastRefresh && <span className="ml-2 text-slate-400">· updated {timeAgo(lastRefresh)}</span>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => load(true)} disabled={loading}>
              <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
            <Button variant="outline" size="sm" onClick={handleSignOut} className="text-slate-500 hover:text-slate-700">
              Sign out
            </Button>
          </div>
        </div>

        {/* Section 1: Headline KPIs */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <KpiCard label="Total Volunteers" value={stats.sessions?.total || 0} icon={Users} color="bg-blue-50" iconColor="text-blue-600" />
          <KpiCard label="New This Week" value={stats.sessions?.this_week || 0} icon={TrendingUp} color="bg-violet-50" iconColor="text-violet-600" />
          <KpiCard label="Active Now" value={stats.sessions?.active || 0} icon={Clock} color="bg-emerald-50" iconColor="text-emerald-600" />
          <KpiCard label="Fully Placed" value={classified.fulfillment.nominated} icon={Handshake} color="bg-teal-50" iconColor="text-teal-600" />
          <KpiCard label="Avg Placement" value={classified.avgPlacementDays !== null ? `${classified.avgPlacementDays}d` : '—'} icon={Timer} color="bg-cyan-50" iconColor="text-cyan-600" sub="days to nomination" />
          <KpiCard label="Drop-off Rate" value={`${classified.dropOffRate}%`} icon={XCircle} color="bg-red-50" iconColor="text-red-500" sub="didn't reach fulfillment" />
        </div>

        {/* Section 2: Pipeline Funnel */}
        <PipelineFunnel {...classified} />

        {/* Section 3: Per-Agent Detail */}
        <Card className="border-none shadow-sm">
          <Tabs defaultValue="onboarding" className="w-full">
            <CardHeader className="pb-0 pt-4 px-5">
              <TabsList>
                <TabsTrigger value="onboarding" className="flex items-center gap-1.5 text-xs">
                  <Users className="w-3.5 h-3.5" /> Onboarding
                </TabsTrigger>
                <TabsTrigger value="selection" className="flex items-center gap-1.5 text-xs">
                  <UserCheck className="w-3.5 h-3.5" /> Selection
                </TabsTrigger>
                <TabsTrigger value="engagement" className="flex items-center gap-1.5 text-xs">
                  <ArrowRight className="w-3.5 h-3.5" /> Engagement
                </TabsTrigger>
                <TabsTrigger value="fulfillment" className="flex items-center gap-1.5 text-xs">
                  <Handshake className="w-3.5 h-3.5" /> Fulfillment
                </TabsTrigger>
              </TabsList>
            </CardHeader>
            <CardContent className="p-5">
              <TabsContent value="onboarding" className="mt-0"><OnboardingPanel data={classified.onboarding} /></TabsContent>
              <TabsContent value="selection" className="mt-0"><SelectionPanel data={classified.selection} /></TabsContent>
              <TabsContent value="engagement" className="mt-0"><EngagementPanel data={classified.engagement} /></TabsContent>
              <TabsContent value="fulfillment" className="mt-0"><FulfillmentPanel data={classified.fulfillment} /></TabsContent>
            </CardContent>
          </Tabs>
        </Card>

        {/* Section 4: Action Required */}
        <ActionQueue items={classified.actionQueue} />

      </div>
    </div>
  );
};

export default OpsView;

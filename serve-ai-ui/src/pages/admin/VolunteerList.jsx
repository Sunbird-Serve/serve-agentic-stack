/**
 * VolunteerList — All volunteers with status, search, filter, and detail panel.
 * Pulls from the dashboard stats API.
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Search, Users, X, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Card, CardContent } from '../../components/ui/card';
import { Input } from '../../components/ui/input';
import { dashboardApi } from '../../services/api';

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const StatusPill = ({ status }) => {
  const colors = {
    active: 'bg-emerald-100 text-emerald-700',
    paused: 'bg-amber-100 text-amber-700',
    completed: 'bg-blue-100 text-blue-700',
    abandoned: 'bg-slate-100 text-slate-500',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colors[status] || 'bg-slate-100 text-slate-600'}`}>
      {status}
    </span>
  );
};

// ── Signal display helpers ────────────────────────────────────────────────────

const SIGNAL_LABELS = {
  motivation_alignment: 'Motivation',
  continuity_intent: 'Commitment',
  language_comfort: 'Language',
  availability_realism: 'Availability',
  readiness: 'Readiness',
  communication_clarity: 'Communication',
};

const SIGNAL_GOOD = {
  motivation_alignment: ['strong'],
  continuity_intent: ['committed'],
  language_comfort: ['comfortable'],
  availability_realism: ['realistic'],
  readiness: ['ready_now'],
  communication_clarity: ['clear'],
};

const SIGNAL_WARN = {
  motivation_alignment: ['moderate'],
  continuity_intent: ['uncertain'],
  language_comfort: [],
  availability_realism: ['unclear'],
  readiness: ['future_ready'],
  communication_clarity: ['mixed'],
};

function SignalIcon({ value, field }) {
  if (!value || value === 'unknown') return <span className="w-4 h-4 rounded-full bg-slate-200 inline-block" />;
  if (SIGNAL_GOOD[field]?.includes(value)) return <CheckCircle2 className="w-4 h-4 text-emerald-500" />;
  if (SIGNAL_WARN[field]?.includes(value)) return <AlertTriangle className="w-4 h-4 text-amber-500" />;
  return <XCircle className="w-4 h-4 text-red-500" />;
}

function parseSubState(s) {
  try { return s.sub_state ? JSON.parse(s.sub_state) : {}; } catch { return {}; }
}

function getSelectionData(session) {
  const ss = parseSubState(session);
  const signals = ss.signals || {};
  const notes = ss.notes || {};
  const outcome = ss.outcome;
  const outcomeReason = ss.outcome_reason;

  // Also check handoff for selection data
  const handoff = ss.handoff || {};
  const selSignals = handoff.selection_signals || signals;
  const selNotes = handoff.selection_notes || notes;
  const selOutcome = handoff.selection_outcome || outcome;
  const selReason = handoff.selection_reason || outcomeReason;
  const selConfidence = handoff.selection_confidence;

  // For sessions past selection (engagement, fulfillment, delivery),
  // check engagement_context in handoff for selection outcome
  const engCtx = ss.engagement_context || {};
  const inferredOutcome = selOutcome || (
    ['engagement', 'fulfillment', 'delivery_assistant'].includes(session.active_agent)
      ? 'recommended'
      : null
  );

  return { signals: selSignals, notes: selNotes, outcome: inferredOutcome, reason: selReason, confidence: selConfidence };
}

// ── Detail Panel ──────────────────────────────────────────────────────────────

function VolunteerDetail({ session, onClose }) {
  const ss = parseSubState(session);
  const sel = getSelectionData(session);
  const hasSelection = sel.outcome || Object.keys(sel.signals).some(k => sel.signals[k]);
  const agent = session.active_agent;

  // Determine which phases this volunteer has passed through
  const AGENT_ORDER = ['onboarding', 'selection', 'engagement', 'fulfillment', 'delivery_assistant'];
  const currentIdx = AGENT_ORDER.indexOf(agent);
  const passedOnboarding = currentIdx >= 0;
  const passedSelection = currentIdx >= 1;
  const inEngagement = currentIdx >= 2;
  const inFulfillment = currentIdx >= 3;
  const inDelivery = currentIdx >= 4;

  const outcomeColors = {
    recommended: 'bg-emerald-100 text-emerald-700',
    engagement_later: 'bg-amber-100 text-amber-700',
    not_matched: 'bg-red-100 text-red-600',
    human_review: 'bg-violet-100 text-violet-700',
    paused: 'bg-slate-100 text-slate-600',
  };

  // Extract engagement data
  const engPrefs = ss.preference_notes || (ss.handoff || {}).preference_notes;
  const engDeferred = ss.deferred;
  const engDeferredReason = ss.deferred_reason;
  const engDays = (ss.handoff || {}).preference_notes || engPrefs;

  // Extract fulfillment data
  const nominatedNeed = ss.nominated_need_id;
  const matchResult = ss.match_result || {};
  const matchCount = (matchResult.candidates || []).length;

  // Compute onboarding duration
  const createdAt = session.created_at ? new Date(session.created_at) : null;
  const firstSelMsg = null; // Would need conversation data for exact timing

  return (
    <div className="fixed inset-0 md:inset-y-0 md:left-auto md:right-0 md:w-[420px] bg-white shadow-xl border-l border-slate-200 z-50 overflow-y-auto">
      <div className="sticky top-0 bg-white border-b border-slate-100 px-4 py-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">Volunteer Journey</h2>
        <button onClick={onClose} className="p-1 rounded hover:bg-slate-100">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Identity Header */}
        <div className="flex items-center gap-3 pb-3 border-b border-slate-100">
          <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center">
            <span className="text-sm font-bold text-blue-700">
              {(session.volunteer_name || '?')[0].toUpperCase()}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-slate-900 truncate">{session.volunteer_name || 'Unknown'}</p>
            <p className="text-xs text-slate-500">{session.volunteer_phone || '—'} · {session.channel}</p>
          </div>
          <StatusPill status={session.status} />
        </div>

        {/* Journey Timeline */}
        <div className="space-y-0">

          {/* Onboarding */}
          <TimelineStep
            label="Onboarding"
            status={passedSelection ? 'complete' : (agent === 'onboarding' ? 'active' : 'pending')}
          >
            {(() => {
              const ELIG_PASSED_STAGES = ['contact_capture', 'teaching_profile', 'registration_review', 'onboarding_complete', 'selection_conversation', 'gathering_preferences'];
              const eligPassed = passedSelection || ELIG_PASSED_STAGES.includes(session.stage);
              const regDone = passedSelection;
              const reviewReason = ss.review_reason;
              const isIneligible = agent === 'onboarding' && session.stage === 'human_review' && reviewReason;

              if (isIneligible) {
                const reasonLabels = { age_18_plus: 'Under 18', has_internet_and_device: 'No device/internet', accepts_unpaid_role: 'Declined unpaid' };
                return <p className="text-red-600">❌ Not eligible — {reasonLabels[reviewReason] || reviewReason}</p>;
              }
              return (
                <>
                  {eligPassed && <p>✓ Eligibility confirmed</p>}
                  {regDone && <p>✓ Registered in Serve Registry</p>}
                  {!eligPassed && agent === 'onboarding' && <p className="text-blue-600">In progress — {session.stage?.replace(/_/g, ' ')}</p>}
                </>
              );
            })()}
          </TimelineStep>

          {/* Selection */}
          <TimelineStep
            label="Selection"
            status={inEngagement ? 'complete' : (agent === 'selection' ? 'active' : (passedSelection ? 'active' : 'pending'))}
          >
            {hasSelection && (
              <>
                {sel.outcome && (
                  <p>
                    <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full font-medium mr-1.5 ${outcomeColors[sel.outcome] || 'bg-slate-100'}`}>
                      {sel.outcome.replace(/_/g, ' ')}
                    </span>
                    {sel.confidence && <span className="text-slate-400">({Math.round(sel.confidence * 100)}%)</span>}
                  </p>
                )}
                {sel.reason && <p className="text-slate-500 italic">{sel.reason}</p>}
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {Object.entries(SIGNAL_LABELS).map(([key, label]) => {
                    const value = sel.signals[key];
                    if (!value) return null;
                    const isGood = SIGNAL_GOOD[key]?.includes(value);
                    return (
                      <span key={key} className={`text-[10px] px-1.5 py-0.5 rounded ${isGood ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                        {label}: {value}
                      </span>
                    );
                  })}
                </div>
              </>
            )}
            {!hasSelection && !passedSelection && agent !== 'onboarding' && <p className="text-slate-400">Not yet reached</p>}
          </TimelineStep>

          {/* Engagement */}
          <TimelineStep
            label="Engagement"
            status={inFulfillment ? 'complete' : (agent === 'engagement' ? 'active' : (inEngagement ? 'active' : 'pending'))}
          >
            {inEngagement && (
              <>
                {engDays && <p>📅 {engDays}</p>}
                {engDeferred && <p className="text-amber-600">⏸️ Deferred: {engDeferredReason || 'no reason'}</p>}
                {!engDays && !engDeferred && agent === 'engagement' && <p className="text-blue-600">Gathering preferences…</p>}
                {!engDays && !engDeferred && agent !== 'engagement' && <p>✓ Preferences captured</p>}
              </>
            )}
          </TimelineStep>

          {/* Fulfillment */}
          <TimelineStep
            label="Fulfillment"
            status={inDelivery ? 'complete' : (agent === 'fulfillment' ? 'active' : (inFulfillment ? 'active' : 'pending'))}
          >
            {inFulfillment && (
              <>
                {matchCount > 0 && !nominatedNeed && <p>🔍 {matchCount} option{matchCount > 1 ? 's' : ''} shown — exploring</p>}
                {nominatedNeed && <p>✓ Nominated: <span className="font-mono text-[10px]">{nominatedNeed.slice(0, 12)}…</span></p>}
                {matchResult.status === 'not_found' && <p className="text-amber-600">⚠️ No matching need found</p>}
                {!matchResult.status && agent === 'fulfillment' && <p className="text-blue-600">Searching…</p>}
              </>
            )}
          </TimelineStep>

          {/* Delivery */}
          <TimelineStep
            label="Delivery"
            status={inDelivery ? 'active' : 'pending'}
          >
            {inDelivery && (
              <>
                {session.stage === 'activation_started' && <p className="text-blue-600">Activation in progress</p>}
                {session.stage === 'volunteer_acknowledged' && <p>✓ Volunteer acknowledged assignment</p>}
                {session.stage === 'activation_complete' && <p>✓ Teaching sessions underway</p>}
                {session.status === 'escalated' && <p className="text-red-600">🚨 Escalated</p>}
              </>
            )}
          </TimelineStep>

        </div>

        {/* Meta info */}
        <div className="pt-3 border-t border-slate-100 text-[11px] text-slate-400 space-y-1">
          <p>Agent: <span className="capitalize text-slate-600">{agent?.replace('_', ' ')}</span> · Stage: <span className="text-slate-600">{session.stage}</span></p>
          <p>Created: {session.created_at ? new Date(session.created_at).toLocaleString() : '—'}</p>
          <p>Last active: {timeAgo(session.last_message_at)}</p>
        </div>
      </div>
    </div>
  );
}

// Timeline step component
function TimelineStep({ label, status, children }) {
  const colors = {
    complete: 'bg-emerald-500',
    active: 'bg-blue-500',
    pending: 'bg-slate-200',
  };
  const textColors = {
    complete: 'text-slate-700',
    active: 'text-slate-900 font-medium',
    pending: 'text-slate-400',
  };

  return (
    <div className="flex gap-3 pb-4">
      {/* Vertical line + dot */}
      <div className="flex flex-col items-center">
        <div className={`w-3 h-3 rounded-full shrink-0 ${colors[status]}`} />
        <div className="w-0.5 flex-1 bg-slate-100 mt-1" />
      </div>
      {/* Content */}
      <div className="flex-1 min-w-0 pb-1">
        <p className={`text-xs mb-1 ${textColors[status]}`}>{label}</p>
        <div className="text-[11px] text-slate-600 space-y-0.5">
          {children}
        </div>
      </div>
    </div>
  );
}

export function VolunteerList() {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [agentFilter, setAgentFilter] = useState('all');
  const [selectedSession, setSelectedSession] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await dashboardApi.getStats(1, 500);
      if (res.status === 'success') {
        setSessions(res.recent_sessions || []);
      }
    } catch (e) {
      console.error('Load failed:', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Filter and search
  const filtered = sessions.filter((s) => {
    if (s.workflow === 'need_coordination') return false;
    if (s.status === 'archived' || s.status === 'abandoned') return false;
    if (filter !== 'all' && s.status !== filter) return false;
    if (agentFilter !== 'all' && s.active_agent !== agentFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      const name = (s.volunteer_name || '').toLowerCase();
      const phone = (s.volunteer_phone || '').toLowerCase();
      return name.includes(q) || phone.includes(q);
    }
    return true;
  });

  return (
    <div className="p-6 max-w-[1200px] mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
          <Users className="w-5 h-5" /> Volunteers
        </h1>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Search + Filter */}
      <div className="flex gap-3 flex-wrap">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
          <Input
            placeholder="Search by name or phone..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 text-sm"
          />
        </div>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white"
        >
          <option value="all">All Status</option>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="completed">Completed</option>
        </select>
        <select
          value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}
          className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white"
        >
          <option value="all">All Agents</option>
          <option value="onboarding">Onboarding</option>
          <option value="selection">Selection</option>
          <option value="engagement">Engagement</option>
          <option value="fulfillment">Fulfillment</option>
          <option value="delivery_assistant">Delivery</option>
        </select>
      </div>

      {/* Table */}
      <Card className="border-none shadow-sm">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Name</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Phone</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Channel</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Agent</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Stage</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Status</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={7} className="text-center text-slate-400 py-8">No volunteers found</td></tr>
                ) : filtered.map((s) => (
                  <tr
                    key={s.id}
                    onClick={() => setSelectedSession(s)}
                    className="border-b border-slate-50 hover:bg-blue-50 transition-colors cursor-pointer"
                  >
                    <td className="py-2.5 px-4 text-slate-900 font-medium">{s.volunteer_name || '—'}</td>
                    <td className="py-2.5 px-4 text-slate-600">{s.volunteer_phone || '—'}</td>
                    <td className="py-2.5 px-4">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${s.channel === 'whatsapp' ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700'}`}>
                        {s.channel === 'whatsapp' ? 'WA' : 'Web'}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-slate-600 capitalize">{s.active_agent || '—'}</td>
                    <td className="py-2.5 px-4 text-slate-600">{s.stage}</td>
                    <td className="py-2.5 px-4"><StatusPill status={s.status} /></td>
                    <td className="py-2.5 px-4 text-slate-400">{timeAgo(s.last_message_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
      <p className="text-xs text-slate-400">{filtered.length} volunteers shown · click a row for details</p>

      {/* Detail slide-over panel */}
      {selectedSession && (
        <VolunteerDetail session={selectedSession} onClose={() => setSelectedSession(null)} />
      )}
    </div>
  );
}

export default VolunteerList;

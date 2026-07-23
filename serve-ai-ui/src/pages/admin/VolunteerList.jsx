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

  return { signals: selSignals, notes: selNotes, outcome: selOutcome, reason: selReason, confidence: selConfidence };
}

// ── Detail Panel ──────────────────────────────────────────────────────────────

function VolunteerDetail({ session, onClose }) {
  const ss = parseSubState(session);
  const sel = getSelectionData(session);
  const hasSelection = sel.outcome || Object.keys(sel.signals).some(k => sel.signals[k]);

  const outcomeColors = {
    recommended: 'bg-emerald-100 text-emerald-700',
    engagement_later: 'bg-amber-100 text-amber-700',
    not_matched: 'bg-red-100 text-red-600',
    human_review: 'bg-violet-100 text-violet-700',
    paused: 'bg-slate-100 text-slate-600',
  };

  return (
    <div className="fixed inset-0 md:inset-y-0 md:left-auto md:right-0 md:w-96 bg-white shadow-xl border-l border-slate-200 z-50 overflow-y-auto">
      <div className="sticky top-0 bg-white border-b border-slate-100 px-4 py-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">Volunteer Detail</h2>
        <button onClick={onClose} className="p-1 rounded hover:bg-slate-100">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4 space-y-5">
        {/* Identity */}
        <div>
          <h3 className="text-xs font-medium text-slate-400 uppercase mb-2">Identity</h3>
          <div className="space-y-1.5">
            <p className="text-sm"><span className="text-slate-500">Name:</span> <span className="font-medium">{session.volunteer_name || '—'}</span></p>
            <p className="text-sm"><span className="text-slate-500">Phone:</span> {session.volunteer_phone || '—'}</p>
            <p className="text-sm"><span className="text-slate-500">Agent:</span> <span className="capitalize">{session.active_agent}</span></p>
            <p className="text-sm"><span className="text-slate-500">Stage:</span> {session.stage}</p>
            <p className="text-sm"><span className="text-slate-500">Status:</span> <StatusPill status={session.status} /></p>
            <p className="text-sm"><span className="text-slate-500">Last active:</span> {timeAgo(session.last_message_at)}</p>
          </div>
        </div>

        {/* Selection Assessment */}
        {hasSelection && (
          <div>
            <h3 className="text-xs font-medium text-slate-400 uppercase mb-2">Selection Assessment</h3>

            {/* Outcome badge */}
            {sel.outcome && (
              <div className="mb-3">
                <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${outcomeColors[sel.outcome] || 'bg-slate-100'}`}>
                  {sel.outcome.replace(/_/g, ' ')}
                  {sel.confidence && ` (${Math.round(sel.confidence * 100)}%)`}
                </span>
                {sel.reason && <p className="text-xs text-slate-500 mt-1.5">{sel.reason}</p>}
              </div>
            )}

            {/* Signals breakdown */}
            <div className="space-y-2">
              {Object.entries(SIGNAL_LABELS).map(([key, label]) => {
                const value = sel.signals[key];
                const note = sel.notes[key === 'motivation_alignment' ? 'motivation' : key === 'availability_realism' ? 'availability' : key === 'language_comfort' ? 'language_notes' : ''];
                if (!value && value !== null) return null;
                return (
                  <div key={key} className="flex items-start gap-2">
                    <SignalIcon value={value} field={key} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-slate-700">{label}:</span>
                        <span className="text-xs text-slate-500">{value || 'not assessed'}</span>
                      </div>
                      {note && <p className="text-xs text-slate-400 truncate mt-0.5" title={note}>{note}</p>}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Blockers */}
            {sel.signals.blockers && sel.signals.blockers.length > 0 && (
              <div className="mt-2 p-2 bg-red-50 rounded-lg">
                <p className="text-xs font-medium text-red-700">Blockers: {sel.signals.blockers.join(', ')}</p>
              </div>
            )}
          </div>
        )}

        {/* No selection yet */}
        {!hasSelection && (
          <div>
            <h3 className="text-xs font-medium text-slate-400 uppercase mb-2">Selection Assessment</h3>
            <p className="text-xs text-slate-400">Not yet assessed — volunteer hasn't reached selection stage.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export function VolunteerList() {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
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
    if (filter !== 'all' && s.status !== filter) return false;
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
      <div className="flex gap-3">
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
          <option value="all">All</option>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="completed">Completed</option>
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
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Agent</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Stage</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Status</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={6} className="text-center text-slate-400 py-8">No volunteers found</td></tr>
                ) : filtered.map((s) => (
                  <tr
                    key={s.id}
                    onClick={() => setSelectedSession(s)}
                    className="border-b border-slate-50 hover:bg-blue-50 transition-colors cursor-pointer"
                  >
                    <td className="py-2.5 px-4 text-slate-900 font-medium">{s.volunteer_name || '—'}</td>
                    <td className="py-2.5 px-4 text-slate-600">{s.volunteer_phone || '—'}</td>
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

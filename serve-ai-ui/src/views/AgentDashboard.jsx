/**
 * SERVE AI - Agent Operations Dashboard
 * Ops-facing view for Need, Engagement, and Fulfillment agents.
 * No conversation content — only operational metrics and status.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw, Users, FileText, Handshake, AlertTriangle,
  CheckCircle2, Clock, PauseCircle, XCircle, ArrowRight,
  TrendingUp, School, BookOpen, UserCheck, UserX, Loader2,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { ScrollArea } from '../components/ui/scroll-area';
import { dashboardApi } from '../services/api';

// ── Helpers ───────────────────────────────────────────────────────────────────

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const fmtDate = (iso) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
};

// ── Shared components ─────────────────────────────────────────────────────────

const MetricCard = ({ label, value, sub, icon: Icon, color = 'bg-slate-100', textColor = 'text-slate-700' }) => (
  <Card className="border-none shadow-sm">
    <CardContent className="p-4 flex items-center gap-3">
      <div className={`w-10 h-10 rounded-lg ${color} flex items-center justify-center shrink-0`}>
        <Icon className={`w-5 h-5 ${textColor}`} />
      </div>
      <div>
        <p className="text-xs text-slate-500">{label}</p>
        <p className="text-xl font-semibold text-slate-900 leading-tight">{value ?? '—'}</p>
        {sub && <p className="text-xs text-slate-400">{sub}</p>}
      </div>
    </CardContent>
  </Card>
);

const StagePill = ({ stage }) => {
  const map = {
    re_engaging:    { label: 'Re-engaging',    cls: 'bg-blue-100 text-blue-700' },
    human_review:   { label: 'Human Review',   cls: 'bg-orange-100 text-orange-700' },
    paused:         { label: 'Paused',         cls: 'bg-slate-100 text-slate-600' },
    active:         { label: 'Active',         cls: 'bg-emerald-100 text-emerald-700' },
    complete:       { label: 'Complete',       cls: 'bg-cyan-100 text-cyan-700' },
    drafting_need:  { label: 'Drafting',       cls: 'bg-violet-100 text-violet-700' },
    pending_approval: { label: 'Pending',      cls: 'bg-amber-100 text-amber-700' },
    approved:       { label: 'Approved',       cls: 'bg-emerald-100 text-emerald-700' },
    submitted:      { label: 'Submitted',      cls: 'bg-cyan-100 text-cyan-700' },
    rejected:       { label: 'Rejected',       cls: 'bg-red-100 text-red-700' },
    refinement_required: { label: 'Needs Revision', cls: 'bg-yellow-100 text-yellow-700' },
    fulfillment_handoff_ready: { label: 'Handoff Ready', cls: 'bg-teal-100 text-teal-700' },
  };
  const cfg = map[stage] || { label: stage, cls: 'bg-slate-100 text-slate-600' };
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg.cls}`}>{cfg.label}</span>;
};

const OutcomePill = ({ outcome }) => {
  const map = {
    ready:          { label: 'Ready',          cls: 'bg-emerald-100 text-emerald-700' },
    deferred:       { label: 'Deferred',       cls: 'bg-amber-100 text-amber-700' },
    declined:       { label: 'Declined',       cls: 'bg-red-100 text-red-700' },
    already_active: { label: 'Already Active', cls: 'bg-blue-100 text-blue-700' },
    nominated:      { label: 'Nominated',      cls: 'bg-teal-100 text-teal-700' },
    confirmed:      { label: 'Confirmed',      cls: 'bg-emerald-100 text-emerald-700' },
    no_match:       { label: 'No Match',       cls: 'bg-orange-100 text-orange-700' },
  };
  if (!outcome) return null;
  const cfg = map[outcome] || { label: outcome, cls: 'bg-slate-100 text-slate-600' };
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg.cls}`}>{cfg.label}</span>;
};

const EmptyState = ({ message }) => (
  <div className="flex flex-col items-center justify-center py-12 text-slate-400">
    <Loader2 className="w-6 h-6 mb-2 opacity-40" />
    <p className="text-sm">{message}</p>
  </div>
);

// ── Need Agent Panel ──────────────────────────────────────────────────────────

const NeedAgentPanel = ({ sessions, needs }) => {
  const needSessions = sessions.filter(s =>
    s.workflow === 'need_coordination' || s.active_agent === 'need'
  );

  const byStage = needSessions.reduce((acc, s) => {
    acc[s.stage] = (acc[s.stage] || 0) + 1;
    return acc;
  }, {});

  const pendingApproval = needs.filter(n => n.status === 'pending_approval' || n.status === 'submitted').length;
  const needsRevision   = needs.filter(n => n.status === 'refinement_required').length;
  const approved        = needs.filter(n => n.status === 'approved').length;
  const drafts          = needs.filter(n => n.status === 'draft').length;

  return (
    <div className="space-y-5">
      {/* Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricCard label="Active Sessions"   value={needSessions.filter(s => s.status === 'active').length}  icon={Clock}        color="bg-blue-50"    textColor="text-blue-600" />
        <MetricCard label="Pending Approval"  value={pendingApproval}  icon={AlertTriangle} color="bg-amber-50"   textColor="text-amber-600" />
        <MetricCard label="Needs Revision"    value={needsRevision}    icon={XCircle}       color="bg-red-50"     textColor="text-red-600" />
        <MetricCard label="Approved Needs"    value={approved}         icon={CheckCircle2}  color="bg-emerald-50" textColor="text-emerald-600" />
      </div>

      {/* Stage breakdown */}
      {Object.keys(byStage).length > 0 && (
        <Card className="border-none shadow-sm">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-sm text-slate-600 font-medium">Sessions by Stage</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="flex flex-wrap gap-2">
              {Object.entries(byStage).map(([stage, count]) => (
                <div key={stage} className="flex items-center gap-1.5">
                  <StagePill stage={stage} />
                  <span className="text-xs font-semibold text-slate-700">{count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent needs table */}
      <Card className="border-none shadow-sm">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm text-slate-600 font-medium">Recent Need Submissions</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-2">
          <ScrollArea className="h-72">
            {needs.length === 0 ? (
              <EmptyState message="No needs yet" />
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">School</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Subject / Grade</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Students</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Status</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Submitted</th>
                  </tr>
                </thead>
                <tbody>
                  {needs.map((n) => (
                    <tr key={n.id} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-2.5 text-slate-700 max-w-[160px] truncate">
                        {n.school_name || n.entity_id?.slice(0, 8) || '—'}
                      </td>
                      <td className="px-4 py-2.5 text-slate-600">
                        {(n.subjects || []).join(', ') || '—'}
                        {n.grade_levels?.length > 0 && (
                          <span className="text-slate-400 ml-1">Gr {n.grade_levels.join(', ')}</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-slate-600">{n.student_count ?? '—'}</td>
                      <td className="px-4 py-2.5"><StagePill stage={n.status} /></td>
                      <td className="px-4 py-2.5 text-slate-400 text-xs">{fmtDate(n.submitted_at || n.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
};

// ── Engagement Agent Panel ────────────────────────────────────────────────────

const EngagementAgentPanel = ({ sessions }) => {
  const engSessions = sessions.filter(s =>
    s.workflow === 'returning_volunteer' || s.active_agent === 'engagement'
  );

  const active      = engSessions.filter(s => s.status === 'active' && s.stage === 're_engaging').length;
  const humanReview = engSessions.filter(s => s.stage === 'human_review').length;
  const paused      = engSessions.filter(s => s.stage === 'paused').length;
  const handedOff   = engSessions.filter(s => s.stage === 'active' && s.active_agent === 'fulfillment').length;

  // Parse sub_state to extract outcome signals
  const withOutcome = engSessions.map(s => {
    let outcome = null;
    let continuity = null;
    let reviewReason = null;
    let volunteerName = s.volunteer_name;
    try {
      const ss = s.sub_state ? JSON.parse(s.sub_state) : {};
      reviewReason  = ss.human_review_reason;
      continuity    = ss.continuity;
      volunteerName = ss.engagement_context?.volunteer_name || ss.handoff?.volunteer_name || volunteerName;
      if (ss.deferred) outcome = 'deferred';
      else if (reviewReason === 'volunteer_declined') outcome = 'declined';
      else if (ss.handoff?.volunteer_id) outcome = 'ready';
    } catch (_) {}
    return { ...s, outcome, continuity, reviewReason, volunteerName };
  });

  const readyCount    = withOutcome.filter(s => s.outcome === 'ready').length;
  const deferredCount = withOutcome.filter(s => s.outcome === 'deferred').length;
  const declinedCount = withOutcome.filter(s => s.outcome === 'declined').length;

  return (
    <div className="space-y-5">
      {/* Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricCard label="In Conversation"  value={active}       icon={Users}        color="bg-blue-50"    textColor="text-blue-600" />
        <MetricCard label="Ready → Fulfillment" value={readyCount} icon={ArrowRight}  color="bg-emerald-50" textColor="text-emerald-600" />
        <MetricCard label="Deferred"         value={deferredCount} icon={PauseCircle} color="bg-amber-50"   textColor="text-amber-600" />
        <MetricCard label="Needs Review"     value={humanReview}  icon={AlertTriangle} color="bg-orange-50" textColor="text-orange-600" />
      </div>

      {/* Outcome summary */}
      <div className="grid grid-cols-3 gap-3">
        <Card className="border-none shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-semibold text-emerald-600">{readyCount}</p>
            <p className="text-xs text-slate-500 mt-0.5">Confirmed re-engagement</p>
          </CardContent>
        </Card>
        <Card className="border-none shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-semibold text-amber-600">{deferredCount}</p>
            <p className="text-xs text-slate-500 mt-0.5">Deferred (come back later)</p>
          </CardContent>
        </Card>
        <Card className="border-none shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-semibold text-red-500">{declinedCount}</p>
            <p className="text-xs text-slate-500 mt-0.5">Opted out this cycle</p>
          </CardContent>
        </Card>
      </div>

      {/* Session list */}
      <Card className="border-none shadow-sm">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm text-slate-600 font-medium">Returning Volunteer Sessions</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-2">
          <ScrollArea className="h-72">
            {engSessions.length === 0 ? (
              <EmptyState message="No engagement sessions yet" />
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Volunteer</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Stage</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Outcome</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Continuity</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Last Active</th>
                  </tr>
                </thead>
                <tbody>
                  {withOutcome.map((s) => (
                    <tr key={s.id} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-2.5 text-slate-700">
                        {s.volunteerName || s.actor_id?.slice(0, 10) || '—'}
                      </td>
                      <td className="px-4 py-2.5"><StagePill stage={s.stage} /></td>
                      <td className="px-4 py-2.5"><OutcomePill outcome={s.outcome} /></td>
                      <td className="px-4 py-2.5 text-slate-500 text-xs capitalize">{s.continuity || '—'}</td>
                      <td className="px-4 py-2.5 text-slate-400 text-xs">{timeAgo(s.last_message_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
};

// ── Fulfillment Agent Panel ───────────────────────────────────────────────────

const FulfillmentAgentPanel = ({ sessions }) => {
  const fulSessions = sessions.filter(s => s.active_agent === 'fulfillment');

  const active      = fulSessions.filter(s => s.stage === 'active').length;
  const complete    = fulSessions.filter(s => s.stage === 'complete').length;
  const humanReview = fulSessions.filter(s => s.stage === 'human_review').length;
  const paused      = fulSessions.filter(s => s.stage === 'paused').length;

  // Parse sub_state for match/nomination data
  const enriched = fulSessions.map(s => {
    let nominatedNeedId = null;
    let matchStatus = null;
    let reviewReason = null;
    let volunteerName = s.volunteer_name;
    try {
      const ss = s.sub_state ? JSON.parse(s.sub_state) : {};
      nominatedNeedId = ss.nominated_need_id;
      reviewReason    = ss.human_review_reason;
      matchStatus     = ss.match_result?.status;
      volunteerName   = ss.handoff?.volunteer_name || volunteerName;
    } catch (_) {}
    return { ...s, nominatedNeedId, matchStatus, reviewReason, volunteerName };
  });

  const nominated  = enriched.filter(s => s.nominatedNeedId).length;
  const noMatch    = enriched.filter(s => s.matchStatus === 'not_found').length;

  return (
    <div className="space-y-5">
      {/* Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricCard label="Matching Active"   value={active}       icon={TrendingUp}   color="bg-blue-50"    textColor="text-blue-600" />
        <MetricCard label="Nominated"         value={nominated}    icon={UserCheck}    color="bg-emerald-50" textColor="text-emerald-600" />
        <MetricCard label="No Match Found"    value={noMatch}      icon={UserX}        color="bg-orange-50"  textColor="text-orange-600" />
        <MetricCard label="Needs Review"      value={humanReview}  icon={AlertTriangle} color="bg-red-50"    textColor="text-red-600" />
      </div>

      {/* Outcome summary */}
      <div className="grid grid-cols-3 gap-3">
        <Card className="border-none shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-semibold text-emerald-600">{complete}</p>
            <p className="text-xs text-slate-500 mt-0.5">Placements completed</p>
          </CardContent>
        </Card>
        <Card className="border-none shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-semibold text-blue-600">{active}</p>
            <p className="text-xs text-slate-500 mt-0.5">In matching flow</p>
          </CardContent>
        </Card>
        <Card className="border-none shadow-sm">
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-semibold text-slate-500">{paused}</p>
            <p className="text-xs text-slate-500 mt-0.5">Paused / on hold</p>
          </CardContent>
        </Card>
      </div>

      {/* Session list */}
      <Card className="border-none shadow-sm">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm text-slate-600 font-medium">Fulfillment Sessions</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-2">
          <ScrollArea className="h-72">
            {fulSessions.length === 0 ? (
              <EmptyState message="No fulfillment sessions yet" />
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Volunteer</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Stage</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Match</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Review Reason</th>
                    <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Last Active</th>
                  </tr>
                </thead>
                <tbody>
                  {enriched.map((s) => (
                    <tr key={s.id} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-2.5 text-slate-700">
                        {s.volunteerName || s.actor_id?.slice(0, 10) || '—'}
                      </td>
                      <td className="px-4 py-2.5"><StagePill stage={s.stage} /></td>
                      <td className="px-4 py-2.5">
                        {s.nominatedNeedId
                          ? <OutcomePill outcome="nominated" />
                          : s.matchStatus === 'not_found'
                            ? <OutcomePill outcome="no_match" />
                            : <span className="text-xs text-slate-400">—</span>
                        }
                      </td>
                      <td className="px-4 py-2.5 text-slate-500 text-xs">
                        {s.reviewReason?.replace(/_/g, ' ') || '—'}
                      </td>
                      <td className="px-4 py-2.5 text-slate-400 text-xs">{timeAgo(s.last_message_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

export const AgentDashboard = () => {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await dashboardApi.getStats();
      if (res.status === 'success') {
        setData(res);
        setLastRefresh(new Date());
      } else {
        setError(res.error || 'Failed to load data');
      }
    } catch (e) {
      setError('Could not reach the dashboard service');
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const sessions = data?.recent_sessions || [];
  const needs    = data?.recent_needs    || [];
  const stats    = data?.stats           || {};

  // Top-level cross-agent summary
  const totalActive     = stats.sessions?.active ?? 0;
  const totalThisWeek   = stats.sessions?.this_week ?? 0;
  const totalNeeds      = stats.needs?.total ?? 0;
  const submittedNeeds  = stats.needs?.submitted ?? 0;

  return (
    <div className="p-6 bg-slate-50 min-h-[calc(100vh-64px)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Agent Operations</h2>
          <p className="text-sm text-slate-500">
            Need · Engagement · Fulfillment
            {lastRefresh && (
              <span className="ml-2 text-slate-400">· updated {timeAgo(lastRefresh)}</span>
            )}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 rounded-lg bg-red-50 text-red-700 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Cross-agent summary strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <MetricCard label="Active Sessions"   value={totalActive}    icon={Clock}      color="bg-blue-500"    textColor="text-white" />
        <MetricCard label="Sessions This Week" value={totalThisWeek} icon={TrendingUp}  color="bg-violet-500"  textColor="text-white" />
        <MetricCard label="Total Needs"        value={totalNeeds}    icon={FileText}    color="bg-amber-500"   textColor="text-white" />
        <MetricCard label="Needs Submitted"    value={submittedNeeds} icon={CheckCircle2} color="bg-emerald-500" textColor="text-white" />
      </div>

      {/* Per-agent tabs */}
      <Tabs defaultValue="need">
        <TabsList className="mb-4">
          <TabsTrigger value="need" className="flex items-center gap-1.5">
            <BookOpen className="w-3.5 h-3.5" /> Need Agent
          </TabsTrigger>
          <TabsTrigger value="engagement" className="flex items-center gap-1.5">
            <Users className="w-3.5 h-3.5" /> Engagement
          </TabsTrigger>
          <TabsTrigger value="fulfillment" className="flex items-center gap-1.5">
            <Handshake className="w-3.5 h-3.5" /> Fulfillment
          </TabsTrigger>
        </TabsList>

        <TabsContent value="need">
          <NeedAgentPanel sessions={sessions} needs={needs} />
        </TabsContent>
        <TabsContent value="engagement">
          <EngagementAgentPanel sessions={sessions} />
        </TabsContent>
        <TabsContent value="fulfillment">
          <FulfillmentAgentPanel sessions={sessions} />
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default AgentDashboard;

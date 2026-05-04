/**
 * SERVE AI - Ops/Coordinator View
 * Pipeline dashboard for managing volunteer entries
 */
import { useState, useEffect } from 'react';
import { RefreshCw, User, Clock, CheckCircle, PauseCircle, AlertCircle, UserPlus, Lock } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { ScrollArea } from '../components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Input } from '../components/ui/input';
import { mcpApi, dashboardApi, dashboardAuth } from '../services/api';
import AgentDashboard from './AgentDashboard';
import PipelineDashboard from './PipelineDashboard';

// ── OpsLogin ──────────────────────────────────────────────────────────────────

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
        // Network error but token saved — let them through
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
        <h2 className="text-lg font-semibold text-slate-900 text-center mb-1">Operations Dashboard</h2>
        <p className="text-xs text-slate-500 text-center mb-6">Enter your access token to continue</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            type="password"
            placeholder="Access token"
            value={token}
            onChange={e => setToken(e.target.value)}
            className="border-slate-300"
            autoFocus
          />
          {error && <p className="text-xs text-red-500">{error}</p>}
          <Button
            type="submit"
            disabled={!token.trim() || loading}
            className="w-full bg-emerald-600 hover:bg-emerald-700 text-white"
          >
            {loading ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : null}
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
};

// Status badge component
const StatusBadge = ({ status }) => {
  const config = {
    active: { label: 'Active', className: 'status-badge active', icon: Clock },
    paused: { label: 'Paused', className: 'status-badge paused', icon: PauseCircle },
    completed: { label: 'Completed', className: 'status-badge completed', icon: CheckCircle },
    abandoned: { label: 'Abandoned', className: 'bg-red-100 text-red-600', icon: AlertCircle },
    escalated: { label: 'Escalated', className: 'bg-orange-100 text-orange-600', icon: AlertCircle },
  };

  const statusConfig = config[status] || config.active;
  const Icon = statusConfig.icon;

  return (
    <span className={`${statusConfig.className} flex items-center gap-1`}>
      <Icon className="w-3 h-3" />
      {statusConfig.label}
    </span>
  );
};

// Pipeline card component
const PipelineCard = ({ session, onClick }) => {
  const stageLabels = {
    init: 'Starting',
    intent_discovery: 'Discovering Intent',
    purpose_orientation: 'Learning Purpose',
    eligibility_confirmation: 'Confirming Info',
    capability_discovery: 'Exploring Skills',
    profile_confirmation: 'Reviewing Profile',
    onboarding_complete: 'Completed',
    paused: 'Paused',
  };

  const statusClass = {
    active: 'status-active',
    paused: 'status-paused',
    completed: 'status-active',
  };

  return (
    <div
      className={`pipeline-card ${statusClass[session.status] || ''} cursor-pointer`}
      onClick={() => onClick(session)}
      data-testid={`pipeline-card-${session.id}`}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center">
            <User className="w-4 h-4 text-slate-600" />
          </div>
          <div>
            <p className="font-medium text-slate-900 text-sm">
              {session.volunteer_name || 'New Volunteer'}
            </p>
            <p className="text-xs text-slate-500">
              {new Date(session.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>
        <StatusBadge status={session.status} />
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">Stage:</span>
          <span className="text-slate-700 font-medium">
            {stageLabels[session.stage] || session.stage}
          </span>
        </div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">Agent:</span>
          <Badge variant="outline" className="text-xs capitalize">
            {session.active_agent}
          </Badge>
        </div>
      </div>
    </div>
  );
};

// Stats card component
const StatsCard = ({ title, value, icon: Icon, color }) => (
  <Card className="border-none shadow-sm">
    <CardContent className="p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-slate-500">{title}</p>
          <p className="text-2xl font-semibold text-slate-900">{value}</p>
        </div>
        <div className={`w-10 h-10 rounded-lg ${color} flex items-center justify-center`}>
          <Icon className="w-5 h-5 text-white" />
        </div>
      </div>
    </CardContent>
  </Card>
);

// Recommended Volunteer card component
const RecommendedCard = ({ session }) => {
  let volunteerName = session.volunteer_name;
  let volunteerPhone = null;
  let stage = session.stage;
  let identityStatus = 'pending';

  try {
    const ss = session.sub_state ? JSON.parse(session.sub_state) : {};
    volunteerName = ss.engagement_context?.volunteer_name || volunteerName;
    volunteerPhone = ss.engagement_context?.volunteer_phone;
    identityStatus = ss.identity_verified === true ? 'verified'
                   : ss.identity_verified === false ? 'not_registered'
                   : 'pending';
    if (!volunteerPhone) {
      try {
        const cm = typeof session.channel_metadata === 'string' ? JSON.parse(session.channel_metadata) : (session.channel_metadata || {});
        volunteerPhone = cm.volunteer_phone;
      } catch (_) {}
    }
  } catch (_) {}

  const identityColor = identityStatus === 'verified' ? 'bg-emerald-100 text-emerald-700'
                       : identityStatus === 'not_registered' ? 'bg-red-100 text-red-700'
                       : 'bg-slate-100 text-slate-600';

  const stageLabels = {
    verifying_identity: 'Verifying Identity',
    gathering_preferences: 'Gathering Preferences',
    active: 'Active',
    not_registered: 'Not Registered',
    human_review: 'Human Review',
    paused: 'Paused',
  };

  return (
    <div className="pipeline-card cursor-default">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-violet-100 flex items-center justify-center">
            <UserPlus className="w-4 h-4 text-violet-600" />
          </div>
          <div>
            <p className="font-medium text-slate-900 text-sm">
              {volunteerName || 'Recommended Volunteer'}
            </p>
            <p className="text-xs text-slate-500">
              {volunteerPhone || '—'}
            </p>
          </div>
        </div>
        <StatusBadge status={session.status} />
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">Stage:</span>
          <span className="text-slate-700 font-medium">
            {stageLabels[stage] || stage}
          </span>
        </div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">Identity:</span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${identityColor}`}>
            {identityStatus === 'verified' ? 'Verified' : identityStatus === 'not_registered' ? 'Not Registered' : 'Pending'}
          </span>
        </div>
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">Last Active:</span>
          <span className="text-slate-600 text-xs">
            {session.last_message_at ? new Date(session.last_message_at).toLocaleDateString() : '—'}
          </span>
        </div>
      </div>
    </div>
  );
};

// Recommended Volunteers panel
const RecommendedVolunteersPanel = ({ sessions }) => {
  const recommended = sessions.filter(s =>
    s.workflow === 'recommended_volunteer' || s.persona === 'recommended_volunteer'
  );

  const active = recommended.filter(s => s.status === 'active');
  const completed = recommended.filter(s => s.status === 'completed');
  const paused = recommended.filter(s => s.status === 'paused' || s.stage === 'human_review');

  return (
    <div className="space-y-6">
      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard title="Total Recommended" value={recommended.length} icon={UserPlus} color="bg-violet-500" />
        <StatsCard title="Active" value={active.length} icon={Clock} color="bg-emerald-500" />
        <StatsCard title="Completed" value={completed.length} icon={CheckCircle} color="bg-cyan-500" />
        <StatsCard title="Needs Review" value={paused.length} icon={PauseCircle} color="bg-amber-500" />
      </div>

      {/* Cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="border-none shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-emerald-500" />
              In Progress
              <Badge variant="secondary" className="ml-auto">{active.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[500px] pr-4">
              <div className="space-y-3">
                {active.length === 0 ? (
                  <p className="text-sm text-slate-500 text-center py-8">No active sessions</p>
                ) : active.map(s => <RecommendedCard key={s.id} session={s} />)}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>

        <Card className="border-none shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-cyan-500" />
              Completed
              <Badge variant="secondary" className="ml-auto">{completed.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[500px] pr-4">
              <div className="space-y-3">
                {completed.length === 0 ? (
                  <p className="text-sm text-slate-500 text-center py-8">No completed sessions</p>
                ) : completed.map(s => <RecommendedCard key={s.id} session={s} />)}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>

        <Card className="border-none shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-amber-500" />
              Needs Review
              <Badge variant="secondary" className="ml-auto">{paused.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[500px] pr-4">
              <div className="space-y-3">
                {paused.length === 0 ? (
                  <p className="text-sm text-slate-500 text-center py-8">No sessions pending review</p>
                ) : paused.map(s => <RecommendedCard key={s.id} session={s} />)}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export const OpsView = () => {
  const [authed, setAuthed] = useState(dashboardAuth.isAuthenticated());
  const [sessions, setSessions] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedSession, setSelectedSession] = useState(null);
  const [stats, setStats] = useState({
    active: 0,
    completed: 0,
    paused: 0,
    total: 0,
  });

  const fetchSessions = async () => {
    setIsLoading(true);
    try {
      const response = await mcpApi.listSessions(null, 100);
      if (response.status === 'success' && response.data?.sessions) {
        const sessionsData = response.data.sessions;
        setSessions(sessionsData);
        
        // Calculate stats
        const active = sessionsData.filter(s => s.status === 'active').length;
        const completed = sessionsData.filter(s => s.status === 'completed').length;
        const paused = sessionsData.filter(s => s.status === 'paused').length;
        setStats({
          active,
          completed,
          paused,
          total: sessionsData.length,
        });
      }
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
    }
    setIsLoading(false);
  };

  useEffect(() => {
    fetchSessions();
    // Refresh every 30 seconds
    const interval = setInterval(fetchSessions, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleSessionClick = (session) => {
    setSelectedSession(session);
  };

  // Group sessions by status
  const activeSessions = sessions.filter(s => s.status === 'active');
  const completedSessions = sessions.filter(s => s.status === 'completed');
  const pausedSessions = sessions.filter(s => s.status === 'paused');

  if (!authed) {
    return <OpsLogin onAuthenticated={() => setAuthed(true)} />;
  }

  const handleSignOut = () => {
    dashboardAuth.clearToken();
    setAuthed(false);
  };

  return (
    <div className="bg-slate-50 min-h-[calc(100vh-64px)]" data-testid="ops-view">
      <Tabs defaultValue="pipeline_dashboard" className="w-full">
        <div className="px-6 pt-6 pb-0 flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="pipeline_dashboard">Pipeline Dashboard</TabsTrigger>
            <TabsTrigger value="pipeline">Onboarding Pipeline</TabsTrigger>
            <TabsTrigger value="recommended">Recommended Volunteers</TabsTrigger>
            <TabsTrigger value="agents">Agent Dashboard</TabsTrigger>
          </TabsList>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={fetchSessions}
              disabled={isLoading}
              data-testid="refresh-sessions-btn"
            >
              <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleSignOut}
              className="text-slate-500 hover:text-slate-700"
            >
              Sign out
            </Button>
          </div>
        </div>

        {/* ── Pipeline Dashboard tab ── */}
        <TabsContent value="pipeline_dashboard">
          <PipelineDashboard />
        </TabsContent>

        {/* ── Onboarding Pipeline tab ── */}
        <TabsContent value="pipeline" className="p-6 pt-4">
          {/* Stats Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <StatsCard title="Total Volunteers" value={stats.total} icon={User} color="bg-blue-500" />
            <StatsCard title="Active" value={stats.active} icon={Clock} color="bg-emerald-500" />
            <StatsCard title="Completed" value={stats.completed} icon={CheckCircle} color="bg-cyan-500" />
            <StatsCard title="Paused" value={stats.paused} icon={PauseCircle} color="bg-amber-500" />
          </div>

          {/* Pipeline Columns */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <Card className="border-none shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-lg flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-emerald-500" />
                  In Progress
                  <Badge variant="secondary" className="ml-auto">{activeSessions.length}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-[500px] pr-4">
                  <div className="space-y-3">
                    {activeSessions.length === 0 ? (
                      <p className="text-sm text-slate-500 text-center py-8">No active sessions</p>
                    ) : (
                      activeSessions.map((session) => (
                        <PipelineCard key={session.id} session={session} onClick={handleSessionClick} />
                      ))
                    )}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>

            <Card className="border-none shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-lg flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-cyan-500" />
                  Completed
                  <Badge variant="secondary" className="ml-auto">{completedSessions.length}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-[500px] pr-4">
                  <div className="space-y-3">
                    {completedSessions.length === 0 ? (
                      <p className="text-sm text-slate-500 text-center py-8">No completed sessions</p>
                    ) : (
                      completedSessions.map((session) => (
                        <PipelineCard key={session.id} session={session} onClick={handleSessionClick} />
                      ))
                    )}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>

            <Card className="border-none shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-lg flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-amber-500" />
                  Needs Review
                  <Badge variant="secondary" className="ml-auto">{pausedSessions.length}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-[500px] pr-4">
                  <div className="space-y-3">
                    {pausedSessions.length === 0 ? (
                      <p className="text-sm text-slate-500 text-center py-8">No sessions pending review</p>
                    ) : (
                      pausedSessions.map((session) => (
                        <PipelineCard key={session.id} session={session} onClick={handleSessionClick} />
                      ))
                    )}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ── Recommended Volunteers tab ── */}
        <TabsContent value="recommended" className="p-6 pt-4">
          <RecommendedVolunteersPanel sessions={sessions} />
        </TabsContent>

        {/* ── Agent Dashboard tab ── */}
        <TabsContent value="agents">
          <AgentDashboard />
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default OpsView;

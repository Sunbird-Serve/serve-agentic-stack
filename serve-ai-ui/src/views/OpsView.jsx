/**
 * SERVE AI - Ops/Coordinator View
 * Pipeline dashboard for managing volunteer entries
 */
import { useState, useEffect } from 'react';
import { RefreshCw, User, Clock, CheckCircle, PauseCircle, AlertCircle } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { ScrollArea } from '../components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { mcpApi } from '../services/api';
import AgentDashboard from './AgentDashboard';

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

export const OpsView = () => {
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

  return (
    <div className="bg-slate-50 min-h-[calc(100vh-64px)]" data-testid="ops-view">
      <Tabs defaultValue="pipeline" className="w-full">
        <div className="px-6 pt-6 pb-0 flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="pipeline">Onboarding Pipeline</TabsTrigger>
            <TabsTrigger value="agents">Agent Dashboard</TabsTrigger>
          </TabsList>
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
        </div>

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

        {/* ── Agent Dashboard tab ── */}
        <TabsContent value="agents">
          <AgentDashboard />
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default OpsView;

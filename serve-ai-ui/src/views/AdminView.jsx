/**
 * SERVE AI - Tech Admin/Debug View
 * Full telemetry, MCP logs, and session debugging
 */
import { useState, useEffect } from 'react';
import { RefreshCw, Terminal, Database, Cpu, Activity, Search, Copy, Check } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { ScrollArea } from '../components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { mcpApi, healthApi } from '../services/api';

// JSON viewer component
const JsonViewer = ({ data, maxHeight = '300px' }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative">
      <Button
        variant="ghost"
        size="sm"
        className="absolute top-2 right-2 z-10"
        onClick={handleCopy}
      >
        {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      </Button>
      <pre
        className="bg-slate-950 text-slate-100 p-4 rounded-lg overflow-auto text-xs font-mono"
        style={{ maxHeight }}
      >
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
};

// Telemetry event row
const TelemetryRow = ({ event }) => {
  const eventColors = {
    session_start: 'bg-green-100 text-green-700',
    session_end: 'bg-red-100 text-red-700',
    state_transition: 'bg-blue-100 text-blue-700',
    mcp_call: 'bg-purple-100 text-purple-700',
    agent_response: 'bg-cyan-100 text-cyan-700',
    user_message: 'bg-slate-100 text-slate-700',
    handoff: 'bg-orange-100 text-orange-700',
    error: 'bg-red-100 text-red-700',
  };

  return (
    <div className="debug-entry flex items-start gap-3">
      <span className="text-slate-500 text-[10px] whitespace-nowrap">
        {new Date(event.timestamp).toLocaleTimeString()}
      </span>
      <Badge className={`text-[10px] ${eventColors[event.event_type] || 'bg-slate-100'}`}>
        {event.event_type}
      </Badge>
      {event.agent && (
        <Badge variant="outline" className="text-[10px]">
          {event.agent}
        </Badge>
      )}
      <span className="text-slate-300 text-xs truncate flex-1">
        {JSON.stringify(event.data || {}).substring(0, 100)}
      </span>
    </div>
  );
};

export const AdminView = () => {
  const [sessions, setSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [sessionData, setSessionData] = useState(null);
  const [telemetry, setTelemetry] = useState([]);
  const [conversation, setConversation] = useState([]);
  const [healthStatus, setHealthStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  // Fetch sessions list
  const fetchSessions = async () => {
    try {
      const response = await mcpApi.listSessions(null, 50);
      if (response.status === 'success' && response.data?.sessions) {
        setSessions(response.data.sessions);
      }
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
    }
  };

  // Fetch health status
  const fetchHealth = async () => {
    try {
      const response = await healthApi.checkAll();
      setHealthStatus(response);
    } catch (error) {
      console.error('Failed to fetch health:', error);
      setHealthStatus({ status: 'error', error: error.message });
    }
  };

  // Fetch session details
  const fetchSessionDetails = async (sessionId) => {
    setIsLoading(true);
    try {
      const [sessionRes, telemetryRes, convRes] = await Promise.all([
        mcpApi.getSession(sessionId),
        mcpApi.getTelemetry(sessionId, 100),
        mcpApi.getConversation(sessionId, 50),
      ]);

      if (sessionRes.status === 'success') {
        setSessionData(sessionRes.data);
      }
      if (telemetryRes.status === 'success') {
        setTelemetry(telemetryRes.data?.events || []);
      }
      if (convRes.status === 'success') {
        setConversation(convRes.data?.messages || []);
      }
    } catch (error) {
      console.error('Failed to fetch session details:', error);
    }
    setIsLoading(false);
  };

  useEffect(() => {
    fetchSessions();
    fetchHealth();
    const interval = setInterval(fetchHealth, 60000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (selectedSessionId) {
      fetchSessionDetails(selectedSessionId);
    }
  }, [selectedSessionId]);

  const filteredSessions = sessions.filter(s =>
    s.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (s.volunteer_name || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="p-6 bg-slate-100 min-h-[calc(100vh-64px)]" data-testid="admin-view">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">Tech Admin Console</h2>
          <p className="text-slate-500">Debug sessions, telemetry, and MCP calls</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            className={healthStatus?.status === 'healthy' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}
          >
            <Activity className="w-3 h-3 mr-1" />
            {healthStatus?.status || 'Checking...'}
          </Badge>
          <Button variant="outline" onClick={() => { fetchSessions(); fetchHealth(); }} data-testid="refresh-admin-btn">
            <RefreshCw className="w-4 h-4 mr-2" />
            Refresh
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Sessions List */}
        <Card className="border-none shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Database className="w-4 h-4" />
              Sessions
            </CardTitle>
            <div className="relative mt-2">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <Input
                placeholder="Search sessions..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8 text-sm"
                data-testid="session-search-input"
              />
            </div>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[600px]">
              <div className="space-y-2">
                {filteredSessions.map((session) => (
                  <div
                    key={session.id}
                    className={`p-3 rounded-lg cursor-pointer transition-colors ${
                      selectedSessionId === session.id
                        ? 'bg-blue-50 border border-blue-200'
                        : 'bg-white hover:bg-slate-50 border border-slate-200'
                    }`}
                    onClick={() => setSelectedSessionId(session.id)}
                    data-testid={`session-item-${session.id}`}
                  >
                    <p className="text-xs font-mono text-slate-500 truncate">{session.id}</p>
                    <p className="text-sm font-medium text-slate-700 mt-1">
                      {session.volunteer_name || 'Anonymous'}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant="outline" className="text-[10px]">
                        {session.status}
                      </Badge>
                      <Badge variant="outline" className="text-[10px]">
                        {session.stage}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>

        {/* Session Details */}
        <div className="lg:col-span-3">
          {selectedSessionId ? (
            <Card className="border-none shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Cpu className="w-4 h-4" />
                  Session Details
                  <span className="font-mono text-xs text-slate-400 ml-2">
                    {selectedSessionId}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {isLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <RefreshCw className="w-6 h-6 animate-spin text-slate-400" />
                  </div>
                ) : (
                  <Tabs defaultValue="state">
                    <TabsList className="mb-4">
                      <TabsTrigger value="state">State</TabsTrigger>
                      <TabsTrigger value="conversation">Conversation</TabsTrigger>
                      <TabsTrigger value="telemetry">Telemetry</TabsTrigger>
                      <TabsTrigger value="raw">Raw Data</TabsTrigger>
                    </TabsList>

                    <TabsContent value="state">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-4">
                          <div>
                            <h4 className="text-sm font-semibold text-slate-700 mb-2">Session</h4>
                            <JsonViewer data={sessionData?.session || {}} />
                          </div>
                        </div>
                        <div>
                          <h4 className="text-sm font-semibold text-slate-700 mb-2">Volunteer Profile</h4>
                          <JsonViewer data={sessionData?.volunteer_profile || {}} />
                        </div>
                      </div>
                    </TabsContent>

                    <TabsContent value="conversation">
                      <ScrollArea className="h-[500px]">
                        <div className="space-y-3">
                          {conversation.map((msg, idx) => (
                            <div
                              key={idx}
                              className={`p-3 rounded-lg ${
                                msg.role === 'user'
                                  ? 'bg-blue-50 ml-8'
                                  : 'bg-slate-50 mr-8'
                              }`}
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <Badge variant="outline" className="text-[10px] capitalize">
                                  {msg.role}
                                </Badge>
                                {msg.agent && (
                                  <Badge variant="outline" className="text-[10px]">
                                    {msg.agent}
                                  </Badge>
                                )}
                                <span className="text-[10px] text-slate-400">
                                  {new Date(msg.timestamp).toLocaleTimeString()}
                                </span>
                              </div>
                              <p className="text-sm text-slate-700">{msg.content}</p>
                            </div>
                          ))}
                        </div>
                      </ScrollArea>
                    </TabsContent>

                    <TabsContent value="telemetry">
                      <div className="debug-panel">
                        <div className="debug-header flex items-center gap-2">
                          <Terminal className="w-4 h-4" />
                          <span>Telemetry Events</span>
                          <Badge variant="outline" className="ml-auto text-[10px]">
                            {telemetry.length} events
                          </Badge>
                        </div>
                        <ScrollArea className="h-[400px]">
                          <div className="debug-content">
                            {telemetry.map((event, idx) => (
                              <TelemetryRow key={idx} event={event} />
                            ))}
                          </div>
                        </ScrollArea>
                      </div>
                    </TabsContent>

                    <TabsContent value="raw">
                      <JsonViewer
                        data={{
                          session: sessionData?.session,
                          volunteer_profile: sessionData?.volunteer_profile,
                          telemetry_count: telemetry.length,
                          conversation_count: conversation.length,
                        }}
                        maxHeight="500px"
                      />
                    </TabsContent>
                  </Tabs>
                )}
              </CardContent>
            </Card>
          ) : (
            <Card className="border-none shadow-sm">
              <CardContent className="flex items-center justify-center py-16">
                <div className="text-center">
                  <Database className="w-12 h-12 text-slate-300 mx-auto mb-4" />
                  <p className="text-slate-500">Select a session to view details</p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
};

export default AdminView;

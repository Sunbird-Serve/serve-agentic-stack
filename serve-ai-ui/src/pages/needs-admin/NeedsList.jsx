/**
 * NeedsList — Table of all needs with status, school, coordinator info.
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileText, Search } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Card, CardContent } from '../../components/ui/card';
import { Input } from '../../components/ui/input';
import { dashboardApi } from '../../services/api';

const timeAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const StatusPill = ({ status }) => {
  const colors = {
    initiated: 'bg-blue-100 text-blue-700',
    drafting_need: 'bg-amber-100 text-amber-700',
    pending_approval: 'bg-violet-100 text-violet-700',
    submitted: 'bg-violet-100 text-violet-700',
    approved: 'bg-emerald-100 text-emerald-700',
    rejected: 'bg-red-100 text-red-600',
    fulfillment_handoff_ready: 'bg-teal-100 text-teal-700',
    paused: 'bg-slate-100 text-slate-500',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colors[status] || 'bg-slate-100 text-slate-600'}`}>
      {(status || '').replace(/_/g, ' ')}
    </span>
  );
};

export function NeedsList() {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await dashboardApi.getStats(1, 500);
      if (res.status === 'success') {
        setSessions((res.recent_sessions || []).filter(s => s.workflow === 'need_coordination'));
      }
    } catch (e) {
      console.error('Load failed:', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = sessions.filter((s) => {
    if (!search) return true;
    const q = search.toLowerCase();
    const name = (s.volunteer_name || '').toLowerCase();
    const phone = (s.volunteer_phone || '').toLowerCase();
    const stage = (s.stage || '').toLowerCase();
    return name.includes(q) || phone.includes(q) || stage.includes(q);
  });

  return (
    <div className="p-6 max-w-[1200px] mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
          <FileText className="w-5 h-5" /> Needs
        </h1>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      <div className="relative max-w-xs">
        <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
        <Input
          placeholder="Search..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9 text-sm"
        />
      </div>

      <Card className="border-none shadow-sm">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Coordinator</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Phone</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Stage</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Status</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Channel</th>
                  <th className="text-left text-xs text-slate-400 font-medium py-3 px-4">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={6} className="text-center text-slate-400 py-8">No needs found</td></tr>
                ) : filtered.map((s) => (
                  <tr key={s.id} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                    <td className="py-2.5 px-4 text-slate-900 font-medium">{s.volunteer_name || 'Coordinator'}</td>
                    <td className="py-2.5 px-4 text-slate-600">{s.volunteer_phone || '—'}</td>
                    <td className="py-2.5 px-4"><StatusPill status={s.stage} /></td>
                    <td className="py-2.5 px-4 text-slate-600 capitalize">{s.status}</td>
                    <td className="py-2.5 px-4 text-slate-500 capitalize">{s.channel}</td>
                    <td className="py-2.5 px-4 text-slate-400">{timeAgo(s.last_message_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
      <p className="text-xs text-slate-400">{filtered.length} needs shown</p>
    </div>
  );
}

export default NeedsList;

/**
 * SERVE — Main Application (Simplified)
 *
 * Route structure:
 *   /              — Public volunteer chat (no login)
 *   /admin         — Token login for volunteer ops
 *   /admin/*       — Protected volunteer ops routes
 *   /needs-admin   — Token login for need coordination ops
 *   /needs-admin/* — Protected need ops routes
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import '@/App.css';
import { AdminProvider, useAdmin } from './context/AdminContext';
import { VolunteerChatPage } from './pages/VolunteerChatPage';
import { AdminLogin } from './pages/AdminLogin';
import { AdminShell } from './components/layout/AdminShell';
import { DashboardOverview } from './pages/admin/DashboardOverview';
import { VolunteerList } from './pages/admin/VolunteerList';
import { ConversationList } from './pages/admin/ConversationList';
import { AgentStatus } from './pages/admin/AgentStatus';
import { NeedsAdminLogin } from './pages/NeedsAdminLogin';
import { NeedsAdminShell } from './components/layout/NeedsAdminShell';
import { NeedsDashboard } from './pages/needs-admin/NeedsDashboard';
import { NeedsList } from './pages/needs-admin/NeedsList';
import { NeedsConversations } from './pages/needs-admin/NeedsConversations';
import { Toaster } from './components/ui/sonner';

/**
 * AdminGuard — protects /admin/* routes.
 */
function AdminGuard({ children }) {
  const { isAuthenticated } = useAdmin();
  if (!isAuthenticated) {
    return <Navigate to="/admin" replace />;
  }
  return children;
}

/**
 * NeedsAdminGuard — protects /needs-admin/* routes.
 */
function NeedsAdminGuard({ children }) {
  const token = localStorage.getItem('serve_needs_admin_token');
  if (!token) {
    return <Navigate to="/needs-admin" replace />;
  }
  return children;
}

function App() {
  return (
    <AdminProvider>
      <BrowserRouter>
        <Routes>
          {/* Public — volunteer chat, no login */}
          <Route path="/" element={<VolunteerChatPage />} />

          {/* Volunteer ops admin — login */}
          <Route path="/admin" element={<AdminLogin />} />

          {/* Volunteer ops admin — protected pages */}
          <Route element={<AdminGuard><AdminShell /></AdminGuard>}>
            <Route path="/admin/dashboard" element={<DashboardOverview />} />
            <Route path="/admin/volunteers" element={<VolunteerList />} />
            <Route path="/admin/conversations" element={<ConversationList />} />
            <Route path="/admin/agents" element={<AgentStatus />} />
          </Route>

          {/* Needs coordination admin — login */}
          <Route path="/needs-admin" element={<NeedsAdminLogin />} />

          {/* Needs coordination admin — protected pages */}
          <Route element={<NeedsAdminGuard><NeedsAdminShell /></NeedsAdminGuard>}>
            <Route path="/needs-admin/dashboard" element={<NeedsDashboard />} />
            <Route path="/needs-admin/needs" element={<NeedsList />} />
            <Route path="/needs-admin/conversations" element={<NeedsConversations />} />
          </Route>

          {/* Fallback */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <Toaster />
      </BrowserRouter>
    </AdminProvider>
  );
}

export default App;

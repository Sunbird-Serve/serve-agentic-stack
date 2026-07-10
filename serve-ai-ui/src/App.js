/**
 * SERVE — Main Application
 * Uses React Router v7 for URL-based navigation.
 *
 * Route structure:
 *   /onboarding     — Public, no auth required (guest volunteer onboarding)
 *   /conversations  — Auth required (Keycloak)
 *   /operations/*   — Auth required (Keycloak)
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import '@/App.css';
import { useAuth } from './context/AuthContext';
import { AppShell } from './components/layout/AppShell';
import { ConversationsPage } from './pages/ConversationsPage';
import { OnboardingPage } from './pages/OnboardingPage';
import { OperationsLayout } from './pages/operations/OperationsLayout';
import { OverviewTab } from './pages/operations/OverviewTab';
import { ConversationsTab } from './pages/operations/ConversationsTab';
import { PipelineTab } from './pages/operations/PipelineTab';
import { AgentsTab } from './pages/operations/AgentsTab';
import { EvaluationTab } from './pages/operations/EvaluationTab';
import { Toaster } from './components/ui/sonner';
import { useBranding } from './context/BrandingContext';

/**
 * AuthGuard — wraps routes that require authentication.
 * In dev mode (AUTH_ENABLED=false): shows a role picker.
 * In production: shows loading/redirect state while Keycloak initializes.
 */
function AuthGuard({ children }) {
  const { authenticated, initializing, isDevMode, selectRole } = useAuth();
  const { appName, primaryColor } = useBranding();

  if (initializing) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="text-center">
          <div
            className="w-12 h-12 rounded-lg flex items-center justify-center mx-auto mb-4 animate-pulse"
            style={{ backgroundColor: primaryColor }}
          >
            <span className="text-white font-bold text-xl">
              {appName?.charAt(0) || 'S'}
            </span>
          </div>
          <p className="text-slate-500 text-sm">Signing in...</p>
        </div>
      </div>
    );
  }

  // Dev mode: show role picker instead of Keycloak redirect
  if (!authenticated && isDevMode) {
    return <DevRolePicker onSelectRole={selectRole} />;
  }

  if (!authenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <p className="text-slate-500">Redirecting to login...</p>
      </div>
    );
  }

  return children;
}

/**
 * DevRolePicker — Simplified role selector for local development.
 * Allows contributors to test any persona without Keycloak.
 */
function DevRolePicker({ onSelectRole }) {
  const roles = [
    { id: 'volunteer', label: 'Volunteer', description: 'Onboarding & engagement flow' },
    { id: 'need_coordinator', label: 'Need Coordinator', description: 'Need creation flow' },
    { id: 'ops', label: 'Operations', description: 'Pipeline & dashboard views' },
    { id: 'admin', label: 'Admin', description: 'Full system access' },
  ];

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-8">
      <div className="max-w-md w-full">
        <div className="text-center mb-8">
          <div className="w-12 h-12 rounded-lg bg-amber-500 flex items-center justify-center mx-auto mb-4">
            <span className="text-white font-bold text-xl">S</span>
          </div>
          <h1 className="text-xl font-semibold text-slate-900">Dev Mode</h1>
          <p className="text-sm text-slate-500 mt-1">
            Auth is disabled. Pick a role to continue.
          </p>
          <p className="text-xs text-amber-600 mt-2 font-medium">
            Set REACT_APP_AUTH_ENABLED=true to use Keycloak
          </p>
        </div>
        <div className="space-y-3">
          {roles.map((role) => (
            <button
              key={role.id}
              onClick={() => onSelectRole(role.id)}
              className="w-full text-left p-4 bg-white border border-slate-200 rounded-lg hover:border-amber-400 hover:shadow-sm transition-all group"
            >
              <div className="font-medium text-slate-900 group-hover:text-amber-700">
                {role.label}
              </div>
              <div className="text-sm text-slate-500">{role.description}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public route — no auth required */}
        <Route path="/onboarding" element={<OnboardingPage />} />

        {/* Auth-required routes */}
        <Route
          path="/"
          element={
            <AuthGuard>
              <AppShell />
            </AuthGuard>
          }
        >
          <Route index element={<Navigate to="/conversations" replace />} />
          <Route path="conversations" element={<ConversationsPage />} />
          <Route path="conversations/:sessionId" element={<ConversationsPage />} />

          <Route path="operations" element={<OperationsLayout />}>
            <Route index element={<Navigate to="/operations/overview" replace />} />
            <Route path="overview" element={<OverviewTab />} />
            <Route path="conversations" element={<ConversationsTab />} />
            <Route path="pipeline" element={<PipelineTab />} />
            <Route path="agents" element={<AgentsTab />} />
            <Route path="evaluation" element={<EvaluationTab />} />
          </Route>

          <Route path="*" element={<Navigate to="/conversations" replace />} />
        </Route>
      </Routes>
      <Toaster />
    </BrowserRouter>
  );
}

export default App;

/**
 * eVidyaloka - Volunteer Management Platform
 * Main Application with Keycloak JWT role-based routing
 */
import { useState } from 'react';
import '@/App.css';
import { useAuth } from './context/AuthContext';
import { Header } from './components/serve/Header';
import { VolunteerView } from './views/VolunteerView';
import { NeedCoordinatorView } from './views/NeedCoordinatorView';
import { OpsView } from './views/OpsView';
import { AdminView } from './views/AdminView';
import { ReturningVolunteerView } from './views/ReturningVolunteerView';
import { RecommendedVolunteerView } from './views/RecommendedVolunteerView';
import { Toaster } from './components/ui/sonner';

function App() {
  const { authenticated, initializing, user, persona, logout } = useAuth();

  // For volunteers, the agent logic determines sub-persona (new/returning/recommended)
  // This state allows the orchestrator response to switch the volunteer view dynamically
  const [volunteerSubView, setVolunteerSubView] = useState(null);

  // Show loading while Keycloak initializes
  if (initializing) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-4 animate-pulse">
            <span className="text-amber-600 font-bold text-xl">e</span>
          </div>
          <p className="text-slate-500">Signing in...</p>
        </div>
      </div>
    );
  }

  // Should not happen with login-required, but safety net
  if (!authenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <p className="text-slate-500">Redirecting to login...</p>
      </div>
    );
  }

  // Volunteer persona — routed by agent logic to the right sub-view
  if (persona === 'volunteer') {
    const renderVolunteerView = () => {
      switch (volunteerSubView) {
        case 'returning':
          return <ReturningVolunteerView onBack={() => setVolunteerSubView(null)} />;
        case 'recommended':
          return <RecommendedVolunteerView onBack={() => setVolunteerSubView(null)} />;
        default:
          // Default volunteer view — agent determines new/returning/recommended dynamically
          return <VolunteerView onBack={null} />;
      }
    };

    return (
      <div className="app-container" data-testid="serve-ai-app">
        <Header
          currentRole="volunteer"
          user={user}
          onLogout={logout}
          isInternal={false}
        />
        <main className="main-content">
          {renderVolunteerView()}
        </main>
        <Toaster />
      </div>
    );
  }

  // Internal personas (ops, need_coordinator, admin)
  const renderInternalView = () => {
    switch (persona) {
      case 'need_coordinator':
        return <NeedCoordinatorView />;
      case 'ops':
        return <OpsView />;
      case 'admin':
        return <AdminView />;
      default:
        return <OpsView />;
    }
  };

  return (
    <div className="app-container" data-testid="serve-ai-app">
      <Header
        currentRole={persona}
        user={user}
        onLogout={logout}
        isInternal={true}
      />
      <main className="main-content">
        {renderInternalView()}
      </main>
      <Toaster />
    </div>
  );
}

export default App;

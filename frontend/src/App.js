/**
 * eVidyaloka - Volunteer Management Platform
 * Main Application with volunteer-first routing
 */
import { useState, useEffect } from 'react';
import '@/App.css';
import { Header } from './components/serve/Header';
import { RoleSelector } from './views/RoleSelector';
import { VolunteerLanding } from './views/VolunteerLanding';
import { VolunteerView } from './views/VolunteerView';
import { NeedCoordinatorView } from './views/NeedCoordinatorView';
import { OpsView } from './views/OpsView';
import { AdminView } from './views/AdminView';
import { Toaster } from './components/ui/sonner';

// Check if we're on an internal route
const isInternalRoute = () => {
  const path = window.location.pathname;
  return path === '/internal' || path === '/admin-entry' || path.startsWith('/staff');
};

function App() {
  const [currentView, setCurrentView] = useState(null);
  const [isInitialized, setIsInitialized] = useState(false);

  // Initialize based on route
  useEffect(() => {
    if (isInternalRoute()) {
      // Check for saved role preference for internal users
      const savedRole = localStorage.getItem('serve-internal-role');
      if (savedRole) {
        setCurrentView(`internal-${savedRole}`);
      } else {
        setCurrentView('internal-selector');
      }
    } else {
      // Default to volunteer landing page
      setCurrentView('volunteer-landing');
    }
    setIsInitialized(true);
  }, []);

  const handleStartVolunteerJourney = () => {
    setCurrentView('volunteer-chat');
  };

  const handleBackToLanding = () => {
    setCurrentView('volunteer-landing');
  };

  const handleInternalRoleChange = (role) => {
    setCurrentView(`internal-${role}`);
    localStorage.setItem('serve-internal-role', role);
  };

  const handleBackToInternalSelector = () => {
    setCurrentView('internal-selector');
    localStorage.removeItem('serve-internal-role');
  };

  // Show loading state during initialization
  if (!isInitialized) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-4 animate-pulse">
            <span className="text-amber-600 font-bold text-xl">e</span>
          </div>
          <p className="text-slate-500">Loading...</p>
        </div>
      </div>
    );
  }

  // Volunteer-facing views (no header with system terminology)
  if (currentView === 'volunteer-landing') {
    return (
      <>
        <VolunteerLanding onStartJourney={handleStartVolunteerJourney} />
        <Toaster />
      </>
    );
  }

  if (currentView === 'volunteer-chat') {
    return (
      <>
        <VolunteerView onBack={handleBackToLanding} />
        <Toaster />
      </>
    );
  }

  // Internal views (with header and role switcher)
  if (currentView === 'internal-selector') {
    return (
      <>
        <RoleSelector onSelectRole={handleInternalRoleChange} />
        <Toaster />
      </>
    );
  }

  // Render internal view based on role
  const renderInternalView = () => {
    switch (currentView) {
      case 'internal-volunteer':
        return <VolunteerView onBack={handleBackToInternalSelector} />;
      case 'internal-need_coordinator':
        return <NeedCoordinatorView onBack={handleBackToInternalSelector} />;
      case 'internal-ops':
        return <OpsView />;
      case 'internal-admin':
        return <AdminView />;
      default:
        return <RoleSelector onSelectRole={handleInternalRoleChange} />;
    }
  };

  // Get current role for header
  const currentRole = currentView?.replace('internal-', '') || 'ops';

  return (
    <div className="app-container" data-testid="serve-ai-app">
      <Header 
        currentRole={currentRole} 
        onRoleChange={handleInternalRoleChange}
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

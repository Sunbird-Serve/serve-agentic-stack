/**
 * SERVE AI - Main Application
 * Multi-agent volunteer management platform
 */
import { useState, useEffect } from 'react';
import '@/App.css';
import { Header } from './components/serve/Header';
import { RoleSelector } from './views/RoleSelector';
import { VolunteerView } from './views/VolunteerView';
import { OpsView } from './views/OpsView';
import { AdminView } from './views/AdminView';
import { Toaster } from './components/ui/sonner';

function App() {
  const [currentRole, setCurrentRole] = useState(null);
  const [isInitialized, setIsInitialized] = useState(false);

  // Check for saved role preference
  useEffect(() => {
    const savedRole = localStorage.getItem('serve-ai-role');
    if (savedRole) {
      setCurrentRole(savedRole);
    }
    setIsInitialized(true);
  }, []);

  const handleRoleChange = (role) => {
    setCurrentRole(role);
    localStorage.setItem('serve-ai-role', role);
  };

  const handleBackToSelector = () => {
    setCurrentRole(null);
    localStorage.removeItem('serve-ai-role');
  };

  // Show loading state during initialization
  if (!isInitialized) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-center">
          <div className="w-12 h-12 rounded-lg dpga-gradient flex items-center justify-center mx-auto mb-4 animate-pulse">
            <span className="text-white font-bold text-xl">S</span>
          </div>
          <p className="text-slate-500">Loading SERVE AI...</p>
        </div>
      </div>
    );
  }

  // Show role selector if no role selected
  if (!currentRole) {
    return (
      <>
        <RoleSelector onSelectRole={handleRoleChange} />
        <Toaster />
      </>
    );
  }

  // Render appropriate view based on role
  const renderView = () => {
    switch (currentRole) {
      case 'volunteer':
        return <VolunteerView />;
      case 'ops':
        return <OpsView />;
      case 'admin':
        return <AdminView />;
      default:
        return <RoleSelector onSelectRole={handleRoleChange} />;
    }
  };

  return (
    <div className="app-container" data-testid="serve-ai-app">
      <Header currentRole={currentRole} onRoleChange={handleRoleChange} />
      <main className="main-content">
        {renderView()}
      </main>
      <Toaster />
    </div>
  );
}

export default App;

/**
 * AppShell — Root layout with capability-driven sidebar + header + content slot.
 * Renders Sidebar on desktop (>=768px) and MobileNav on mobile.
 */
import { Outlet } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useCapabilities } from '../../hooks/useCapabilities';
import { AppHeader } from './AppHeader';
import { Sidebar } from './Sidebar';
import { MobileNav } from './MobileNav';

export function AppShell() {
  const { user, logout } = useAuth();
  const { persona, navItems } = useCapabilities();

  return (
    <div className="min-h-screen flex flex-col bg-white">
      {/* Header */}
      <AppHeader user={user} persona={persona} onLogout={logout} />

      {/* Body: Sidebar + Content */}
      <div className="flex flex-1 overflow-hidden">
        <Sidebar navItems={navItems} />

        {/* Main content area */}
        <main className="flex-1 overflow-y-auto pb-16 md:pb-0">
          <Outlet />
        </main>
      </div>

      {/* Mobile bottom nav */}
      <MobileNav navItems={navItems} />
    </div>
  );
}

export default AppShell;

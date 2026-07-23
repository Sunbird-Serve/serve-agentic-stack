/**
 * NeedsAdminShell — Layout for needs admin routes with sidebar navigation.
 */
import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { LayoutDashboard, FileText, MessageSquare, LogOut } from 'lucide-react';

const NEEDS_TOKEN_KEY = 'serve_needs_admin_token';

const NAV_ITEMS = [
  { path: '/needs-admin/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/needs-admin/needs', label: 'Needs', icon: FileText },
  { path: '/needs-admin/conversations', label: 'Conversations', icon: MessageSquare },
];

export function NeedsAdminShell() {
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem(NEEDS_TOKEN_KEY);
    navigate('/needs-admin');
  };

  return (
    <div className="min-h-screen flex bg-slate-50">
      {/* Sidebar */}
      <aside className="w-56 bg-white border-r border-slate-100 flex flex-col h-screen sticky top-0">
        <div className="p-4 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-emerald-600 flex items-center justify-center">
              <span className="text-white font-bold text-xs">N</span>
            </div>
            <span className="text-sm font-semibold text-slate-900">Needs Ops</span>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-emerald-50 text-emerald-700 font-medium'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                }`
              }
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-slate-100">
          <button
            onClick={handleLogout}
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-slate-500 hover:text-red-600 hover:bg-red-50 w-full transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Logout
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}

export default NeedsAdminShell;

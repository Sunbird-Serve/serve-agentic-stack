/**
 * eVidyaloka - Header Component
 * Shows user identity from Keycloak JWT and provides logout.
 */
import { Users, Settings, MessageSquare, BookOpen, School, LogOut, User } from 'lucide-react';
import { Button } from '../ui/button';

const ROLES = {
  volunteer: { label: 'Volunteer', icon: MessageSquare, color: 'text-blue-600' },
  need_coordinator: { label: 'Need Coordinator', icon: School, color: 'text-amber-500' },
  ops: { label: 'Operations', icon: Users, color: 'text-emerald-600' },
  admin: { label: 'Tech Admin', icon: Settings, color: 'text-slate-600' },
};

export const Header = ({ currentRole, user, onLogout, isInternal }) => {
  const currentRoleConfig = ROLES[currentRole] || ROLES.volunteer;
  const RoleIcon = currentRoleConfig?.icon || MessageSquare;

  return (
    <header className="serve-header" data-testid="main-header">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo and Brand */}
          <div className="flex items-center gap-3" data-testid="brand-logo">
            <div className="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center">
              <BookOpen className="w-5 h-5 text-amber-600" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-slate-900 tracking-tight">
                eVidyaloka
              </h1>
              <p className="text-xs text-slate-500">
                {isInternal ? 'Staff Portal' : 'Volunteer Platform'}
              </p>
            </div>
          </div>

          {/* User Info + Role Badge + Logout */}
          <div className="flex items-center gap-4">
            {/* Role Badge */}
            <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-slate-100 rounded-full">
              <RoleIcon className={`w-4 h-4 ${currentRoleConfig?.color}`} />
              <span className="text-sm font-medium text-slate-700">
                {currentRoleConfig?.label}
              </span>
            </div>

            {/* User Identity */}
            {user && (
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center">
                  <User className="w-4 h-4 text-slate-600" />
                </div>
                <span className="hidden md:inline text-sm text-slate-700 font-medium">
                  {user.name || user.preferredUsername}
                </span>
              </div>
            )}

            {/* Logout */}
            <Button
              variant="ghost"
              size="sm"
              onClick={onLogout}
              className="text-slate-500 hover:text-red-600"
              title="Sign out"
              data-testid="logout-btn"
            >
              <LogOut className="w-4 h-4" />
              <span className="hidden sm:inline ml-1">Sign out</span>
            </Button>
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header;
